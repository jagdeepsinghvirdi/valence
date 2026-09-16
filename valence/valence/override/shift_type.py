import frappe
from frappe import _
from frappe.utils import cint
from hrms.hr.doctype.attendance.attendance import mark_attendance
from hrms.hr.doctype.shift_type.shift_type import ShiftType as _ShiftType
from hrms.utils import get_date_range


class ShiftType(_ShiftType):

	@frappe.whitelist()
	def process_auto_attendance(self, is_manually_triggered=False):
		incomplete_setup = self.get_incomplete_setup_message()
		if incomplete_setup:
			return incomplete_setup

		return super().process_auto_attendance(is_manually_triggered=is_manually_triggered)

	def get_incomplete_setup_message(self):
		if not cint(self.enable_auto_attendance):
			return _("Auto Attendance is not enabled for {0}, so no attendance was processed.").format(
				self.name
			)
		if not self.process_attendance_after:
			return _("Please set Process Attendance After on {0} before marking attendance.").format(
				self.name
			)
		if not self.last_sync_of_checkin:
			return _("Please set Last Sync of Checkin on {0} before marking attendance.").format(self.name)

		return None

	def get_dates_for_attendance(self, employee: str) -> list[str]:
		start_date, end_date = self.get_start_and_end_dates(employee)

		# No shift assignment found, no need to process absent attendance records
		if start_date is None:
			return []

		date_range = get_date_range(start_date, end_date)

		# Skip dates with existing attendance
		marked_attendance_dates = self.get_marked_attendance_dates_between(employee, start_date, end_date)
		return sorted(set(date_range) - set(marked_attendance_dates))

	def should_mark_attendance(self, employee: str, attendance_date: str) -> bool:
		return True

	def mark_absent_for_dates_with_no_attendance(self, employee: str):
		from valence.api import get_applicable_shift, get_day_type

		for date in self.get_dates_for_attendance(employee):
			if get_applicable_shift(employee, date) != self.name:
				continue

			status = get_day_type(employee, date) or "Absent"
			attendance = mark_attendance(employee, date, status, self.name)

			if not attendance or status != "Absent":
				continue

			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Attendance",
					"reference_name": attendance,
					"content": frappe._("Employee was marked Absent due to missing Employee Checkins."),
				}
			).insert(ignore_permissions=True)
