from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import format_date, get_link_to_form
from hrms.hr.doctype.attendance.attendance import DuplicateAttendanceError
from hrms.hr.doctype.attendance_request.attendance_request import AttendanceRequest as _AttendanceRequest


class AttendanceRequest(_AttendanceRequest):
	def get_attendance_doc(self, attendance_date: str):
		attendance_name = frappe.db.get_value(
			"Attendance",
			{
				"employee": self.employee,
				"attendance_date": attendance_date,
				"docstatus": ("!=", 2),
			},
			"name",
			for_update=True,
		)
		return frappe.get_doc("Attendance", attendance_name) if attendance_name else None

	def create_or_update_attendance(self, date: str):
		try:
			# Transaction-level row lock on the employee
			frappe.db.sql(
				"SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE",
				(self.employee,),
			)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Deadlock on Attendance Request for {0} on {1}").format(self.employee, date),
				message=frappe.get_traceback(),
			)
			frappe.throw(
				_("A database deadlock occurred while processing Attendance Request for employee {0}. The transaction has been rolled back. Please retry submitting the request.").format(
					frappe.bold(self.employee)
				),
				title=_("Database Deadlock"),
				exc=frappe.QueryDeadlockError,
			)
		except frappe.QueryTimeoutError:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Lock timeout on Attendance Request for {0} on {1}").format(self.employee, date),
				message=frappe.get_traceback(),
			)
			frappe.throw(
				_("Could not acquire lock for employee {0} due to concurrent attendance processing (lock wait timeout). The transaction has been rolled back. Please retry submitting the request.").format(
					frappe.bold(self.employee)
				),
				title=_("Lock Timeout"),
				exc=frappe.QueryTimeoutError,
			)

		doc = self.get_attendance_doc(date)
		status = self.get_attendance_status(date)

		if doc:
			self._update_existing_attendance(doc, status, date)
			return

		try:
			# submit a new attendance record
			new_doc = frappe.new_doc("Attendance")
			new_doc.employee = self.employee
			new_doc.attendance_date = date
			new_doc.shift = self.shift
			new_doc.company = self.company
			new_doc.attendance_request = self.name
			new_doc.status = status
			new_doc.half_day_status = "Absent" if status == "Half Day" else None
			new_doc.insert(ignore_permissions=True)
			new_doc.submit()
		except DuplicateAttendanceError:
			# Concurrent creation or race condition: re-fetch and update the existing record
			# The employee lock is STILL HELD and the transaction is valid.
			existing_doc = self.get_attendance_doc(date)
			if existing_doc:
				self._update_existing_attendance(existing_doc, status, date)
			else:
				raise
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Deadlock inserting Attendance Request for {0} on {1}").format(self.employee, date),
				message=frappe.get_traceback(),
			)
			frappe.throw(
				_("A database deadlock occurred while creating attendance for employee {0} on {1}. The transaction has been rolled back. Please retry submitting the request.").format(
					frappe.bold(self.employee), format_date(date)
				),
				title=_("Database Deadlock"),
				exc=frappe.QueryDeadlockError,
			)
		except frappe.QueryTimeoutError:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Lock timeout inserting Attendance Request for {0} on {1}").format(self.employee, date),
				message=frappe.get_traceback(),
			)
			frappe.throw(
				_("Could not acquire lock for employee {0} on {1} due to concurrent attendance processing (lock wait timeout). The transaction has been rolled back. Please retry submitting the request.").format(
					frappe.bold(self.employee), format_date(date)
				),
				title=_("Lock Timeout"),
				exc=frappe.QueryTimeoutError,
			)

	def _update_existing_attendance(self, doc, status, date):
		old_status = doc.status

		if old_status != status:
			doc.db_set({"status": status, "attendance_request": self.name})
			if status == "Half Day":
				doc.db_set("half_day_status", "Absent")
				text = _(
					"Changed the status from {0} to {1} and Status for Other Half to {2} via Attendance Request"
				).format(frappe.bold(old_status), frappe.bold(status), frappe.bold("Absent"))
			else:
				text = _("Changed the status from {0} to {1} via Attendance Request").format(
					frappe.bold(old_status), frappe.bold(status)
				)
			doc.add_comment(comment_type="Info", text=text)

			frappe.msgprint(
				_("Updated status from {0} to {1} for date {2} in the attendance record {3}").format(
					frappe.bold(old_status),
					frappe.bold(status),
					frappe.bold(format_date(date)),
					get_link_to_form("Attendance", doc.name),
				),
				title=_("Attendance Updated"),
			)
		else:
			if not doc.attendance_request:
				doc.db_set("attendance_request", self.name)
