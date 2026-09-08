import frappe
from frappe.utils import getdate, today
from hrms.hr.doctype.shift_assignment.shift_assignment import (
	ShiftAssignment as HRMSShiftAssignment,
)

CORRECTION_ROLES = ("HR Manager", "System Manager")


class ShiftAssignment(HRMSShiftAssignment):
	def on_cancel(self):
		if self.is_past_duplicate_correction():
			self.db_set("status", "Inactive", update_modified=False)
			return

		super().on_cancel()

	def is_past_duplicate_correction(self) -> bool:
		"""
		Allow cancelling a past duplicate assignment so bad data can be corrected.

		Deliberately narrow: an authorised role, a period that has already started,
		and at least one other submitted assignment covering the same dates.
		Creation-time duplicate prevention is untouched.
		"""
		if not self.start_date:
			return False

		roles = set(frappe.get_roles(frappe.session.user))
		if not roles.intersection(CORRECTION_ROLES):
			return False

		if getdate(self.start_date) >= getdate(today()):
			return False

		return bool(self.get_overlapping_submitted_assignments())

	def get_overlapping_submitted_assignments(self):
		end_date = self.end_date or self.start_date

		return frappe.get_all(
			"Shift Assignment",
			filters={
				"name": ["!=", self.name],
				"employee": self.employee,
				"docstatus": 1,
				"start_date": ["<=", end_date],
			},
			or_filters=[
				["end_date", ">=", self.start_date],
				["end_date", "is", "not set"],
			],
			pluck="name",
		)
