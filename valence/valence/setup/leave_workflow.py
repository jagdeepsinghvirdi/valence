"""
#3 / #4 Leave Application approval routing (Track B)

- Backdated leave is allowed only within Attendance Settings → Backdated
  Creation Window (Days) counted from the leave START date and after the
  leave END date in working days
  (holidays + weekly offs excluded, default 3). This is a creation rule, not approval.
- Future / same-day leave is HOD-only (no Super HOD), regardless of length.
- Super HOD applies only to backdated leave (from_date before today).
- Working leave days exclude holidays + week offs.
- Super HOD threshold is configurable in Attendance Settings → Super HOD After
  Working Days (default 3). 3 working days or more need Super HOD.
- Backdated + working days < threshold → HOD Approve → Approved
- Backdated + working days >= threshold → HOD Approve → Pending Super HOD → Super HOD Approve
"""

from __future__ import annotations

import frappe

WORKFLOW_NAME = "Leave Application Approval"

# State labels (Workflow State masters)
STATE_DRAFT = "Draft"
STATE_PENDING_HOD = "Pending HOD Approval"
STATE_PENDING_SUPER_HOD = "Pending Super HOD Approval"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"

ROLE_SUPER_HOD = "Super HOD"

ACTIONS = ("Apply", "Approve", "Reject")

WORKING_LEAVE_DAYS_FIELD = "custom_working_leave_days"
SETTINGS_DOCTYPE = "Attendance Settings"
THRESHOLD_FIELD = "super_hod_working_days_threshold"
DEFAULT_THRESHOLD = 3
CREATION_WINDOW_FIELD = "leave_creation_window_days"
DEFAULT_CREATION_WINDOW = 3

# Workflow reads threshold from Attendance Settings (editable by HR / HOD / Super HOD).
# Cast to float — Singles often return strings.
_THRESHOLD_EXPR = (
	f"float(frappe.db.get_value('{SETTINGS_DOCTYPE}', '{SETTINGS_DOCTYPE}', "
	f"'{THRESHOLD_FIELD}') or {DEFAULT_THRESHOLD})"
)
# Super HOD only when from_date is before today. Uses frappe.utils (safe_eval whitelist).
COND_BACKDATED = (
	"frappe.utils.get_datetime(doc.from_date).date() < frappe.utils.now_datetime().date()"
)
COND_NOT_BACKDATED = (
	"frappe.utils.get_datetime(doc.from_date).date() >= frappe.utils.now_datetime().date()"
)
COND_SHORT = (
	f"({COND_NOT_BACKDATED}) or "
	f"(float(doc.{WORKING_LEAVE_DAYS_FIELD} or 0) < {_THRESHOLD_EXPR})"
)
COND_LONG = (
	f"({COND_BACKDATED}) and "
	f"(float(doc.{WORKING_LEAVE_DAYS_FIELD} or 0) >= {_THRESHOLD_EXPR})"
)


def after_migrate():
	ensure_leave_application_workflow()
	repair_historical_leave_workflow_states()
	frappe.db.commit()


def ensure_leave_application_workflow():
	"""Idempotent: safe to call on migrate and manually via bench execute."""
	_ensure_roles()
	_ensure_working_leave_days_field()
	_ensure_threshold_setting()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_ensure_super_hod_permissions()
	_ensure_employee_field_ignores_user_permissions("Leave Application")
	_ensure_workflow()
	frappe.clear_cache()
	frappe.db.commit()


def repair_historical_leave_workflow_states():
	"""Show old approved/rejected leaves as Approved/Rejected, not Draft.

	HRMS `status` is the source of truth. List view uses `workflow_state`, which
	can stay Draft when the workflow field was added (default Draft fills
	existing rows; Frappe only backfills *empty* states). Does not change
	docstatus or leave ledger.
	"""
	if not frappe.db.exists("DocType", "Leave Application"):
		return
	if "workflow_state" not in frappe.get_meta("Leave Application").get_valid_columns():
		return

	frappe.db.sql(
		"""
		UPDATE `tabLeave Application`
		SET `workflow_state` = %s
		WHERE `status` = 'Approved'
		AND coalesce(`workflow_state`, '') IN ('Draft', '')
		""",
		(STATE_APPROVED,),
	)
	frappe.db.sql(
		"""
		UPDATE `tabLeave Application`
		SET `workflow_state` = %s
		WHERE `status` = 'Rejected'
		AND coalesce(`workflow_state`, '') IN ('Draft', '')
		""",
		(STATE_REJECTED,),
	)


def get_super_hod_working_days_threshold() -> int:
	"""Current configurable threshold (working days). Default 3."""
	return _positive_int_setting(THRESHOLD_FIELD, DEFAULT_THRESHOLD)


def get_leave_creation_window_days() -> int:
	"""Working-day window from start date and after end date for creating backdated Leave / OD / WFH.

	Holidays and weekly offs are excluded. Default 3.
	"""
	return _positive_int_setting(CREATION_WINDOW_FIELD, DEFAULT_CREATION_WINDOW)


def _positive_int_setting(fieldname: str, default: int) -> int:
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return default
	if not frappe.get_meta(SETTINGS_DOCTYPE).has_field(fieldname):
		return default
	value = frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname)
	if value in (None, ""):
		return default
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	# 0 / negative treated as unset
	if value <= 0:
		return default
	return value


def _ensure_threshold_setting():
	"""Ensure Single has usable Super HOD + creation-window values."""
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return
	meta = frappe.get_meta(SETTINGS_DOCTYPE)
	if meta.has_field(THRESHOLD_FIELD):
		current = frappe.db.get_single_value(SETTINGS_DOCTYPE, THRESHOLD_FIELD)
		if current in (None, "", 0, "0"):
			frappe.db.set_single_value(SETTINGS_DOCTYPE, THRESHOLD_FIELD, DEFAULT_THRESHOLD)
	if meta.has_field(CREATION_WINDOW_FIELD):
		window = frappe.db.get_single_value(SETTINGS_DOCTYPE, CREATION_WINDOW_FIELD)
		if window in (None, "", 0, "0"):
			frappe.db.set_single_value(
				SETTINGS_DOCTYPE, CREATION_WINDOW_FIELD, DEFAULT_CREATION_WINDOW
			)


def _ensure_working_leave_days_field():
	"""Custom field used by workflow conditions for Super HOD routing."""
	if frappe.db.exists("Custom Field", {"dt": "Leave Application", "fieldname": WORKING_LEAVE_DAYS_FIELD}):
		# Keep description in sync with configurable threshold messaging
		frappe.db.set_value(
			"Custom Field",
			{"dt": "Leave Application", "fieldname": WORKING_LEAVE_DAYS_FIELD},
			"description",
			(
				"Working days in leave period excluding holidays and week offs. "
				"Compared to Attendance Settings → Super HOD After Working Days "
				"(default 3). Super HOD for backdated leave of 3 working days or more. "
				"Future / same-day leave needs only HOD, regardless of length. "
				"Backdated leave is allowed."
			),
			update_modified=False,
		)
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Leave Application",
			"module": "Valence",
			"label": "Working Leave Days",
			"fieldname": WORKING_LEAVE_DAYS_FIELD,
			"fieldtype": "Float",
			"precision": "1",
			"insert_after": "total_leave_days",
			"read_only": 1,
			"description": (
				"Working days in leave period excluding holidays and week offs. "
				"Compared to Attendance Settings → Super HOD After Working Days "
				"(default 3). Super HOD for backdated leave of 3 working days or more. "
				"Future / same-day leave needs only HOD, regardless of length. "
				"Backdated leave is allowed."
			),
		}
	).insert(ignore_permissions=True)


def _ensure_roles():
	if not frappe.db.exists("Role", ROLE_SUPER_HOD):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": ROLE_SUPER_HOD,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)


def _ensure_super_hod_permissions():
	"""Super HOD must read/write/submit Leave Application to complete workflow actions."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists(
		"Custom DocPerm", {"parent": "Leave Application", "role": ROLE_SUPER_HOD, "permlevel": 0}
	) and not frappe.db.exists(
		"DocPerm", {"parent": "Leave Application", "role": ROLE_SUPER_HOD, "permlevel": 0}
	):
		add_permission("Leave Application", ROLE_SUPER_HOD, 0)

	for prop in ("read", "write", "submit", "cancel", "email", "print", "share", "select"):
		try:
			update_permission_property("Leave Application", ROLE_SUPER_HOD, 0, prop, 1)
		except Exception:
			# Property may already be set or type-restricted
			pass


def _ensure_employee_field_ignores_user_permissions(dt: str):
	"""Stop Employee User Permissions from hiding Leave / OD / WFH from Super HOD.

	Creating an Employee with 'Create User Permission' restricts that user to
	their own Employee on every Link field. Super HOD then cannot open another
	person's Leave Application even with role perms. Department-wise access is
	already enforced by permission_query_conditions / has_permission.
	"""
	if not frappe.db.exists("DocType", dt):
		return
	if not frappe.get_meta(dt).has_field("employee"):
		return

	filters = {
		"doc_type": dt,
		"field_name": "employee",
		"property": "ignore_user_permissions",
	}
	name = frappe.db.exists("Property Setter", filters)
	if name:
		frappe.db.set_value("Property Setter", name, "value", "1", update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": dt,
			"field_name": "employee",
			"property": "ignore_user_permissions",
			"property_type": "Check",
			"value": "1",
			"module": "Valence",
		}
	).insert(ignore_permissions=True)


def _ensure_workflow_states():
	styles = {
		STATE_DRAFT: "Inverse",
		STATE_PENDING_HOD: "Warning",
		STATE_PENDING_SUPER_HOD: "Warning",
		STATE_APPROVED: "Success",
		STATE_REJECTED: "Danger",
	}
	for state, style in styles.items():
		if frappe.db.exists("Workflow State", state):
			frappe.db.set_value("Workflow State", state, "style", style, update_modified=False)
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow State",
				"workflow_state_name": state,
				"style": style,
			}
		).insert(ignore_permissions=True)


def _ensure_workflow_actions():
	for action in ACTIONS:
		if frappe.db.exists("Workflow Action Master", action):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": action,
			}
		).insert(ignore_permissions=True)


def _state_row(state, doc_status, allow_edit, update_value=None, message=""):
	row = {
		"state": state,
		"doc_status": str(doc_status),
		"allow_edit": allow_edit,
		"update_field": "status",
		"message": message or state,
	}
	if update_value is not None:
		row["update_value"] = update_value
	return row


def _transition(state, action, next_state, allowed, condition="", allow_self_approval=0):
	return {
		"state": state,
		"action": action,
		"next_state": next_state,
		"allowed": allowed,
		"allow_self_approval": allow_self_approval,
		"condition": condition,
	}


def _ensure_workflow():
	states = [
		_state_row(STATE_DRAFT, 0, "Employee", "Open", "Draft leave application"),
		_state_row(
			STATE_PENDING_HOD,
			0,
			"Leave Approver",
			"Open",
			"Awaiting HOD / Leave Approver",
		),
		_state_row(
			STATE_PENDING_SUPER_HOD,
			0,
			ROLE_SUPER_HOD,
			"Open",
			"Awaiting Super HOD (backdated leave of 3+ working days)",
		),
		_state_row(STATE_APPROVED, 1, "HR Manager", "Approved", "Leave approved"),
		_state_row(STATE_REJECTED, 1, "HR Manager", "Rejected", "Leave rejected"),
	]

	# Multiple `allowed` roles need multiple transition rows (Frappe supports one role per row).
	transitions = []

	# Employee applies
	for role in ("Employee", "Employee Self Service", "HR User", "HR Manager"):
		transitions.append(
			_transition(STATE_DRAFT, "Apply", STATE_PENDING_HOD, role, allow_self_approval=1)
		)

	# HOD / Leave Approver / HR: short leave → Approved
	for role in ("Leave Approver", "HR Manager", "HR User"):
		transitions.append(
			_transition(
				STATE_PENDING_HOD,
				"Approve",
				STATE_APPROVED,
				role,
				condition=COND_SHORT,
				allow_self_approval=0,
			)
		)
		# long leave → Super HOD queue (same action, different condition)
		transitions.append(
			_transition(
				STATE_PENDING_HOD,
				"Approve",
				STATE_PENDING_SUPER_HOD,
				role,
				condition=COND_LONG,
				allow_self_approval=0,
			)
		)
		transitions.append(
			_transition(
				STATE_PENDING_HOD,
				"Reject",
				STATE_REJECTED,
				role,
				allow_self_approval=0,
			)
		)

	# Super HOD final approval
	for role in (ROLE_SUPER_HOD, "HR Manager"):
		transitions.append(
			_transition(
				STATE_PENDING_SUPER_HOD,
				"Approve",
				STATE_APPROVED,
				role,
				allow_self_approval=0,
			)
		)
		transitions.append(
			_transition(
				STATE_PENDING_SUPER_HOD,
				"Reject",
				STATE_REJECTED,
				role,
				allow_self_approval=0,
			)
		)

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		doc = frappe.get_doc("Workflow", WORKFLOW_NAME)
		doc.is_active = 1
		doc.document_type = "Leave Application"
		doc.workflow_state_field = "workflow_state"
		doc.override_status = 0
		doc.send_email_alert = 0
		doc.set("states", [])
		doc.set("transitions", [])
		for row in states:
			doc.append("states", row)
		for row in transitions:
			doc.append("transitions", row)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": WORKFLOW_NAME,
				"document_type": "Leave Application",
				"is_active": 1,
				"override_status": 0,
				"send_email_alert": 0,
				"workflow_state_field": "workflow_state",
				"states": states,
				"transitions": transitions,
			}
		)
		doc.insert(ignore_permissions=True)

	# Deactivate any other active Leave Application workflows
	other = frappe.get_all(
		"Workflow",
		filters={
			"document_type": "Leave Application",
			"is_active": 1,
			"name": ["!=", WORKFLOW_NAME],
		},
		pluck="name",
	)
	for name in other:
		frappe.db.set_value("Workflow", name, "is_active", 0)
