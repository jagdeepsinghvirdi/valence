import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

HOLD_OPTIONS = ("Left", "Resignation", "Leave Not Approved")


class AttendanceMonthRemark(Document):
	def validate(self):
		self.validate_period()
		self.validate_hold()

	def validate_period(self):
		month = cint(self.month)
		if month < 1 or month > 12:
			frappe.throw(_("Month must be between 1 and 12."))

		year = cint(self.year)
		if year < 1900 or year > 9999:
			frappe.throw(_("Please set a valid Year."))

		self.month = month
		self.year = year

	def validate_hold(self):
		if self.hold and self.hold not in HOLD_OPTIONS:
			frappe.throw(
				_("Hold must be one of: {0}").format(", ".join(HOLD_OPTIONS))
			)
