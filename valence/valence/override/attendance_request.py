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
		# Transaction-level row lock on the employee
		frappe.db.sql(
			"SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE",
			(self.employee,),
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
			existing_doc = self.get_attendance_doc(date)
			if existing_doc:
				self._update_existing_attendance(existing_doc, status, date)
			else:
				raise

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
