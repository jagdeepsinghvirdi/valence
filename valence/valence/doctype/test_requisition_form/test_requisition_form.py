# Copyright (c) 2025, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TestRequisitionForm(Document):
	def on_submit(self):
		self.update_batch_spec_from_trf()

	def update_batch_spec_from_trf(self):
		if not self.batch:
			frappe.throw("Batch No is not set.")

		batch_doc = frappe.get_doc("Batch", self.batch)
		if not batch_doc:
			frappe.throw(f"Batch {self.batch} does not exist.")
		batch_doc.db_set("ih", self.ih)
		batch_doc.db_set("ip", self.ip)
		batch_doc.db_set("usp", self.usp)
		batch_doc.db_set("epbp", self.epbp)

		batch_doc.db_set("ar_no_ih", self.ar_no_ih)
		batch_doc.db_set("ar_no_ip", self.ar_no_ip)
		batch_doc.db_set("ar_no_usp", self.ar_no_usp)
		batch_doc.db_set("ar_no_epbp", self.ar_no_epbp)

	
