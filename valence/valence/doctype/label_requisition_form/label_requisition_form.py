# Copyright (c) 2025, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_url_to_form,flt


class LabelRequisitionForm(Document):

	def on_submit(self):
		if self.released_qty_kgs != self.total_net_weight:
			frappe.throw(f"Released Quantity ({self.released_qty_kgs} kg) must be equal to Total Net Weight ({self.total_net_weight} kg). Please check the values.")
				
		# self.create_quality_inspection()
		# self.material_transfer_stock_entry()
		# self.update_sample_size()

	# def update_sample_size(self):
		# qi_name = frappe.get_doc("Quality Inspection",{'custom_lrf_reference_name':self.name})
		# qi_name.db_set('sample_size',self.custom_sample_size)
	
	def create_quality_inspection(self):
		# Create a new Quality Inspection document
		
		qi = frappe.new_doc("Quality Inspection")
		qi.inspection_type = "Incoming"  # or "In Process" or "Final" depending on your case
		qi.reference_type = "Stock Entry"
		qi.reference_name = self.stock_entry_reference_name
		# qi.custom_lrf_reference_name = self.name
		qi.item_code = self.production_item
		qi.batch_no = self.batch_no 
		qi.sample_size = self.batch_size_kgs
		qi.lot_no = self.lot_no
		qi.ar_no = self.ar_no
		qi.expiry_date = self.retestexpiry_date
		qi.manufacturing_date = self.manufacturing_date
		qi.inspected_by = self.inspected_by
		qi.report_date = frappe.utils.nowdate()

		qi.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.msgprint(f"""Quality Inspection <a href="/app/quality-inspection/{qi.name}" target="_blank">{qi.name}</a> created automatically.""")
		
	def material_transfer_stock_entry(self):
		
		ref_doc = frappe.get_doc("Stock Entry",self.stock_entry_reference_name)

		default_quality_analysis_warehouse, default_quality_inspection_warehouse = frappe.db.get_value(
		"Company", ref_doc.company, ['custom_default_quality_analysis_warehouse', 'default_quality_inspection_warehouse'])
		
		se = frappe.new_doc("Stock Entry")
		se.fg_completed_qty = 0
		se.posting_date = self.date
		se.purpose = "Material Transfer"
		se.stock_entry_type = "Material Transfer"
		se.company = ref_doc.company
		
		for row in ref_doc.items:
			if row.t_warehouse and row.is_finished_item and row.item_code == self.production_item:
				
				se.append("items", {
					'item_code': row.item_code,
					# 'quality_inspection': self.name,
					's_warehouse': default_quality_analysis_warehouse,	
					't_warehouse': default_quality_inspection_warehouse,
					'qty': flt(self.custom_sample_size),
					'batch_no': row.batch_no,
					'basic_rate': row.basic_rate,  # Stock Entry uses basic_rate
					'lot_no': row.lot_no,
					'ar_no': row.ar_no,
					'use_serial_batch_fields': 1,
				})

		se.save()
		se.submit()
		url = get_url_to_form("Stock Entry", se.name)
		# self.db_set("stock_entry",se.name)
		frappe.msgprint("New Stock Entry - <a href='{url}'>{doc}</a> created for Material Transfer".format(
			url=url, doc=frappe.bold(se.name)))

