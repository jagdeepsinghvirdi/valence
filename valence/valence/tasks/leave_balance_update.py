"""
For each employee and each Leave Type configured with
`custom_working_days_per_leave`, this:
  1. Tries to auto-calculate working days for the quarter from Attendance.
  2. If that yields no usable data, falls back to a manually entered
     Quarterly Working Days record (created by HR).
  3. Credits leave = working_days / custom_working_days_per_leave,
     logged as a Leave Ledger Entry, same pattern as core HRMS's
     allocate_earned_leaves so it shows correctly in standard reports.

divisors: EL/Privilege Leave = 20, SL = 43.57,
CL = 43.57. These live on Leave Type.custom_working_days_per_leave,not hardcoded, so HR can adjust them without a code change if the
real policy differs.
"""

import frappe
from frappe.utils import getdate, flt, add_months, today


def run_quarterly_leave_balance_update():
	"""Entry point — registered under scheduler_events -> cron (quarterly)."""
	quarter_start, quarter_end = get_current_quarter_range()

	leave_types = frappe.get_all(
		"Leave Type",
		filters=[["custom_working_days_per_leave", ">", 0]],
		fields=["name", "custom_working_days_per_leave"],
	)
	if not leave_types:
		return

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "company"],
	)

	for employee in employees:
		auto_working_days = get_working_days_for_quarter(employee.name, quarter_start, quarter_end)

		for leave_type in leave_types:
			working_days = auto_working_days
			if working_days is None:
				working_days = get_manual_working_days(
					employee.name, leave_type.name, quarter_start, quarter_end
				)
			if working_days is None:
				continue

			credit_leave_for_employee(
				employee=employee.name,
				company=employee.company,
				leave_type=leave_type.name,
				divisor=leave_type.custom_working_days_per_leave,
				working_days=working_days,
				quarter_start=quarter_start,
				quarter_end=quarter_end,
			)


def get_current_quarter_range():
	end = getdate(today())
	start = add_months(end, -3)
	return start, end


def get_working_days_for_quarter(employee, start_date, end_date):
	records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [start_date, end_date]],
			"docstatus": 1,
			"status": ["in", ["Present", "Half Day"]],
		},
		fields=["status"],
	)

	if not records:
		return None

	return sum(1 if r.status == "Present" else 0.5 for r in records)


def get_manual_working_days(employee, start_date, end_date):
	record = frappe.db.get_value(
		"Quarterly Working Days",
		{
			"employee": employee,
			"leave_type": leave_type,
			"quarter_start_date": start_date,
			"quarter_end_date": end_date,
		},
		"working_days",
	)
	return flt(record) if record else None


def credit_leave_for_employee(employee, company, leave_type, divisor, working_days, quarter_start, quarter_end):
	if not divisor:
		return

	earned_leaves = flt(working_days / divisor, 3)
	if earned_leaves <= 0:
		return

	allocation_name = frappe.db.get_value(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ["<=", quarter_end],
			"to_date": [">=", quarter_start],
		},
		"name",
	)
	if not allocation_name:
		return

	allocation = frappe.get_doc("Leave Allocation", allocation_name)
	precision = allocation.precision("total_leaves_allocated")
	earned_leaves = flt(earned_leaves, precision)

	allocation.db_set(
		"total_leaves_allocated",
		flt(allocation.total_leaves_allocated + earned_leaves, precision),
		update_modified=False,
	)

	frappe.get_doc(
		{
			"doctype": "Leave Ledger Entry",
			"employee": employee,
			"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"transaction_name": allocation.name,
			"company": company,
			"leaves": earned_leaves,
			"from_date": quarter_start,
			"to_date": quarter_end,
			"is_carry_forward": 0,
			"is_expired": 0,
		}
	).insert(ignore_permissions=True)

	allocation.add_comment(
		text=frappe._(
			"Credited {0} leave(s) for quarter ending {1}, based on {2} working days "
			"({3} working days per leave)."
		).format(earned_leaves, quarter_end, working_days, divisor)
	)