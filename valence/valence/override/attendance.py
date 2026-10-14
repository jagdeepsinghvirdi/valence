import frappe
from frappe import _
from frappe.utils import format_date, get_link_to_form
from hrms.hr.doctype.attendance.attendance import (
	Attendance as _Attendance,
	DuplicateAttendanceError,
	validate_active_employee,
)


def lock_employee(employee: str | None):
	if not employee:
		return
	try:
		frappe.db.sql(
			"SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE",
			(employee,),
		)
	except frappe.QueryDeadlockError:
		frappe.db.rollback()
		frappe.log_error(
			title=_("Deadlock detected for Employee {0}").format(employee),
			message=frappe.get_traceback(),
		)
		frappe.throw(
			_("A database deadlock occurred while locking employee {0}. The transaction has been rolled back. Please retry.").format(
				frappe.bold(employee)
			),
			title=_("Database Deadlock"),
			exc=frappe.QueryDeadlockError,
		)
	except frappe.QueryTimeoutError:
		frappe.db.rollback()
		frappe.log_error(
			title=_("Lock wait timeout for Employee {0}").format(employee),
			message=frappe.get_traceback(),
		)
		frappe.throw(
			_("Could not acquire lock for employee {0} due to concurrent attendance processing (lock wait timeout). The transaction has been rolled back. Please retry.").format(
				frappe.bold(employee)
			),
			title=_("Lock Timeout"),
			exc=frappe.QueryTimeoutError,
		)


class Attendance(_Attendance):
	def before_insert(self):
		if self.half_day_status == "":
			self.half_day_status = None

		# Universal duplicate guard: locks employee and validates duplicate even if flags.ignore_validate = True
		lock_employee(self.employee)
		self.validate_duplicate_record()

	def on_cancel(self):
		self.ignore_linked_doctypes = ["Leave Ledger Entry"]
		super().on_cancel()

	def validate(self):
		from erpnext.controllers.status_updater import validate_status

		validate_status(self.status, ["Present", "Absent", "On Leave", "Half Day", "Work From Home","Mispunch","No punch","Present With Short Leave","Holiday","On Duty", "Weekly Off"])
		validate_active_employee(self.employee)
		self.validate_attendance_date()
		self.validate_duplicate_record()
		self.validate_overlapping_shift_attendance()
		self.validate_employee_status()
		self.check_leave_record()

	def validate_duplicate_record(self):
		lock_employee(self.employee)
		duplicate = self.get_duplicate_attendance_record()

		if duplicate:
			frappe.throw(
				_("Attendance for employee {0} is already marked for the date {1}: {2}").format(
					frappe.bold(self.employee),
					frappe.bold(format_date(self.attendance_date)),
					get_link_to_form("Attendance", duplicate),
				),
				title=_("Duplicate Attendance"),
				exc=DuplicateAttendanceError,
			)

	def get_duplicate_attendance_record(self) -> str | None:
		AttendanceDoc = frappe.qb.DocType("Attendance")
		query = (
			frappe.qb.from_(AttendanceDoc)
			.select(AttendanceDoc.name)
			.where(
				(AttendanceDoc.employee == self.employee)
				& (AttendanceDoc.docstatus < 2)
				& (AttendanceDoc.attendance_date == self.attendance_date)
				& (AttendanceDoc.name != (self.name or ""))
			)
			.for_update()
		)

		duplicate = query.run(pluck=True)
		return duplicate[0] if duplicate else None
