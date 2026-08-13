import frappe
from frappe import _


@frappe.whitelist()
def bulk_create_quarterly_working_days(entries, company, quarter_start_date, quarter_end_date):
	"""
	Create/update a Quarterly Working Days record for each employee in one go.

	entries: JSON list of {"employee": "...", "working_days": <number>}
	company, quarter_start_date, quarter_end_date: shared across all entries
	"""
	if isinstance(entries, str):
		entries = frappe.parse_json(entries)

	if not entries:
		frappe.throw(_("Please provide at least one employee with working days."))

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
				"quarter_start_date": quarter_start_date,
				"quarter_end_date": quarter_end_date,
			},
		)

		if existing_name:
			# Already have an entry for this employee/quarter - update it
			# rather than creating a duplicate.
			frappe.db.set_value("Quarterly Working Days", existing_name, "working_days", working_days)
			updated.append(employee)
		else:
			frappe.get_doc({
				"doctype": "Quarterly Working Days",
				"employee": employee,
				"company": company,
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