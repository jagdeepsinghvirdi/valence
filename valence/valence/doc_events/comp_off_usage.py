"""Comp Off Usage and Validation.

Notes:
- Comp Off balance must always come from HRMS's get_leave_balance_on() — never a custom calculation.
- Comp Off earning is automatic (from qualifying double-shift work), so employees cannot apply for unearned Comp Off — this must be blocked.
"""

import frappe
from frappe import _
from frappe.utils import flt

from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on


def get_comp_off_leave_type():
	"""Get configured Comp Off Leave Type from Attendance Settings."""
	return frappe.db.get_single_value("Attendance Settings", "comp_off_leave_type")


def validate_comp_off_application(doc, method=None):
	"""Validate Comp Off application.

	Ensures that employees cannot apply for unearned Comp Off by verifying
	that the requested Comp Off days do not exceed the available balance
	obtained from HRMS's get_leave_balance_on().
	"""
	from frappe.utils import add_days, cint, getdate
	from valence.api import get_day_type

	comp_off_leave_type = get_comp_off_leave_type()
	if not comp_off_leave_type:
		frappe.throw(_("Comp Off Leave Type is not configured in Attendance Settings"))

	if doc.leave_type != comp_off_leave_type:
		return

	if not doc.employee or not doc.from_date or not doc.to_date:
		return

	start = getdate(doc.from_date)
	end = getdate(doc.to_date)
	if end < start:
		return

	is_half_day = cint(doc.half_day) == 1
	half_day_date = getdate(doc.half_day_date) if (is_half_day and doc.half_day_date) else None

	eligible_requested_amount = 0.0
	current = start
	while current <= end:
		day_type = get_day_type(doc.employee, current)
		if not day_type:
			if is_half_day and (current == half_day_date or (not half_day_date and start == end)):
				eligible_requested_amount += 0.5
			else:
				eligible_requested_amount += 1.0
		current = getdate(add_days(current, 1))

	eligible_requested_amount = flt(eligible_requested_amount, 1)

	if flt(doc.total_leave_days) != eligible_requested_amount:
		doc.total_leave_days = eligible_requested_amount

	available_balance = flt(get_comp_off_balance(doc.employee, doc.from_date))

	if eligible_requested_amount > available_balance or available_balance < 0:
		frappe.throw(
			_(
				"Insufficient Comp Off balance for Employee {0}. Requested: {1} day(s), Available balance: {2} day(s). "
				"Comp Off cannot result in a negative balance."
			).format(doc.employee, eligible_requested_amount, available_balance),
			title=_("Insufficient Comp Off Balance"),
		)


@frappe.whitelist()
def get_comp_off_balance(employee, on_date=None):
	"""Retrieve the Comp Off leave balance for an employee on a given date.

	Balance must always come from HRMS's get_leave_balance_on() — never a custom calculation.
	"""
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Employee {0} does not exist.").format(employee))

	leave_type = get_comp_off_leave_type()
	if not leave_type:
		frappe.throw(_("Comp Off Leave Type is not configured in Attendance Settings"))

	if not on_date:
		on_date = frappe.utils.nowdate()

	return get_leave_balance_on(employee, leave_type, on_date)


def get_comp_off_statement(employee, from_date, to_date):
	"""Retrieve a statement/ledger of Comp Off allocations and consumption for an employee.

	Returns details of Comp Off earned and taken between from_date and to_date.
	"""
	leave_type = get_comp_off_leave_type()

	entries = frappe.get_all(
		"Leave Ledger Entry",
		filters={
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ["<=", to_date],
			"to_date": [">=", from_date],
		},
		fields=[
			"name",
			"employee",
			"employee_name",
			"leave_type",
			"from_date",
			"to_date",
			"leaves",
			"transaction_type",
			"transaction_name",
			"is_carry_forward",
			"is_expired",
		],
		order_by="from_date asc, creation asc",
	)

	statement = []
	for entry in entries:
		row = frappe._dict(entry)
		leaves = flt(row.get("leaves"))
		row.earned = leaves if leaves > 0 else 0.0
		row.consumed = abs(leaves) if leaves < 0 else 0.0
		statement.append(row)

	return statement
