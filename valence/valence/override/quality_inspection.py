import frappe
from erpnext.stock.doctype.quality_inspection.quality_inspection import QualityInspection as _QualityInspection
from frappe import _ 
from frappe.utils import cint, cstr, flt, get_link_to_form, get_number_format_info


class QualityInspection(_QualityInspection):
	def validate_inspection_required(self):
		if self.reference_type in ["Purchase Receipt", "Purchase Invoice"] and not frappe.get_cached_value(
			"Item", self.item_code, "inspection_required_before_purchase") and not frappe.get_cached_value("Item",self.item_code,"inspection_required_after_purchase"):
			frappe.throw(
				_(
					"'Inspection Required before Purchase' has disabled for the item {0}, no need to create the QI"
				).format(get_link_to_form("Item", self.item_code))
			)

		if self.reference_type in ["Delivery Note", "Sales Invoice"] and not frappe.get_cached_value(
			"Item", self.item_code, "inspection_required_before_delivery"
		):
			frappe.throw(
				_(
					"'Inspection Required before Delivery' has disabled for the item {0}, no need to create the QI"
				).format(get_link_to_form("Item", self.item_code))
			)