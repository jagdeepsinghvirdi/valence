"""
Single-level approval workflow for Short Leave Application.

Mirrors the pattern used by valence.valence.setup.leave_workflow for Leave
Application, but simpler: only one approval step (Reporting Head / "Leave
Approver" role), matching the confirmed #6 policy — no Super HOD step for
Short Leave.

Reuses the existing "Draft" / "Approved" / "Rejected" Workflow States and the
"Apply" / "Approve" / "Reject" Workflow Action Master records already set up
for Leave Application (see hooks.py fixtures), and adds one new state:
"Pending Approval".

NOTE: this file assumes valence.valence.setup.leave_workflow already created
the "Draft" / "Approved" / "Rejected" Workflow States and the Apply/Approve/
Reject Workflow Action Master records — it runs after that in hooks.py's
after_migrate list. If your leave_workflow.py names these differently, adjust
STATE_DRAFT / STATE_APPROVED / STATE_REJECTED / actions below to match.
"""

import frappe

WORKFLOW_NAME = "Short Leave Application Approval"
DOCTYPE = "Short Leave Application"
APPROVER_ROLE = "Leave Approver"  # same role already used as HOD/Reporting Head elsewhere in this app

STATE_DRAFT = "Draft"
STATE_PENDING = "Pending Approval"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"

ACTION_APPLY = "Apply"
ACTION_APPROVE = "Approve"
ACTION_REJECT = "Reject"


def after_migrate():
	create_pending_state()
	create_workflow()


def create_pending_state():
	if frappe.db.exists("Workflow State", STATE_PENDING):
		return
	frappe.get_doc(
		{
			"doctype": "Workflow State",
			"workflow_state_name": STATE_PENDING,
		}
	).insert(ignore_permissions=True)


def create_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = WORKFLOW_NAME
	workflow.document_type = DOCTYPE
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.send_email_alert = 0

	workflow.append("states", {"state": STATE_DRAFT, "doc_status": "0", "allow_edit": "Employee"})
	workflow.append(
		"states", {"state": STATE_PENDING, "doc_status": "0", "allow_edit": APPROVER_ROLE}
	)
	workflow.append(
		"states", {"state": STATE_APPROVED, "doc_status": "1", "allow_edit": APPROVER_ROLE}
	)
	workflow.append(
		"states", {"state": STATE_REJECTED, "doc_status": "0", "allow_edit": APPROVER_ROLE}
	)

	workflow.append(
		"transitions",
		{"state": STATE_DRAFT, "action": ACTION_APPLY, "next_state": STATE_PENDING, "allowed": "Employee"},
	)
	workflow.append(
		"transitions",
		{
			"state": STATE_PENDING,
			"action": ACTION_APPROVE,
			"next_state": STATE_APPROVED,
			"allowed": APPROVER_ROLE,
		},
	)
	workflow.append(
		"transitions",
		{
			"state": STATE_PENDING,
			"action": ACTION_REJECT,
			"next_state": STATE_REJECTED,
			"allowed": APPROVER_ROLE,
		},
	)

	workflow.insert(ignore_permissions=True)