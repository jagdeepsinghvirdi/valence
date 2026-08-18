"""
#7 OD/WFH rules on standard Attendance Request (Work From Home / On Duty).

Aligned with Leave Application routing:
- Working days exclude holidays + week offs
- Super HOD when backdated AND working days > Attendance Settings threshold
- Future / same-day OD/WFH is HOD-only
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, formatdate, getdate

from hrms.hr.doctype.leave_application.leave_application import get_leave_approver
from hrms.hr.utils import share_doc_with_approver

from valence.valence.doc_events.leave_application import (
	_users_with_roles,
	count_working_leave_days,
	validate_leave_creation_window,
)
from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
)
from valence.valence.setup.od_wfh_workflow import WORKING_REQUEST_DAYS_FIELD

SUPER_HOD_STATE = STATE_PENDING_SUPER_HOD


def validate(doc, method=None):
	"""Attendance Request validate — OD/WFH business rules."""
	set_request_day_counts(doc)
	validate_mandatory_explanation(doc)
	validate_leave_creation_window(doc)
	validate_no_self_approval(doc)


def before_insert(doc, method=None):
	if not doc.get("workflow_state"):
		doc.workflow_state = "Draft"


def on_update(doc, method=None):
	approver = get_leave_approver(doc.employee)
	if approver:
		share_doc_with_approver(doc, approver)
	notify_super_hod_if_needed(doc)


def set_request_day_counts(doc):
	"""Calendar days + working days (for Super HOD routing)."""
	if not doc.from_date or not doc.to_date:
		doc.total_request_days = 0
		if doc.meta.has_field(WORKING_REQUEST_DAYS_FIELD):
			doc.set(WORKING_REQUEST_DAYS_FIELD, 0)
		return

	doc.total_request_days = date_diff(getdate(doc.to_date), getdate(doc.from_date)) + 1

	if not doc.meta.has_field(WORKING_REQUEST_DAYS_FIELD):
		return

	if not doc.employee:
		doc.set(WORKING_REQUEST_DAYS_FIELD, 0)
		return

	doc.set(
		WORKING_REQUEST_DAYS_FIELD,
		count_working_leave_days(doc.employee, doc.from_date, doc.to_date),
	)


def set_total_request_days(doc):
	"""Backward-compatible alias used by older tests / callers."""
	set_request_day_counts(doc)


def validate_mandatory_explanation(doc):
	"""Reason type is required (reason field); explanation text is mandatory for Valence."""
	if not (doc.explanation or "").strip():
		frappe.throw(
			_("Please provide an explanation for this OD/WFH request."),
			title=_("Explanation Required"),
		)


def validate_no_self_approval(doc):
	"""
	Block employees from approving/rejecting their own request
	(e.g. when the same user is Employee + Leave Approver).
	"""
	employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
	if not employee_user or frappe.session.user != employee_user:
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	old_state = before.get("workflow_state") or "Draft"
	new_state = doc.get("workflow_state") or "Draft"
	if old_state == new_state:
		return

	# Employee may Apply (Draft → Pending HOD) only
	if old_state == "Draft" and new_state == STATE_PENDING_HOD:
		return

	if new_state in (STATE_APPROVED, STATE_PENDING_SUPER_HOD, STATE_REJECTED):
		if old_state in (STATE_PENDING_HOD, STATE_PENDING_SUPER_HOD):
			frappe.throw(
				_("You cannot approve or reject your own OD/WFH request."),
				title=_("Self-Approval Not Allowed"),
			)


def notify_super_hod_if_needed(doc, method=None):
	"""When HOD routes a long OD/WFH to Super HOD, create ToDos for Super HOD / HR."""
	if doc.get("workflow_state") != SUPER_HOD_STATE:
		return

	before = doc.get_doc_before_save()
	if before and before.get("workflow_state") == SUPER_HOD_STATE:
		return

	_notify_super_hod_approvers(doc)


def _notify_super_hod_approvers(doc):
	users = _users_with_roles(["Super HOD", "HR Manager"])
	if not users:
		return

	working = doc.get(WORKING_REQUEST_DAYS_FIELD) or doc.get("total_request_days")
	subject = _("OD/WFH needs Super HOD approval: {0}").format(doc.name)
	message = _(
		"Attendance Request {0} for {1} ({2} working days from {3} to {4}) needs Super HOD approval."
	).format(
		doc.name,
		doc.employee_name or doc.employee,
		working,
		formatdate(doc.from_date),
		formatdate(doc.to_date),
	)

	for user in users:
		if user in ("Administrator", "Guest"):
			continue
		existing = frappe.db.exists(
			"ToDo",
			{
				"reference_type": "Attendance Request",
				"reference_name": doc.name,
				"allocated_to": user,
				"status": "Open",
			},
		)
		if existing:
			continue
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"description": message,
				"reference_type": "Attendance Request",
				"reference_name": doc.name,
				"assigned_by": frappe.session.user,
				"priority": "High",
			}
		).insert(ignore_permissions=True)

		if hasattr(frappe, "publish_realtime"):
			frappe.publish_realtime(
				event="notification",
				message={"type": "Alert", "message": subject},
				user=user,
			)
