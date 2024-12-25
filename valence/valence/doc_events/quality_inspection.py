import frappe
from frappe.utils import add_months, get_last_day, nowdate,add_days,formatdate

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
			batch_no.db_set("retest_date",self.retest_date)
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