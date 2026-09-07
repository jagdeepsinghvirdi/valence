import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import get_available_materials
from erpnext.stock.utils import get_incoming_rate
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

try:
	# Cloud / full chemical app
	from chemical.chemical.override.doctype.stock_entry import StockEntry as _StockEntry
except ModuleNotFoundError:
	# Local bench without full chemical override package
	from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry as _StockEntry


class StockEntry(_StockEntry):
	def _uses_consumption_entry_cost(self) -> bool:
		"""True when Manufacture FG cost must come from submitted consumption entries."""
		if self.purpose != "Manufacture" or cint(self.is_return) or not self.work_order:
			return False
		if not cint(frappe.db.get_single_value("Manufacturing Settings", "material_consumption")):
			return False
		if not cint(
			frappe.db.get_single_value("Manufacturing Settings", "get_rm_cost_from_consumption_entry")
		):
			return False
		if hasattr(self, "get_consumption_entries"):
			return bool(self.get_consumption_entries())
		return bool(
			frappe.db.exists(
				"Stock Entry",
				{
					"docstatus": 1,
					"work_order": self.work_order,
					"purpose": "Material Consumption for Manufacture",
				},
			)
		)

	def _drop_raw_materials_for_consumption_costing(self) -> None:
		"""Keep Finish/Manufacture as FG-only so users need not toggle Manufacturing Settings."""
		if not self._uses_consumption_entry_cost():
			return
		for row in list(self.get("items") or []):
			if not cint(row.is_finished_item) and not cint(row.is_scrap_item):
				self.remove(row)

	def get_items(self):
		super().get_items()
		self._drop_raw_materials_for_consumption_costing()

	def validate(self):
		self._drop_raw_materials_for_consumption_costing()
		super().validate()

	def get_basic_rate_for_manufactured_item(
		self, finished_item_qty, outgoing_items_cost=0, has_consumption_basis=False
	):
		self._drop_raw_materials_for_consumption_costing()
		parent = super().get_basic_rate_for_manufactured_item
		try:
			rate = parent(finished_item_qty, outgoing_items_cost, has_consumption_basis)
		except TypeError:
			rate = parent(finished_item_qty, outgoing_items_cost)

		# Consumption + scrap costing can push FG rate below zero when scrap value
		# exceeds booked consumption cost (common on partial Finish). ERPNext then
		# blocks save with NonNegativeError on Basic Rate.
		return max(0.0, flt(rate))

	def set_rate_for_outgoing_items(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		outgoing_items_cost = 0.0
		for d in self.get("items"):
			if d.s_warehouse:
				if reset_outgoing_rate:
					args = self.get_args_for_incoming_rate(d)
					rate = get_incoming_rate(args, raise_error_if_no_rate)
					# Never pass negative valuation into Basic Rate (Stock Entry Detail is non_negative).
					d.basic_rate = max(0.0, flt(rate)) if rate is not None else 0.0

				d.basic_rate = max(0.0, flt(d.basic_rate))
				d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))
				if not d.t_warehouse:
					outgoing_items_cost += flt(d.basic_amount)

		return outgoing_items_cost

	def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		self._drop_raw_materials_for_consumption_costing()
		super().set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)
		for d in self.get("items") or []:
			if flt(d.basic_rate) < 0:
				d.basic_rate = 0.0
				d.basic_amount = 0.0

	def add_transfered_raw_materials_in_items(self) -> None:
		# Consumption already booked RM; Finish must not backflush them again.
		if self._uses_consumption_entry_cost():
			return

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