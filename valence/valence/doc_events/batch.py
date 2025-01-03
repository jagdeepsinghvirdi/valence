import frappe
from frappe.utils import nowdate, date_diff

def real_time_status_update():
	# Fetch all Batch records
	batches = frappe.get_all(
		"Batch",
		fields=["name", "disabled", "expiry_date", "retest_date", "batch_qty", "set_status"]
	)
	
	for batch in batches:
		new_status = "Active"
		if batch.disabled:
			new_status = "Disabled"
		elif batch.expiry_date and date_diff(batch.expiry_date, nowdate()) <= 0:
			new_status = "Expired"
		elif batch.retest_date and date_diff(batch.retest_date, nowdate()) <= 0:
			new_status = "Retest"
		elif not batch.batch_qty or batch.batch_qty <= 0:
			new_status = "Empty"

		if batch.set_status != new_status:
			batch_doc = frappe.get_doc("Batch", batch.name)
			batch_doc.set_status = new_status
			batch_doc.flags.ignore_save_modified = False
			batch_doc.save()  

	frappe.db.commit()  
