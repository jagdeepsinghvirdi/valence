import frappe
from frappe import _
from valence.valence.tasks.leave_balance_update import get_working_days_for_quarter


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
	"""
	Create/update a Quarterly Working Days record for each employee in one go.
	entries: JSON list of {"employee": "...", "working_days": <number>}
	company, quarter_start_date, quarter_end_date, leave_type: shared across all entries
	"""
	if isinstance(entries, str):
		entries = frappe.parse_json(entries)
	if not entries:
		frappe.throw(_("Please provide at least one employee with working days."))
	if not leave_type:
		frappe.throw(_("Please select a Leave Type."))

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
			# Already have an entry for this employee/leave_type/quarter -
			# update it rather than creating a duplicate.
			frappe.db.set_value("Quarterly Working Days", existing_name, "working_days", working_days)
			updated.append(employee)
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
			}).insert()
			created.append(employee)

	return {
		"created_count": len(created),
		"updated_count": len(updated),
	}