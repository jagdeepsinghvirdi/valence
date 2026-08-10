"""
#4 Extended Leave Approval Workflow (Track B)

Installs / updates:
- Super HOD role
- Workflow states & actions
- Active Leave Application workflow:
    Draft → Pending HOD Approval
    HOD Approve (< 3 days)  → Approved
    HOD Approve (≥ 3 days)  → Pending Super HOD Approval → Super HOD Approve → Approved
    Reject from either pending state → Rejected
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

# total_leave_days is set on Leave Application by HRMS (half days as 0.5)
# Use `or 0` so missing values do not block both Approve paths.
COND_SHORT = "(doc.total_leave_days or 0) < 3"
COND_LONG = "(doc.total_leave_days or 0) >= 3"


def after_migrate():
	ensure_leave_application_workflow()


def ensure_leave_application_workflow():
	"""Idempotent: safe to call on migrate and manually via bench execute."""
	_ensure_roles()
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_ensure_super_hod_permissions()
	_ensure_workflow()
	frappe.clear_cache()
	frappe.db.commit()


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

	for prop in ("read", "write", "submit", "cancel", "email", "print", "share"):
		try:
			update_permission_property("Leave Application", ROLE_SUPER_HOD, 0, prop, 1)
		except Exception:
			# Property may already be set or type-restricted
			pass


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
			"Awaiting Super HOD (leave of 3+ days)",
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
