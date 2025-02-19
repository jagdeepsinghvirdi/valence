import frappe

def before_submit(self,method):
	created_quality_inspections = []
	for row in self.items:
		if frappe.db.get_value("Item",row.item_code,"inspection_required_after_purchase") == 1:
			if self.company and not self.is_return and frappe.db.get_value("Item",row.item_code,"is_stock_item") == 1 and frappe.db.get_value("Item",row.item_code,"inspection_required_after_purchase") == 1:
				default_quality_inspection_warehouse=frappe.db.get_value("Company",self.company,"default_quality_inspection_warehouse")
				if default_quality_inspection_warehouse:
					row.warehouse = default_quality_inspection_warehouse
					
					row.quality_inspection = make_quality_inspection(self,row)
					created_quality_inspections.append(row.quality_inspection)
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
		# "item_name":item.item_name,
		"ref_item":item.name,
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