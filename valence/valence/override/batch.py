from chemical.chemical.override.doctype.batch import Batch as _Batch
import frappe
from frappe.utils import nowdate
from frappe.model.naming import make_autoname
from frappe import _
from erpnext.stock.doctype.batch.batch import batch_uses_naming_series,get_name_from_hash


class Batch(_Batch):
	def autoname(self):
		"""Generate random ID for batch if not specified"""

		if self.batch_id:
			self.name = self.batch_id
			return

		create_new_batch, batch_number_series = frappe.db.get_value(
			"Item", self.item, ["create_new_batch", "batch_number_series"]
		)

		if not create_new_batch:
			frappe.throw(_("Batch ID is mandatory"), frappe.MandatoryError)

		while not self.batch_id:
			if batch_number_series:
				if self.posting_date:
					batch_number_series = batch_number_series.replace("posting_date", self.posting_date)
				else:
					batch_number_series = batch_number_series.replace("posting_date", nowdate())
				self.batch_id = make_autoname(batch_number_series, doc=self)
			elif batch_uses_naming_series():
				self.batch_id = self.get_name_from_naming_series()
			else:
				self.batch_id = get_name_from_hash()

			# User might have manually created a batch with next number
			if frappe.db.exists("Batch", self.batch_id):
				self.batch_id = None

		self.name = self.batch_id
