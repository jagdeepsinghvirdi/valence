import frappe
from frappe import _
from valence.valence.monkey_patch.serial_batch_bundle import create_batch

# import frappe.printing

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
	created_lrf_docs = []
	
	if self.stock_entry_type == "Manufacture" and self.bom_no and self.work_order:		
		
		if frappe.db.get_value("Work Order",self.work_order,"quality_inspection_required"):	
					
			production_item=frappe.db.get_value("BOM",self.bom_no,"item")	

			for each in self.items:	
						
				if each.item_name == production_item or each.item_code == production_item or (each.quality_inspection_required_for_scrap and each.is_scrap_item):
					
					if not each.get('quality_inspection'):	
												
						each.quality_inspection = make_quality_inspection(self,each)
						created_quality_inspections.append(each.quality_inspection)
					if self.company:
						# lrf_name = frappe.db.get_value("Quality Inspection",each.quality_inspection,'custom_lrf_reference_name')
						if each.is_finished_item:
							default_quality_analysis_warehouse=frappe.db.get_value("Company",self.company,"custom_default_quality_analysis_warehouse")
							if default_quality_analysis_warehouse and default_quality_analysis_warehouse != each.get('t_warehouse'):
								each.t_warehouse = default_quality_analysis_warehouse
						else:
							default_quality_inspection_warehouse=frappe.db.get_value("Company",self.company,"default_quality_inspection_warehouse")
							if default_quality_inspection_warehouse and default_quality_inspection_warehouse != each.get('t_warehouse'):
								each.t_warehouse = default_quality_inspection_warehouse
	elif frappe.db.get_value("Stock Entry Type", self.stock_entry_type, "purpose") == "Repack":
		# production_item=frappe.db.get_value("BOM",self.bom_no,"item")
		for each in self.items:
			if self.custom_quality_inspection_for_bland:
				if each.is_finished_item and each.t_warehouse:
					if not each.get('quality_inspection'):
						each.quality_inspection = make_quality_inspection(self,each)
						created_quality_inspections.append(each.quality_inspection)
					if self.company:
						default_quality_inspection_warehouse=frappe.db.get_value("Company",self.company,"default_quality_inspection_warehouse")
						if default_quality_inspection_warehouse and default_quality_inspection_warehouse != each.get('t_warehouse'):
							each.t_warehouse = default_quality_inspection_warehouse
			if self.custom_lrf_required:
				if each.is_finished_item and each.t_warehouse:
					lrf_doc  = make_lrf_entry(self,each)
					created_lrf_docs.append(lrf_doc)
	
	if created_quality_inspections:
		links = ', '.join(
			f'<a href="/app/quality-inspection/{name}" target="_blank">{name}</a>'
			for name in created_quality_inspections if name
		)
		if links:
			frappe.msgprint(
				f"<b>Quality Inspections created:</b>{links}",
				indicator="green"
			)
   
	# Show LRF links
	if created_lrf_docs:
		links = ', '.join(
			f'<a href="/app/label-requisition-form/{name}" target="_blank">{name}</a>'
			for name in created_lrf_docs if name
		)
		if links:
			frappe.msgprint(
				f"<b>LRF Documents created:</b> {links}",
				indicator="blue"
			)
	
	# if created_quality_inspections:
	# 	links = ''.join(
	# 		f'<a href="/app/quality-inspection/{name}" target="_blank">{name}</a>,'
	# 		for name in created_quality_inspections
	# 	)
	# 	frappe.msgprint(f"<b>Quality Inspections created:</b>{links}", title="Quality Inspections", indicator="green")


def make_quality_inspection(se_doc,item):
	
	# production_item, get_batch_no = None, None
    
	# if se_doc.work_order:
	# 	production_item = frappe.db.get_value("Work Order",se_doc.work_order,"production_item")
	# 	get_batch_no = frappe.db.get_value("Work Order",se_doc.work_order,"batch_no")
	# 	is_final_stage = frappe.db.get_value("Item",production_item,"custom_is_final_stage")
	# 	item_stage = frappe.db.get_value("Item",production_item,"custom_item_stage")
	# else:
	# 	is_final_stage = frappe.db.get_value("Item",item.item_code,"custom_is_final_stage")
	# 	item_stage = frappe.db.get_value("Item",item.item_code,"custom_item_stage")

	
	qi_doc=frappe.new_doc("Quality Inspection")
	wo_batch = frappe.get_all("Batch",filters={"reference_doctype":"Stock Entry","reference_name":se_doc.name,"item":item.item_code})
	if item.batch_no:
		batch = item.batch_no
	elif wo_batch:
		batch = wo_batch[0].name
	qi_doc.update({
		"inspection_type": "Incoming",
		"reference_type": se_doc.doctype,
		"reference_name": se_doc.name,
		# "custom_entry_type": "LRF" if lrf_reference else "RFA",
		# 'custom_lrf_reference_name': lrf_reference,
		"item_code": item.item_code,
		"sample_size": item.qty,
		"description": item.description,
		"batch_no": batch,
		"lot_no": item.lot_no,
		"ar_no":item.ar_no,
	})

	qi_doc.flags.ignore_mandatory=True
	qi_doc.flags.ignore_permissions=True
	qi_doc.flags.ignore_links = True
	qi_doc.save()
	return qi_doc.name

	# if (is_final_stage or se_doc.custom_is_item_intermediate_stage) and int(item_stage)>0:
	# 	if not item.quality_inspection_required_for_scrap and not item.is_scrap_item:
			
	# 		# Create LRF Entry
	# 		lrf_doc = frappe.new_doc("Label Requisition Form")
	# 		lrf_doc.update({
	# 			"production_item": production_item if production_item else item.item_code,            
	# 			"grade":'NA' if se_doc.custom_is_item_intermediate_stage else '',
	# 			"production_b_no": get_batch_no,
	# 			"stock_entry_reference_name": se_doc.name,
	# 			"inspected_by": se_doc.modified_by,
	# 		})
	# 		lrf_doc.flags.ignore_mandatory = True
	# 		lrf_doc.flags.ignore_permissions = True
	# 		lrf_doc.insert()
	# 		# Show link in message
	# 		link = f'<a href="/app/label-requisition-form/{lrf_doc.name}" target="_blank">{lrf_doc.name}</a>'
	# 		frappe.msgprint(f"<b>LRF created:</b> {link}", title="Label Requisition Form", indicator="green")

	# 		return create_quality_inspection(lrf_doc.name)
	# 	else:
	# 		return create_quality_inspection()
	# else:
	# 	return create_quality_inspection()


def make_lrf_entry(se_doc,item):
	production_item, get_batch_no = None, None
 
	if se_doc.work_order:
		production_item = frappe.db.get_value("Work Order",se_doc.work_order,"production_item")
		get_batch_no = frappe.db.get_value("Work Order",se_doc.work_order,"batch_no")
		is_final_stage = frappe.db.get_value("Item",production_item,"custom_is_final_stage")
		item_stage = frappe.db.get_value("Item",production_item,"custom_item_stage")
	else:
		is_final_stage = frappe.db.get_value("Item",item.item_code,"custom_is_final_stage")
		item_stage = frappe.db.get_value("Item",item.item_code,"custom_item_stage")
  
	if (is_final_stage or se_doc.custom_is_item_intermediate_stage) and int(item_stage)>0:
		if not item.quality_inspection_required_for_scrap and not item.is_scrap_item:
			# Create LRF Entry
			lrf_doc = frappe.new_doc("Label Requisition Form")
			wo_batch = frappe.get_all("Batch",filters={"reference_doctype":"Stock Entry","reference_name":se_doc.name,"item":item.item_code})
			if item.batch_no:
				batch = item.batch_no
			elif wo_batch:
				batch = wo_batch[0].name
			lrf_doc.update({
				"production_item": item.item_code,            
				"grade":'NA' if se_doc.custom_is_item_intermediate_stage else '',
				"production_b_no": batch,
				# "stock_entry_reference_name": se_doc.name,
				"inspected_by": se_doc.modified_by,
			})
			lrf_doc.flags.ignore_mandatory=True
			lrf_doc.flags.ignore_permissions=True
			lrf_doc.flags.ignore_links = True
			lrf_doc.save()
   
			se_doc.custom_lrf_reference = lrf_doc.name
			se_doc.save()
			return lrf_doc.name       

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
					is_final_stage = frappe.db.get_value("Item",each.item_code,"custom_is_final_stage")
					
					if is_final_stage or self.custom_is_item_intermediate_stage:
						return
					else:
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