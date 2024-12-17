import frappe
from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan as _ProductionPlan,set_default_warehouses
from frappe.utils import (
	add_days,
	ceil,
	cint,
	comma_and,
	flt,
	get_link_to_form,
	getdate,
	now_datetime,
	nowdate,
)
from frappe import _, msgprint
from erpnext.manufacturing.doctype.work_order.work_order import get_item_details
from erpnext.manufacturing.doctype.bom.bom import get_children as get_bom_children



class ProductionPlan(_ProductionPlan):
	@frappe.whitelist()
	def make_material_request(self):
		"""Create Material Requests grouped by Sales Order and Material Request Type"""
		material_request_list = []
		material_request_map = {}

		for item in self.mr_items:
			item_doc = frappe.get_cached_doc("Item", item.item_code)

			material_request_type = item.material_request_type or item_doc.default_material_request_type

			# key for Sales Order:Material Request Type:Customer
			key = "{}:{}:{}".format(item.sales_order, material_request_type, item_doc.customer or "")
			schedule_date = item.schedule_date or add_days(nowdate(), cint(item_doc.lead_time_days))

			if key not in material_request_map:
				# make a new MR for the combination
				material_request_map[key] = frappe.new_doc("Material Request")
				material_request = material_request_map[key]
				material_request.update(
					{
						"transaction_date": nowdate(),
						"status": "Draft",
						"company": self.company,
						"material_request_type": material_request_type,
						"customer": item_doc.customer or "",
						"select_department":self.select_department,
					}
				)
				material_request_list.append(material_request)
			else:
				material_request = material_request_map[key]

			# add item
			material_request.append(
				"items",
				{
					"item_code": item.item_code,
					"from_warehouse": item.from_warehouse
					if material_request_type == "Material Transfer"
					else None,
					"item_purpose":item.item_purpose,
					"qty": item.quantity,
					"schedule_date": schedule_date,
					"warehouse": item.warehouse,
					"sales_order": item.sales_order,
					"production_plan": self.name,
					"material_request_plan_item": item.name,
					"project": frappe.db.get_value("Sales Order", item.sales_order, "project")
					if item.sales_order
					else None,
				},
			)

		for material_request in material_request_list:
			# submit
			material_request.flags.ignore_permissions = 1
			material_request.run_method("set_missing_values")

			material_request.save()
			if self.get("submit_material_request"):
				material_request.submit()

		frappe.flags.mute_messages = False

		if material_request_list:
			material_request_list = [
				f"""<a href="/app/Form/Material Request/{m.name}">{m.name}</a>"""
				for m in material_request_list
			]
			msgprint(_("{0} created").format(comma_and(material_request_list)))
		else:
			msgprint(_("No material request created"))

	@frappe.whitelist()
	def make_work_order_with_sub_assembly_item(self):
		from erpnext.manufacturing.doctype.work_order.work_order import get_default_warehouse

		wo_list= []
		default_warehouses = get_default_warehouse()

		self.make_work_order_for_finished_goods(wo_list, default_warehouses)
		self.show_list_created_message("Work Order", wo_list)

		if not wo_list:
			frappe.msgprint(_("No Work Orders were created"))

	def make_work_order_for_finished_goods(self, wo_list, default_warehouses):
		items_data = self.get_production_items()

		for _key, item in items_data.items():
			if self.sub_assembly_items:
				item["use_multi_level_bom"] = 1

			set_default_warehouses(item, default_warehouses)
			work_order = self.create_work_order(item)
			if work_order:
				wo_list.append(work_order)

	def get_production_items(self):
		item_dict = {}
		for d in self.po_items:
			item_details = {
				"production_item": d.item_code,
				"use_multi_level_bom": d.include_exploded_items,
				"sales_order": d.sales_order,
				"sales_order_item": d.sales_order_item,
				"material_request": d.material_request,
				"material_request_item": d.material_request_item,
				"bom_no": d.bom_no,
				"description": d.description,
				"stock_uom": d.stock_uom,
				"company": self.company,
				"fg_warehouse": d.warehouse,
				"production_plan": self.name,
				"production_plan_item": d.name,
				"product_bundle_item": d.product_bundle_item,
				"planned_start_date": d.planned_start_date,
				"project": self.project,
			}

			key = (d.item_code, d.sales_order, d.warehouse, d.name)
			if not d.sales_order:
				key = (d.name, d.item_code, d.warehouse, d.name)

			if not item_details["project"] and d.sales_order:
				item_details["project"] = frappe.get_cached_value(
					"Sales Order", d.sales_order, "project"
				)

			if self.get_items_from == "Material Request":
				item_details.update({"qty": d.planned_qty})
				item_dict[(d.item_code, d.name, d.warehouse)] = item_details
			else:
				item_details.update(
					{
						"qty": flt(item_dict.get(key, {}).get("qty"))
						+ (flt(d.planned_qty) - flt(d.ordered_qty))
					}
				)
				item_dict[key] = item_details

		return item_dict


	
	@frappe.whitelist()
	def get_items(self):
		self.set("po_items", [])
		if self.get_items_from == "Sales Order":
			self.get_so_items()

		elif self.get_items_from == "Material Request":
			self.get_mr_items()


	def add_items(self, items):
		refs = {}
		for data in items:
			if not data.pending_qty:
				continue

			item_details = get_item_details(data.item_code, throw=False)
			if self.combine_items:
				bom_no = item_details.bom_no
				if data.get("bom_no"):
					bom_no = data.get("bom_no")

				if bom_no in refs:
					refs[bom_no]["so_details"].append(
						{"sales_order": data.parent, "sales_order_item": data.name, "qty": data.pending_qty}
					)
					refs[bom_no]["qty"] += data.pending_qty
					continue

				else:
					refs[bom_no] = {
						"qty": data.pending_qty,
						"po_item_ref": data.name,
						"so_details": [],
					}
					refs[bom_no]["so_details"].append(
						{"sales_order": data.parent, "sales_order_item": data.name, "qty": data.pending_qty}
					)

			bom_no = data.bom_no or item_details and item_details.get("bom_no") or ""
			if not bom_no:
				continue

			bom_details = frappe.get_doc("BOM", bom_no)
			bom_qty = bom_details.quantity  # BOM defines this as the standard batch size
			pending_qty = data.pending_qty  # Total pending quantity for this item

			# Add rows based on BOM quantity
			while pending_qty > 0:
				row_qty = min(bom_qty, pending_qty)  # Take the BOM qty or the remaining qty
				pi = self.append(
					"po_items",
					{
						"warehouse": data.warehouse,
						"item_code": data.item_code,
						"description": data.description or item_details.description,
						"stock_uom": item_details and item_details.stock_uom or "",
						"bom_no": bom_no,
						"planned_qty": row_qty,  # This row's planned quantity
						"pending_qty": row_qty,  # This row's pending quantity
						"planned_start_date": now_datetime(),
						"product_bundle_item": data.parent_item,
					},
				)
				pending_qty -= row_qty

			if self.get_items_from == "Sales Order":
				pi.sales_order = data.parent
				pi.sales_order_item = data.name
				pi.description = data.description

			elif self.get_items_from == "Material Request":
				pi.material_request = data.parent
				pi.material_request_item = data.name
				pi.description = data.description

		if refs:
			for po_item in self.po_items:
				po_item.planned_qty = refs[po_item.bom_no]["qty"]
				po_item.pending_qty = refs[po_item.bom_no]["qty"]
				po_item.sales_order = ""
			self.add_pp_ref(refs)

	@frappe.whitelist()
	def get_sub_assembly_items(self, manufacturing_type=None):
		"Fetch sub assembly items and optionally combine them."
		self.sub_assembly_items = []
		sub_assembly_items_store = []  # temporary store to process all subassembly items

		for row in self.po_items:
			if self.skip_available_sub_assembly_item and not self.sub_assembly_warehouse:
				frappe.throw(_("Row #{0}: Please select the Sub Assembly Warehouse").format(row.idx))

			if not row.item_code:
				frappe.throw(_("Row #{0}: Please select Item Code in Assembly Items").format(row.idx))

			if not row.bom_no:
				frappe.throw(_("Row #{0}: Please select the BOM No in Assembly Items").format(row.idx))

			bom_data = []

			warehouse = (self.sub_assembly_warehouse) if self.skip_available_sub_assembly_item else None
			get_sub_assembly_items(row.bom_no, bom_data, row.planned_qty, self.company, warehouse=warehouse)
			self.set_sub_assembly_items_based_on_level(row, bom_data, manufacturing_type)
			sub_assembly_items_store.extend(bom_data)

		if not sub_assembly_items_store and self.skip_available_sub_assembly_item:
			message = (
				_(
					"As there are sufficient Sub Assembly Items, Work Order is not required for Warehouse {0}."
				).format(self.sub_assembly_warehouse)
				+ "<br><br>"
			)
			message += _(
				"If you still want to proceed, please disable 'Skip Available Sub Assembly Items' checkbox."
			)

			frappe.msgprint(message, title=_("Note"))

		if self.combine_sub_items:
			# Combine subassembly items
			sub_assembly_items_store = self.combine_subassembly_items(sub_assembly_items_store)

		for idx, row in enumerate(sub_assembly_items_store):
			row.idx = idx + 1
			self.append("sub_assembly_items", row)

		self.set_default_supplier_for_subcontracting_order()

def get_sub_assembly_items(bom_no, bom_data, to_produce_qty, company, warehouse=None, indent=0):
	# Fetch all child items of the BOM
	data = get_bom_children(parent=bom_no)

	for d in data:
		if d.expandable:
			# Fetch parent item code for reference
			parent_item_code = frappe.get_cached_value("BOM", bom_no, "item")
			bom_qty = flt(d.parent_bom_qty)  # Ensure it's a float
			required_qty = flt((d.stock_qty / bom_qty) * to_produce_qty)  # Total required stock
			remaining_qty = required_qty  # Initialize remaining quantity
			
			# Check availability in warehouse
			if warehouse:
				bin_details = get_bin_details(d, company, for_warehouse=warehouse)

				for _bin_dict in bin_details:
					if _bin_dict.projected_qty > 0:
						if _bin_dict.projected_qty >= remaining_qty:
							remaining_qty = 0
							break
						else:
							remaining_qty -= _bin_dict.projected_qty

			# Add rows in chunks of `bom_qty`
			while remaining_qty > 0:
				# Handle the first row separately if needed
				batch_qty = min(bom_qty, remaining_qty)  # For subsequent rows, use smaller values

				bom_data.append(
					frappe._dict(
						{
							"parent_item_code": parent_item_code,
							"description": d.description,
							"production_item": d.item_code,
							"item_name": d.item_name,
							"stock_uom": d.stock_uom,
							"uom": d.stock_uom,
							"bom_no": d.value,
							"is_sub_contracted_item": d.is_sub_contracted_item,
							"bom_level": indent,
							"indent": indent,
							"stock_qty": batch_qty,  # Batch quantity for this row
						}
					)
				)

				remaining_qty -= batch_qty  # Decrease remaining quantity
			
			# If there's a sub-BOM, recursively fetch its items
			if d.value:
				get_sub_assembly_items(
					d.value, bom_data, required_qty, company, warehouse, indent=indent + 1
				)
