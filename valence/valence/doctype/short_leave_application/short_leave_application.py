# Copyright (c) 2026, finbyz tech and contributors
# For license information, please see license.txt

# NOTE: Business logic lives in valence.valence.doc_events.short_leave_application
# (hooked via doc_events in hooks.py), matching the pattern used for Leave
# Application / Attendance Request in this app. Keep this controller thin.

import frappe
from frappe.model.document import Document


class ShortLeaveApplication(Document):
	def before_insert(self):
		if not self.leave_approver:
			try:
				from hrms.hr.doctype.leave_application.leave_application import get_leave_approver

				approver = (get_leave_approver(self.employee) or "").strip()
				# Don't let a stale/incorrect Employee.leave_approver reference
				# (points at a User that doesn't exist here) crash the insert
				# with a LinkValidationError — leave it blank and let HR/the
				# employee notice and fix the Employee record instead.
				if approver and frappe.db.exists("User", approver):
					self.leave_approver = approver
				elif approver:
					frappe.log_error(
						title="Short Leave Application: invalid leave_approver",
						message=(
							f"Employee {self.employee}'s configured leave approver "
							f"'{approver}' is not a valid User — record created without "
							f"an approver set."
						),
					)
			except Exception:
				pass