import frappe
from frappe.utils import add_months, get_last_day, nowdate,add_days,formatdate,get_url_to_form
from frappe.utils import flt, cint, getdate

def on_submit(self, method):
	
	if self.reference_type:
		ref_doctype = frappe.get_doc(self.reference_type, self.reference_name)
		for row in ref_doctype.items:
			if self.item_code == row.item_code:
				row.db_set("lot_no",self.lot_no)
				row.db_set("ar_no",self.ar_no)
		ref_doctype.reload()

	if self.batch_no:
		batch_no = frappe.get_doc("Batch",self.batch_no)
		batch_no.db_set("ar_no",self.ar_no)
		if self.retest_date:
			batch_no.db_set("retest_date",self.retest_date)
		if self.expiry_date:
			batch_no.db_set("expiry_date",self.expiry_date)
		if self.manufacturing_date:
			batch_no.db_set("manufacturing_date",self.manufacturing_date)

def before_submit(self,method):
	if not self.ar_no:
		frappe.throw("AR No. is Mandatory Field")

def before_save(self, method):
	
	if self.retest_month:
		today = nowdate()  
		new_date = add_months(today, int(self.retest_month))
		retest_date = get_last_day(new_date)  
		self.retest_date = retest_date

	# if self.custom_lrf_reference_name:
	# 	lrf_doc = frappe.get_doc("Label Requisition Form", self.custom_lrf_reference_name)
	# 	lrf_batch_size = lrf_doc.get("batch_size_kgs") 
	# 	lrf_doc.db_set("released_qty_kgs",lrf_batch_size - self.sample_size)

	# 	# Initialize list to collect selected grades
	# 	grades = []

	# 	if self.custom_ih:
	# 		grades.append("IH")

	# 	if self.custom_ip:
	# 		grades.append("IP")

	# 	if self.custom_usp:
	# 		grades.append("USP")

	# 	if self.custom_epbp:
	# 		grades.append("EP/BP")

	# 	# Join and set grade in LRF doc
	# 	if grades:
	# 		lrf_doc.db_set("grade", ", ".join(grades))

	batch_doc = frappe.get_doc("Batch",self.batch_no)
	if self.custom_ih:
		batch_doc.db_set("ih",1)
	if self.custom_ar_no_ih:
		batch_doc.db_set("ar_no_ih",self.custom_ar_no_ih)
	if self.custom_ip:
		batch_doc.db_set("ip",1)
	if self.custom_ar_no_ip:
		batch_doc.db_set("ar_no_ip",self.custom_ar_no_ip)
	if self.custom_usp:
		batch_doc.db_set("usp",1)
	if self.custom_ar_no_usp:
		batch_doc.db_set("ar_no_usp",self.custom_ar_no_usp)
	if self.custom_epbp:
		batch_doc.db_set("epbp",1)
	if self.custom_ar_no_epbp:
		batch_doc.db_set("ar_no_epbp",self.custom_ar_no_epbp)

def create_qc_for_retest_batches():
	tomorrow_date = add_days(nowdate(), 1)

	formatted_tomorrow_date = formatdate(tomorrow_date, "dd-mm-yyyy")
	batches = frappe.db.get_all('Batch', filters={'retest_date': "26-01-2025"}, fields=["*"])


	for batch in batches:
		qc_doc = frappe.get_doc({
			'doctype': 'Quality Inspection',
			'item_code': batch['item'],
			'item_name':batch['item_name'],
			'batch_no': batch['name'],
			'reference_type':batch['reference_doctype'],
			'reference_name':batch['reference_name'],
			'lot_no':batch['lot_no'],
			'ar_no':batch['ar_no'],
			'sample_size':0,
			'manufacturing_date':batch['manufacturing_date'],
			'inspection_type': 'Incoming',
			'status': 'Accepted',
			'inspected_by':'Administrator' , 
			'retest_quality_inspection':1
		})
		qc_doc.insert(ignore_permissions=True)
		frappe.db.commit()

def transfer_material_from_quality_inspection_warehouse(self,method):
	if self.reference_type and self.reference_name and self.reference_type in ["Stock Entry","Purchase Receipt"]:
		doc = frappe.get_doc(self.reference_type, self.reference_name)
		if self.reference_type == "Stock Entry":
			if doc.stock_entry_type == "Manufacture":
				material_transfer_stock_entry(self, doc)
			elif doc.stock_entry_type == "Repack":
				repack_stock_entry_type(self, doc)
		elif self.reference_type == "Purchase Receipt":
			material_transfer(self,doc)


def material_transfer(self, ref_doc):
	if self.reference_type == "Purchase Receipt":
		se_doc = frappe.get_doc("Purchase Receipt",self.reference_name)
	default_quality_inspection_warehouse, rejection_warehouse = frappe.db.get_value(
		"Company", ref_doc.company, ['default_quality_inspection_warehouse', 'rejection_warehouse'])
	
	se = frappe.new_doc("Stock Entry")
	se.fg_completed_qty = 0
	se.posting_date = self.report_date
	se.purpose = "Material Transfer"
	se.stock_entry_type = "Material Transfer"
	se.company = ref_doc.company
	if self.reference_type == "Purchase Receipt":	
		se.update({
			"to_warehouse": ref_doc.set_warehouse if self.workflow_state == "Approved" else rejection_warehouse,
			"from_warehouse": default_quality_inspection_warehouse
			})
	existing_items = set()
	for row in ref_doc.items:
		if self.reference_type == "Purchase Receipt" and row.item_code == self.item_code:
			if row.name == self.ref_item:
				existing_items.add(row.item_code)
				se.append("items", {
					'item_code': row.item_code,
					'quality_inspection': self.name,
					's_warehouse': default_quality_inspection_warehouse,
					't_warehouse': self.warehouse,
					'qty': flt(row.stock_qty) - flt(self.sample_size),
					'batch_no': row.batch_no,
					'basic_rate': row.rate,  # Replace basic_rate with rate for Purchase Receipt
					'lot_no': row.lot_no,	
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})
	se.save()	
	se.submit()
	url = get_url_to_form("Stock Entry", se.name)
	self.db_set("stock_entry",se.name)
	frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Material Transfer".format(
		url=url, doc=frappe.bold(se.name)))


def material_transfer_stock_entry(self, ref_doc):	
	
	if self.reference_type == "Stock Entry":
		se_doc = frappe.get_doc("Stock Entry",self.reference_name)
	default_quality_inspection_warehouse, default_quality_analysis_warehouse, rejection_warehouse = frappe.db.get_value(
		"Company", ref_doc.company, ['default_quality_inspection_warehouse', 'custom_default_quality_analysis_warehouse','rejection_warehouse'])
	
	# if self.custom_lrf_reference_name:
		# First Manufacture Entry For Quality Analysis to Quality Inspection Warehouse
		# se1 = frappe.new_doc("Stock Entry")
		# se1.fg_completed_qty = 0
		# se1.posting_date = self.report_date
		# se1.purpose = "Material Transfer"
		# se1.stock_entry_type = "Material Transfer"
		# se1.company = ref_doc.company
		# se1.update({
		# 	"to_warehouse": default_quality_inspection_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
		# 	"from_warehouse": default_quality_analysis_warehouse
		# })
		# for row in ref_doc.items:
		# 	if self.reference_type == "Stock Entry":
		# 		if row.t_warehouse and row.is_finished_item and row.item_code == self.item_code:
		# 			if self.custom_lrf_reference_name:
		# 				ref_lrf_sample_size = self.sample_size or frappe.db.get_value("Label Requisition Form",self.custom_lrf_reference_name,'custom_sample_size')
		# 				se1.append("items", {
		# 					'item_code': row.item_code,
		# 					'quality_inspection': self.name,
		# 					's_warehouse': default_quality_analysis_warehouse,
		# 					't_warehouse': default_quality_inspection_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
		# 					'qty': flt(ref_lrf_sample_size),
		# 					'batch_no': row.batch_no,
		# 					'basic_rate': row.basic_rate,  # Stock Entry uses basic_rate
		# 					'lot_no': row.lot_no,
		# 					'ar_no': row.ar_no,
		# 					'use_serial_batch_fields': 1
		# 				})
		# se1.custom_quality_inspection_reference_ = self.name
		# se1.save()
		# se1.submit()
		# url = get_url_to_form("Stock Entry", se1.name)

		# frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Material Transfer".format(
		# 	url=url, doc=frappe.bold(se1.name)))
		
		# # Second  Manufacture Entry For Quality Inspection Warehouse to Target Warehouse
		# se2 = frappe.new_doc("Stock Entry")
		# se2.fg_completed_qty = 0
		# se2.posting_date = self.report_date
		# se2.purpose = "Material Transfer"
		# se2.stock_entry_type = "Material Transfer"
		# se2.company = ref_doc.company
		# se2.update({
		# 	"to_warehouse": ref_doc.to_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
		# 	"from_warehouse": default_quality_inspection_warehouse
		# })
		# for row in ref_doc.items:
		# 	if self.reference_type == "Stock Entry":
		# 		if row.t_warehouse and row.is_finished_item and row.item_code == self.item_code:
		# 			if self.custom_lrf_reference_name:
		# 				ref_lrf_sample_size = self.sample_size or frappe.db.get_value("Label Requisition Form",self.custom_lrf_reference_name,'custom_sample_size')
		# 				se2.append("items", {
		# 					'item_code': row.item_code,
		# 					'quality_inspection': self.name,
		# 					's_warehouse': default_quality_analysis_warehouse,
		# 					't_warehouse': ref_doc.to_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
		# 					'qty': flt(row.qty) - flt(ref_lrf_sample_size),
		# 					'batch_no': row.batch_no,
		# 					'basic_rate': row.basic_rate,  # Stock Entry uses basic_rate
		# 					'lot_no': row.lot_no,
		# 					'ar_no': row.ar_no,
		# 					'use_serial_batch_fields': 1
		# 				})
		# se2.custom_quality_inspection_reference_ = self.name
		# se2.save()
		# se2.submit()
		# url = get_url_to_form("Stock Entry", se2.name)
		# frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Material Transfer".format(
		# 	url=url, doc=frappe.bold(se2.name)))
		
	# else:
	se = frappe.new_doc("Stock Entry")
	se.fg_completed_qty = 0
	se.posting_date = self.report_date
	se.purpose = "Material Transfer"
	se.stock_entry_type = "Material Transfer"
	se.company = ref_doc.company
	se.update({
			"to_warehouse": ref_doc.to_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
			"from_warehouse": default_quality_inspection_warehouse
	})
	for row in ref_doc.items:
		if self.reference_type == "Stock Entry":
			if row.t_warehouse and row.is_finished_item and row.item_code == self.item_code:
				se.append("items", {
					'item_code': row.item_code,
					'quality_inspection': self.name,
					's_warehouse': default_quality_inspection_warehouse,
					't_warehouse': ref_doc.to_warehouse if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
					'qty': flt(row.qty) - flt(self.sample_size),
					'batch_no': row.batch_no,
					'basic_rate': row.basic_rate,  # Stock Entry uses basic_rate
					'lot_no': row.lot_no,
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})			
			elif self.reference_type == "Stock Entry" and row.t_warehouse and row.item_code == self.item_code and row.quality_inspection_required_for_scrap and row.is_scrap_item:
				se.append("items", {
					'item_code': row.item_code,
					'quality_inspection': self.name,
					's_warehouse': default_quality_inspection_warehouse,
					't_warehouse': frappe.db.get_value("Work Order", ref_doc.work_order, "scrap_warehouse") if self.workflow_state == "Approved" and self.status == "Accepted" else rejection_warehouse,
					'qty': flt(row.qty) - flt(self.sample_size),
					'batch_no': row.batch_no,
					'basic_rate': row.basic_rate if hasattr(row, 'basic_rate') else row.rate,  # Fallback for basic_rate
					'lot_no': row.lot_no,
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})

	se.save()
	se.submit()
	url = get_url_to_form("Stock Entry", se.name)
	self.db_set("stock_entry",se.name)
	frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Material Transfer".format(
		url=url, doc=frappe.bold(se.name)))

def repack_stock_entry_type(self, ref_doc):
	if self.reference_type == "Stock Entry":
		se_doc = frappe.get_doc("Stock Entry",self.reference_name)
	default_quality_inspection_warehouse, rejection_warehouse = frappe.db.get_value(
		"Company", ref_doc.company, ['default_quality_inspection_warehouse', 'rejection_warehouse'])
	se = frappe.new_doc("Stock Entry")
	se.fg_completed_qty = 0
	se.posting_date = self.report_date
	se.purpose = "Material Transfer"
	se.stock_entry_type = "Material Transfer"
	se.company = ref_doc.company
	if self.reference_type == "Stock Entry":
		se.update({
			"to_warehouse": ref_doc.to_warehouse if self.workflow_state == "Approved" else rejection_warehouse,
			"from_warehouse": default_quality_inspection_warehouse
		})
	for row in ref_doc.items:
		if self.reference_type == "Stock Entry":
			if row.t_warehouse and row.is_finished_item and row.item_code == self.item_code:
				se.append("items", {
					'item_code': row.item_code,
					'quality_inspection': self.name,
					's_warehouse': default_quality_inspection_warehouse,
					't_warehouse': self.warehouse,
					'qty': flt(row.qty) - flt(self.sample_size),
					'batch_no': row.batch_no,
					'basic_rate': row.basic_rate, 
					'lot_no': row.lot_no,
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})
	se.save()
	se.submit()
	url = get_url_to_form("Stock Entry", se.name)
	self.db_set("stock_entry",se.name)
	frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Repack".format(
		url=url, doc=frappe.bold(se.name)))