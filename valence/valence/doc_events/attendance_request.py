"""
#7 OD/WFH rules on standard Attendance Request (Work From Home / On Duty).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, getdate

from hrms.hr.doctype.leave_application.leave_application import get_leave_approver
from hrms.hr.utils import share_doc_with_approver

from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
)


def validate(doc, method=None):
	"""Attendance Request validate — OD/WFH business rules."""
	set_total_request_days(doc)
	validate_mandatory_explanation(doc)
	validate_no_self_approval(doc)


def before_insert(doc, method=None):
	if not doc.get("workflow_state"):
		doc.workflow_state = "Draft"


def on_update(doc, method=None):
	approver = get_leave_approver(doc.employee)
	if approver:
		share_doc_with_approver(doc, approver)


def set_total_request_days(doc):
	if doc.from_date and doc.to_date:
		doc.total_request_days = date_diff(getdate(doc.to_date), getdate(doc.from_date)) + 1


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
