from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice as _SalesInvoice
import frappe
from frappe.utils import cint, cstr, flt, get_link_to_form, getdate
from frappe import _, bold
from erpnext.controllers.stock_controller import BatchExpiredError

class SalesInvoice(_SalesInvoice):
	def validate_serialized_batch(self):
		from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

		is_material_issue = False
		if self.doctype == "Stock Entry" and self.purpose == "Material Issue":
			is_material_issue = True

		for d in self.get("items"):
			if hasattr(d, "serial_no") and hasattr(d, "batch_no") and d.serial_no and d.batch_no:
				serial_nos = frappe.get_all(
					"Serial No",
					fields=["batch_no", "name", "warehouse"],
					filters={"name": ("in", get_serial_nos(d.serial_no))},
				)

				for row in serial_nos:
					if row.warehouse and row.batch_no != d.batch_no:
						frappe.throw(
							_("Row #{0}: Serial No {1} does not belong to Batch {2}").format(
								d.idx, row.name, d.batch_no
							)
						)

			if is_material_issue:
				continue

			if flt(d.qty) > 0.0 and d.get("batch_no") and self.get("posting_date") and self.docstatus < 2:
				expiry_date = frappe.get_cached_value("Batch", d.get("batch_no"), "expiry_date")
				# add validation retest date in same way work for expiry date 
				retest_date = frappe.get_cached_value("Batch", d.get("batch_no"), "retest_date")

				if retest_date and getdate(retest_date) < getdate(self.posting_date):
					frappe.throw(
						_("Row #{0}: The batch {1} has already reach it Restest date.").format(
							d.idx, get_link_to_form("Batch", d.get("batch_no"))
						),
						BatchExpiredError,
					)
				# changes end
				if expiry_date and getdate(expiry_date) < getdate(self.posting_date):
					frappe.throw(
						_("Row #{0}: The batch {1} has already expired.").format(
							d.idx, get_link_to_form("Batch", d.get("batch_no"))
						),
						BatchExpiredError,
					)