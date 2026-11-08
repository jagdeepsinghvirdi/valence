"""Remove custom Table fields that point to DocTypes which no longer exist.

Leftovers of uninstalled apps (e.g. Lending's Company fields `irac_provisioning_configuration` and
`loan_classification_ranges`) come back on migrate and make documents such as Company fail to load with
"Unknown column 'parent'". Runs after every migrate.
"""

import frappe


def remove_orphan_table_custom_fields():
	removed = []
	for cf in frappe.get_all(
		"Custom Field",
		filters={"fieldtype": ["in", ["Table", "Table MultiSelect"]]},
		fields=["name", "dt", "options"],
	):
		if cf.options and not frappe.db.exists("DocType", cf.options):
			frappe.delete_doc("Custom Field", cf.name, ignore_permissions=True, force=True)
			removed.append(cf.name)
	if removed:
		frappe.db.commit()
		frappe.clear_cache()
		print("valence: removed orphan custom table fields:", ", ".join(removed))
	return removed
