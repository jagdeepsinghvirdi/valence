import frappe
from frappe import _

def on_submit(self, method):
	if self.work_order and self.stock_entry_type in [ "Manufacture","Material Transfer for Manufacture"]:
		user = self.owner
		roles = frappe.get_roles(user)
		if "Quality Manager" in roles:
			return "Quality Manager Can Submit Stock Entry"
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
		

def validate_manufacture_entry(self,method):
	created_quality_inspections = []
	if self.stock_entry_type == "Manufacture" and self.bom_no and self.work_order:
		if frappe.db.get_value("Work Order",self.work_order,"quality_inspection_required"):
			production_item=frappe.db.get_value("BOM",self.bom_no,"item")
			for each in self.items:
				if each.item_name == production_item or each.item_code == production_item or (each.quality_inspection_required_for_scrap and each.is_scrap_item):
					if not each.get('quality_inspection'):
						each.quality_inspection = make_quality_inspection(self,each)
						created_quality_inspections.append(each.quality_inspection)
					if self.company:
						default_quality_inspection_warehouse=frappe.db.get_value("Company",self.company,"default_quality_inspection_warehouse")
						if default_quality_inspection_warehouse and default_quality_inspection_warehouse != each.get('t_warehouse'):
							each.t_warehouse = default_quality_inspection_warehouse
	if created_quality_inspections:
		links = ''.join(
			f'<a href="/app/quality-inspection/{name}" target="_blank">{name}</a>,'
			for name in created_quality_inspections
		)
		frappe.msgprint(f"<b>Quality Inspections created:</b>{links}", title="Quality Inspections", indicator="green")


def make_quality_inspection(se_doc,item):
	
	doc=frappe.new_doc("Quality Inspection")
	doc.update({
		"inspection_type": "Incoming",
		"reference_type": se_doc.doctype,
		"reference_name": se_doc.name,
		"item_code": item.item_code,
		"description": item.description,
		"batch_no": item.batch_no,
		"lot_no": item.lot_no,
		"ar_no":item.ar_no,
		"sample_size": item.qty
	})
	doc.flags.ignore_mandatory=True
	doc.flags.ignore_permissions=True
	doc.flags.ignore_links = True
	doc.save()
	return doc.name

def stock_entry_quality_inspection_validation(self, method=None):
	if (
		self.bom_no
		and self.stock_entry_type == "Manufacture"
		and self.work_order
	):
		if frappe.db.get_value(
			"Work Order", self.work_order, "quality_inspection_required"
		):

			production_item = frappe.db.get_value(
				"BOM", self.bom_no, "item_name"
			)
			for each in self.items:
				if (
					each.item_name == production_item
					or each.item_code == production_item
				):

					if not each.get("quality_inspection"):
						frappe.throw(
							"Row {}: Quality Inspection is required for Finished Item".format(
								each.idx
							)
						)

def on_cancel_manufacture_entry(self, method):
	if self.stock_entry_type == "Manufacture":
		quality_inspections = [item.quality_inspection for item in self.items if item.quality_inspection]
		
		for qi_name in quality_inspections:
			qi_doc = frappe.get_doc("Quality Inspection", qi_name)
			if qi_doc.docstatus == 1:
				qi_doc.cancel()
			elif qi_doc.docstatus == 0:
				qi_doc.delete()

def validate(self,method):
	quality_inspection_required = frappe.db.get_value("Work Order",self.work_order,"quality_inspection_required")
	batch_no = frappe.db.get_value("Work Order",self.work_order,"batch_no")
	if self.stock_entry_type == "Manufacture" and self.work_order and quality_inspection_required and batch_no:
		for row in self.items:
			if row.is_finished_item and row.serial_and_batch_bundle:
				row.serial_and_batch_bundle = ""
				row.use_serial_batch_fields = 1
				row.batch_no = batch_no

