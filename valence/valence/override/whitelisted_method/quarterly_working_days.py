import frappe
from frappe import _
from valence.valence.tasks.leave_balance_update import get_working_days_for_quarter
from valence.valence.tasks.leave_balance_update import get_working_days_for_quarter, credit_leave_for_employee

@frappe.whitelist()
def get_working_days_preview(company, quarter_start_date, quarter_end_date):
	"""
	Auto-computed working days (from Attendance) for every active employee
	in the given company/quarter, for pre-filling the bulk-entry table.
	"""
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "company": company},
		fields=["name", "employee_name"],
	)

	preview = []
	for emp in employees:
		working_days = get_working_days_for_quarter(emp.name, quarter_start_date, quarter_end_date)
		preview.append({
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"working_days": working_days,
		})

	return preview


@frappe.whitelist()
def bulk_create_quarterly_working_days(entries, company, quarter_start_date, quarter_end_date, leave_type):
	if isinstance(entries, str):
		entries = frappe.parse_json(entries)
	if not entries:
		frappe.throw(_("Please provide at least one employee with working days."))
	if not leave_type:
		frappe.throw(_("Please select a Leave Type."))

	divisor = frappe.db.get_value("Leave Type", leave_type, "custom_working_days_per_leave")

	created = []
	updated = []
	for entry in entries:
		employee = entry.get("employee")
		working_days = entry.get("working_days")
		if not employee or working_days in (None, ""):
			continue
		existing_name = frappe.db.exists(
			"Quarterly Working Days",
			{
				"employee": employee,
				"leave_type": leave_type,
				"quarter_start_date": quarter_start_date,
				"quarter_end_date": quarter_end_date,
			},
		)
		if existing_name:
			frappe.db.set_value("Quarterly Working Days", existing_name, "working_days", working_days)
			updated.append(employee)
			if divisor:
				credit_leave_for_employee(
					employee=employee,
					company=company or frappe.db.get_value("Employee", employee, "company"),
					leave_type=leave_type,
					divisor=divisor,
					working_days=working_days,
					quarter_start=quarter_start_date,
					quarter_end=quarter_end_date,
				)
		else:
			frappe.get_doc({
				"doctype": "Quarterly Working Days",
				"employee": employee,
				"company": company,
				"leave_type": leave_type,
				"quarter_start_date": quarter_start_date,
				"quarter_end_date": quarter_end_date,
				"working_days": working_days,
				"is_manual_entry": 1,
			}).insert()  # on_update hook fires credit_leave_from_qwd automatically
			created.append(employee)

	return {
		"created_count": len(created),
		"updated_count": len(updated),
	}
