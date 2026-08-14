"""
#12 Mobile App Approval (Track B)

Whitelisted APIs for HOD / Super HOD leave approve & reject from mobile
(or any API client). Uses standard Frappe workflow under the hood so desk
and mobile stay in sync — including the Super HOD step for long leaves.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_transitions, get_workflow_name
from frappe.utils import cint

ALLOWED_LEAVE_ACTIONS = frozenset({"Apply", "Approve", "Reject"})

PENDING_STATES = (
	"Pending HOD Approval",
	"Pending Super HOD Approval",
)


@frappe.whitelist()
def get_pending_leave_approvals(limit: int = 20) -> list[dict]:
	"""
	Leaves waiting for the current user's workflow action (HOD or Super HOD).

	Mobile: call this to populate an approval inbox.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Login required"), frappe.PermissionError)

	limit = max(1, min(cint(limit) or 20, 100))

	if not get_workflow_name("Leave Application"):
		return []

	# Candidate pool: pending states the user can see via permission query
	candidates = frappe.get_list(
		"Leave Application",
		filters={
			"docstatus": 0,
			"workflow_state": ["in", list(PENDING_STATES)],
		},
		fields=[
			"name",
			"employee",
			"employee_name",
			"leave_type",
			"from_date",
			"to_date",
			"total_leave_days",
			"custom_working_leave_days",
			"workflow_state",
			"status",
			"leave_approver",
			"department",
		],
		order_by="modified desc",
		limit_page_length=limit * 3,  # filter down to actionable
	)

	pending: list[dict] = []
	for row in candidates:
		doc = frappe.get_doc("Leave Application", row.name)
		actions = _actions_for_user(doc)
		# Inbox = can Approve or Reject (not Apply)
		approver_actions = [a for a in actions if a in ("Approve", "Reject")]
		if not approver_actions:
			continue
		pending.append(
			{
				**row,
				"available_actions": approver_actions,
			}
		)
		if len(pending) >= limit:
			break

	return pending


@frappe.whitelist()
def get_leave_workflow_actions(leave_application: str) -> dict:
	"""
	Return current workflow state and actions available to the logged-in user.
	"""
	doc = _get_leave_or_throw(leave_application)
	doc.check_permission("read")

	return {
		"name": doc.name,
		"workflow_state": doc.get("workflow_state"),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"available_actions": _actions_for_user(doc),
		"working_leave_days": doc.get("custom_working_leave_days"),
		"total_leave_days": doc.total_leave_days,
		"employee": doc.employee,
		"employee_name": doc.employee_name,
		"from_date": doc.from_date,
		"to_date": doc.to_date,
		"leave_type": doc.leave_type,
	}


@frappe.whitelist()
def apply_leave_workflow_action(leave_application: str, action: str) -> dict:
	"""
	Apply a workflow action on a Leave Application (Apply / Approve / Reject).

	This is the mobile-safe entrypoint for HOD and Super HOD approvals —
	same transitions as Desk workflow buttons.
	"""
	action = (action or "").strip()
	if action not in ALLOWED_LEAVE_ACTIONS:
		frappe.throw(
			_("Invalid action {0}. Use one of: {1}").format(
				frappe.bold(action), ", ".join(sorted(ALLOWED_LEAVE_ACTIONS))
			)
		)

	doc = _get_leave_or_throw(leave_application)
	doc.check_permission("write")

	if action not in _actions_for_user(doc):
		frappe.throw(
			_("You are not allowed to {0} leave {1} in state {2}.").format(
				frappe.bold(action),
				frappe.bold(doc.name),
				frappe.bold(doc.get("workflow_state") or "Draft"),
			),
			frappe.PermissionError,
		)

	# Standard Frappe workflow (already @whitelist); keep one code path with Desk
	updated = apply_workflow(doc, action)
	updated.reload()

	return {
		"name": updated.name,
		"action": action,
		"workflow_state": updated.get("workflow_state"),
		"status": updated.status,
		"docstatus": updated.docstatus,
		"available_actions": _actions_for_user(updated),
		"message": _("Leave {0}: {1} → {2}").format(
			updated.name, action, updated.get("workflow_state")
		),
	}


def _get_leave_or_throw(name: str):
	if not name or not frappe.db.exists("Leave Application", name):
		frappe.throw(_("Leave Application {0} not found").format(frappe.bold(name)))
	return frappe.get_doc("Leave Application", name)


def _actions_for_user(doc) -> list[str]:
	"""Unique workflow action names available to the current session user."""
	if not get_workflow_name(doc.doctype):
		return []
	try:
		transitions = get_transitions(doc)
	except Exception:
		return []
	seen: list[str] = []
	for t in transitions:
		action = t.get("action") if isinstance(t, dict) else getattr(t, "action", None)
		if action and action not in seen:
			seen.append(action)
	return seen
