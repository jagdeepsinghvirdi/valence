import frappe
from frappe import _

def validate(self, method):
	if self.work_order and self.stock_entry_type in [ "Manufacture","Material Transfer for Manufacture"]:
		manufacturing_settings_doc = frappe.get_doc("Manufacturing Settings")
		item_groups_to_validate = [row.item_group for row in manufacturing_settings_doc.custom_validate_item_group]
		wo_doc = frappe.get_doc("Work Order", self.work_order)

		wo_item_qty = {}
		se_item_qty = {}
		wo_item_group_totals = {}
		se_item_group_totals = {}

		for row in wo_doc.required_items:
			if row.item_group in item_groups_to_validate:
				wo_item_qty[row.item_code] = row.required_qty
				wo_item_group_totals[row.item_group] = wo_item_group_totals.get(row.item_group, 0) + row.required_qty

		for data in self.items:
			if data.item_group in item_groups_to_validate:
				se_item_qty[data.item_code] = data.qty
				se_item_group_totals[data.item_group] = se_item_group_totals.get(data.item_group, 0) + data.qty

		mismatched_groups = []
		for group in item_groups_to_validate:
			wo_total = wo_item_group_totals.get(group, 0)
			se_total = se_item_group_totals.get(group, 0)
			if round(wo_total,2) != round(se_total,2):
				mismatched_groups.append((group, wo_total, se_total))

		changed_items = []
		for group, wo_total, se_total in mismatched_groups:
			for row in wo_doc.required_items:
				if row.item_group == group:
					se_qty = se_item_qty.get(row.item_code, 0)
					if round(row.required_qty,2) != round(se_qty,2):
						changed_items.append((row.item_code, se_qty, row.required_qty, group))

		group_summary = "<br>".join([
			_("Item Group '<b>{0}</b>' has Work Order Total({1}) and Stock Entry Total({2})").format(
				group, round(wo_total, 2), round(se_total, 2)
			)
			for group, wo_total, se_total in mismatched_groups
		])

		item_table = ""
		if changed_items:
			item_table = "<table class='table table-bordered'>"
			item_table += "<thead><tr><th>Item Code</th><th>Entered Qty</th><th>Allowed Qty</th><th>Item Group</th></tr></thead><tbody>"
			item_table += "".join([
				f"<tr><td>{item_code}</td><td>{round(entered_qty,2) or 0}</td><td>{round(allowed_qty,2)}</td><td>{item_group}</td></tr>"
				for item_code, entered_qty, allowed_qty, item_group in changed_items
			])
			item_table += "</tbody></table>"

		if mismatched_groups:
			frappe.throw(
				_("{0}<br><br>{1}")
				.format(group_summary, item_table)
			)
