import frappe
from frappe import _
from frappe.utils import add_days, getdate, today
from hrms.hr.doctype.shift_assignment.shift_assignment import (
	ShiftAssignment as HRMSShiftAssignment,
)

CORRECTION_ROLES = ("HR Manager", "System Manager")


class ShiftAssignment(HRMSShiftAssignment):
	def validate_overlapping_shifts(self):
		# Left and Inactive assignments do not represent working shift timing overlaps
		if self.status in ("Inactive", "Left"):
			return

		super().validate_overlapping_shifts()

	def validate(self):
		self.reset_status_on_amend()
		self.apply_left_status()
		super().validate()

	def apply_left_status(self):
		if self.status == "Left":
			self.shift_type = None
			self.shift_location = None
			if self.meta.has_field("custom_off_day"):
				self.custom_off_day = None
			return

		if not self.shift_type:
			frappe.throw(_("Shift Type is required unless the assignment status is Left."))

	def reset_status_on_amend(self):
		# Amend copies the cancelled document's Inactive status. Restore Active for a
		# new amended draft unless its date range has genuinely expired.
		if not (self.is_new() and self.amended_from):
			return
		if self.status != "Inactive":
			return
		if self.end_date and getdate(self.end_date) < getdate(add_days(today(), -1)):
			return
		self.status = "Active"

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
