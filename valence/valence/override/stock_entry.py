from chemical.chemical.override.doctype.stock_entry import StockEntry as _StockEntry
import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import get_available_materials
from frappe.utils import (
	cint,
	comma_or,
	cstr,
	flt,
	format_time,
	formatdate,
	get_link_to_form,
	getdate,
	nowdate,
)
from collections import defaultdict
from frappe import _, bold
from erpnext.controllers.stock_controller import BatchExpiredError



class StockEntry(_StockEntry):
	def add_transfered_raw_materials_in_items(self) -> None:
		available_materials = get_available_materials(self.work_order)

		wo_data = frappe.db.get_value(
			"Work Order",
			self.work_order,
			["qty", "produced_qty", "material_transferred_for_manufacturing as trans_qty"],
			as_dict=1,
		)
		precision = frappe.get_precision("Stock Entry Detail", "qty")
		# under production as mention in manufacturing settings
		under_production = flt(frappe.db.get_single_value("Manufacturing Settings", "under_production_allowance_percentage"))
		for _key, row in available_materials.items():
			remaining_qty_to_produce = flt(wo_data.trans_qty) - flt(wo_data.produced_qty)
			if remaining_qty_to_produce <= 0 and not self.is_return:
				continue

			qty = flt(row.qty)
			if not self.is_return:
				if under_production:
					qty = (flt(row.qty))
				else:
					qty = (flt(row.qty) * flt(self.fg_completed_qty)) / remaining_qty_to_produce
			# changes end
			item = row.item_details
			if cint(frappe.get_cached_value("UOM", item.stock_uom, "must_be_whole_number")):
				qty = frappe.utils.ceil(qty)

			if row.batch_details:
				row.batches_to_be_consume = defaultdict(float)
				batches = row.batch_details
				self.update_batches_to_be_consume(batches, row, qty)

			elif row.serial_nos:
				serial_nos = row.serial_nos[0 : cint(qty)]
				row.serial_nos = serial_nos

			if flt(qty, precision) != 0.0:
				self.update_item_in_stock_entry_detail(row, item, qty)
				
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