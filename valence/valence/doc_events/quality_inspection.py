import frappe
from frappe.utils import add_months, get_last_day, nowdate,add_days,formatdate,get_url_to_form

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
				material_transfer(self, doc)
		elif self.reference_type == "Purchase Receipt":
			material_transfer(self,doc)

def material_transfer(self, ref_doc):
	if self.reference_type == "Stock Entry":
		se_doc = frappe.get_doc("Stock Entry",self.reference_name)
	elif self.reference_type == "Purchase Receipt":
		se_doc = frappe.get_doc("Purchase Receipt",self.reference_name)
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
	elif self.reference_type == "Purchase Receipt":	
		se.update({
			"to_warehouse": ref_doc.set_warehouse if self.workflow_state == "Approved" else rejection_warehouse,
			"from_warehouse": default_quality_inspection_warehouse
			})
	for row in ref_doc.items:
		if self.reference_type == "Stock Entry":
			if row.t_warehouse and row.is_finished_item and row.item_code == self.item_code:
				se.append("items", {
					'item_code': row.item_code,
					'quality_inspection': self.name,
					's_warehouse': default_quality_inspection_warehouse,
					't_warehouse': ref_doc.to_warehouse if self.workflow_state == "Approved" else rejection_warehouse,
					'qty': row.qty,
					'batch_no': row.batch_no,
					'basic_rate': row.basic_rate,  # Stock Entry uses basic_rate
					'lot_no': row.lot_no,
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})
		elif self.reference_type == "Purchase Receipt":
			se.append("items", {
				'item_code': row.item_code,
				'quality_inspection': self.name,
				's_warehouse': default_quality_inspection_warehouse,
				't_warehouse': self.warehouse,
				'qty': row.qty,
				'batch_no': row.batch_no,
				'basic_rate': row.rate,  # Replace basic_rate with rate for Purchase Receipt
				'lot_no': row.lot_no,
				'ar_no': row.ar_no,
				'use_serial_batch_fields': 1,
			})
		elif row.t_warehouse and row.item_code == self.item_code and row.quality_inspection_required_for_scrap and row.is_scrap_item:
			se.append("items", {
				'item_code': row.item_code,
				'quality_inspection': self.name,
				's_warehouse': default_quality_inspection_warehouse,
				't_warehouse': frappe.db.get_value("Work Order", ref_doc.work_order, "scrap_warehouse") if self.workflow_state == "Approved" else rejection_warehouse,
				'qty': row.qty,
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