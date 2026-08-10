"""
Leave Application override.

MariaDB 12+ treats bare `to_date` as TO_DATE() — HRMS raw SQL that selects/filters
`to_date` without backticks fails. Quote those identifiers here so leave + workflow
work on current MariaDB.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	LeaveApplication as HRMSLeaveApplication,
)


class LeaveApplication(HRMSLeaveApplication):
	def validate_leave_overlap(self):
		if not self.name:
			self.name = "New Leave Application"

		for d in frappe.db.sql(
			"""
			select
				name, leave_type, posting_date, from_date, `to_date`, total_leave_days, half_day, half_day_date
			from `tabLeave Application`
			where employee = %(employee)s and docstatus < 2 and status in ('Open', 'Approved')
			and `to_date` >= %(from_date)s and from_date <= %(to_date)s
			and name != %(name)s
			""",
			{
				"employee": self.employee,
				"from_date": self.from_date,
				"to_date": self.to_date,
				"name": self.name,
			},
			as_dict=1,
		):
			if (
				cint(self.half_day) == 1
				and cint(d.half_day) == 1
				and getdate(self.half_day_date) == getdate(d.half_day_date)
				and (
					flt(self.total_leave_days) == 0.5
					or getdate(self.from_date) == getdate(d.to_date)
					or getdate(self.to_date) == getdate(d.from_date)
				)
			):
				total_leaves_on_half_day = self.get_total_leaves_on_half_day()
				if total_leaves_on_half_day >= 1:
					self.throw_overlap_error(d)
			else:
				self.throw_overlap_error(d)


def get_leave_entries(employee, leave_type, from_date, to_date):
	"""MariaDB-12-safe version of HRMS get_leave_entries (backtick `to_date`)."""
	return frappe.db.sql(
		"""
		SELECT
			employee, leave_type, from_date, `to_date`, leaves, transaction_name, transaction_type, holiday_list,
			is_carry_forward, is_expired
		FROM `tabLeave Ledger Entry`
		WHERE employee=%(employee)s AND leave_type=%(leave_type)s
			AND docstatus=1
			AND (leaves<0
				OR is_expired=1)
			AND (from_date between %(from_date)s AND %(to_date)s
				OR `to_date` between %(from_date)s AND %(to_date)s
				OR (from_date < %(from_date)s AND `to_date` > %(to_date)s))
		""",
		{"from_date": from_date, "to_date": to_date, "employee": employee, "leave_type": leave_type},
		as_dict=1,
	)


@frappe.whitelist()
def get_leave_period(from_date, to_date, company):
	"""MariaDB-12-safe version of hrms.hr.utils.get_leave_period (backtick `to_date`)."""
	leave_period = frappe.db.sql(
		"""
		select name, from_date, `to_date`
		from `tabLeave Period`
		where company=%(company)s and is_active=1
			and (from_date between %(from_date)s and %(to_date)s
				or `to_date` between %(from_date)s and %(to_date)s
				or (from_date < %(from_date)s and `to_date` > %(to_date)s))
		""",
		{"from_date": from_date, "to_date": to_date, "company": company},
		as_dict=1,
	)

	if leave_period:
		return leave_period


def apply_mariadb_leave_sql_patches():
	"""Patch HRMS module-level helpers used outside the DocType class."""
	import hrms.hr.doctype.leave_application.leave_application as leave_mod
	import hrms.hr.utils as hr_utils

	leave_mod.get_leave_entries = get_leave_entries
	hr_utils.get_leave_period = get_leave_period
	# Rebind modules that already did `from hrms.hr.utils import get_leave_period`.
	leave_mod.get_leave_period = get_leave_period
	for module_path in (
		"hrms.hr.doctype.leave_allocation.leave_allocation",
		"hrms.hr.doctype.compensatory_leave_request.compensatory_leave_request",
	):
		module = __import__(module_path, fromlist=["get_leave_period"])
		if hasattr(module, "get_leave_period"):
			module.get_leave_period = get_leave_period
