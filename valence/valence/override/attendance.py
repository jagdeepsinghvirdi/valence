import frappe
from frappe import _
from hrms.hr.doctype.attendance.attendance import Attendance as _Attendance, validate_active_employee

class Attendance(_Attendance):
	def before_insert(self):
		if self.half_day_status == "":
			self.half_day_status = None

	def validate(self):
		from erpnext.controllers.status_updater import validate_status

		validate_status(self.status, ["Present", "Absent", "On Leave", "Half Day", "Work From Home","In Mispunch","Out Mispunch","No punch","Present With Short Leave","Holiday","Weekly Off"])
		validate_active_employee(self.employee)
		self.validate_attendance_date()
		self.validate_duplicate_record()
		self.validate_overlapping_shift_attendance()
		self.validate_employee_status()
		self.check_leave_record()
