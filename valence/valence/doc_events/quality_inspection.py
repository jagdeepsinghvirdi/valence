import frappe
from frappe.utils import add_months, get_last_day, nowdate

def on_submit(self, method):
	if self.reference_type:
		ref_doctype = frappe.get_doc(self.reference_type, self.reference_name)
		for row in ref_doctype.items:
			if self.item_code == row.item_code:
				row.lot_no = self.lot_no
				row.ar_no = self.ar_no
		ref_doctype.save()

	if self.batch_no:
		batch_no = frappe.get_doc("Batch",self.batch_no)
		batch_no.db_set("ar_no",self.ar_no)
		if self.retest_date:
			batch_no.db_set("retest_date",self.retest_date)
		if self.expiry_date:
			batch_no.db_set("retest_date",self.retest_date)

def before_submit(self,method):
	if not self.ar_no:
		frappe.throw("AR No. is Mandatory Field")

def before_save(self, method):
	if self.retest_month:
		today = nowdate()  
		new_date = add_months(today, int(self.retest_month))
		retest_date = get_last_day(new_date)  
		self.retest_date = retest_date