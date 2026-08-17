"""
#7 OD/WFH Workflow (Track B)

Uses standard HRMS Attendance Request (reason: Work From Home / On Duty).

Same approval rules as Leave Application (#3 / #4):
- Backdated OD/WFH is allowed.
- Future / same-day OD/WFH is HOD-only (no Super HOD), regardless of length.
- Super HOD applies only to backdated requests (from_date before today).
- Length is counted in working days (holidays + week offs excluded).
- Threshold from Attendance Settings → Super HOD After Working Days (default 3).
- Backdated + working days ≤ threshold → HOD Approve → Approved
- Backdated + working days > threshold → HOD Approve → Pending Super HOD
"""

from __future__ import annotations

import frappe

from valence.valence.setup.leave_workflow import (
	COND_BACKDATED,
	COND_NOT_BACKDATED,
	DEFAULT_THRESHOLD,
	ROLE_SUPER_HOD,
	SETTINGS_DOCTYPE,
	STATE_APPROVED,
	STATE_DRAFT,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
	THRESHOLD_FIELD,
	_ensure_roles,
	_ensure_threshold_setting,
	_ensure_workflow_actions,
	_ensure_workflow_states,
	_transition,
)

WORKFLOW_NAME = "OD WFH Request Approval"
DOCTYPE = "Attendance Request"

# Working days used by workflow conditions (same threshold as leave)
WORKING_REQUEST_DAYS_FIELD = "custom_working_request_days"

_THRESHOLD_EXPR = (
	f"float(frappe.db.get_value('{SETTINGS_DOCTYPE}', '{SETTINGS_DOCTYPE}', "
	f"'{THRESHOLD_FIELD}') or {DEFAULT_THRESHOLD})"
)
COND_SHORT = (
	f"({COND_NOT_BACKDATED}) or "
	f"(float(doc.{WORKING_REQUEST_DAYS_FIELD} or 0) <= {_THRESHOLD_EXPR})"
)
COND_LONG = (
	f"({COND_BACKDATED}) and "
	f"(float(doc.{WORKING_REQUEST_DAYS_FIELD} or 0) > {_THRESHOLD_EXPR})"
)


def after_migrate():
	ensure_od_wfh_workflow()


def ensure_od_wfh_workflow():
	"""Idempotent: safe on migrate and via bench execute."""
	_ensure_threshold_setting()
	_ensure_custom_fields()
	_ensure_roles()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_ensure_approver_permissions()
	_ensure_workflow()
	frappe.clear_cache()
	frappe.db.commit()


def _ensure_custom_fields():
	"""Workflow field + working-day count for Super HOD routing."""
	fields = [
		{
			"dt": DOCTYPE,
			"fieldname": "workflow_state",
			"label": "Workflow State",
			"fieldtype": "Link",
			"options": "Workflow State",
			"insert_after": "employee_name",
			"default": STATE_DRAFT,
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
		},
		{
			"dt": DOCTYPE,
			"fieldname": "total_request_days",
			"label": "Total Request Days",
			"fieldtype": "Int",
			"insert_after": "to_date",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"description": "Calendar days in the request period (from_date → to_date).",
		},
		{
			"dt": DOCTYPE,
			"fieldname": WORKING_REQUEST_DAYS_FIELD,
			"label": "Working Request Days",
			"fieldtype": "Float",
			"precision": "1",
			"insert_after": "total_request_days",
			"read_only": 1,
			"description": (
				"Working days in OD/WFH period excluding holidays and week offs. "
				"Compared to Attendance Settings → Super HOD After Working Days "
				"(default 3). Super HOD only for backdated OD/WFH above the threshold. "
				"Future / same-day requests need only HOD, regardless of length."
			),
		},
	]
	for spec in fields:
		existing = frappe.db.exists(
			"Custom Field", {"dt": spec["dt"], "fieldname": spec["fieldname"]}
		)
		if existing:
			# Keep descriptions / labels in sync with leave routing rules
			updates = {
				k: spec[k]
				for k in ("label", "description", "fieldtype", "precision", "hidden", "read_only")
				if k in spec
			}
			if updates:
				frappe.db.set_value(
					"Custom Field",
					{"dt": spec["dt"], "fieldname": spec["fieldname"]},
					updates,
					update_modified=False,
				)
			continue
		doc = frappe.get_doc({"doctype": "Custom Field", "module": "Valence", **spec})
		doc.insert(ignore_permissions=True)


def _ar_state_row(state, doc_status, allow_edit, message=""):
	return {
		"state": state,
		"doc_status": str(doc_status),
		"allow_edit": allow_edit,
		"update_field": "workflow_state",
		"update_value": state,
		"message": message or state,
	}


def _ensure_approver_permissions():
	from frappe.permissions import add_permission, update_permission_property

	for role in ("Leave Approver", ROLE_SUPER_HOD):
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": DOCTYPE, "role": role, "permlevel": 0}
		) and not frappe.db.exists("DocPerm", {"parent": DOCTYPE, "role": role, "permlevel": 0}):
			add_permission(DOCTYPE, role, 0)

		for prop in ("read", "write", "submit", "email", "print", "share"):
			try:
				update_permission_property(DOCTYPE, role, 0, prop, 1)
			except Exception:
				pass


def _ensure_workflow():
	states = [
		_ar_state_row(STATE_DRAFT, 0, "Employee", "Draft OD/WFH request"),
		_ar_state_row(
			STATE_PENDING_HOD,
			0,
			"Leave Approver",
			"Awaiting HOD / Leave Approver",
		),
		_ar_state_row(
			STATE_PENDING_SUPER_HOD,
			0,
			ROLE_SUPER_HOD,
			"Awaiting Super HOD (backdated request above Attendance Settings threshold)",
		),
		_ar_state_row(STATE_APPROVED, 1, "HR Manager", "OD/WFH approved"),
		_ar_state_row(STATE_REJECTED, 0, "HR Manager", "OD/WFH rejected"),
	]

	transitions = []

	for role in ("Employee", "Employee Self Service", "HR User", "HR Manager"):
		transitions.append(
			_transition(STATE_DRAFT, "Apply", STATE_PENDING_HOD, role, allow_self_approval=1)
		)

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
		doc.document_type = DOCTYPE
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
				"document_type": DOCTYPE,
				"is_active": 1,
				"override_status": 0,
				"send_email_alert": 0,
				"workflow_state_field": "workflow_state",
				"states": states,
				"transitions": transitions,
			}
		)
		doc.insert(ignore_permissions=True)

	other = frappe.get_all(
		"Workflow",
		filters={
			"document_type": DOCTYPE,
			"is_active": 1,
			"name": ["!=", WORKFLOW_NAME],
		},
		pluck="name",
	)
	for name in other:
		frappe.db.set_value("Workflow", name, "is_active", 0)
