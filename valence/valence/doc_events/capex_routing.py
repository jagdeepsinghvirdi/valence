"""Capex routing for project purchases.

Settings (Stock Settings, all blank = feature off):
  custom_project_store_warehouse  – warehouse that receives stock items bought for projects
  custom_project_capex_account    – account an issue out of that warehouse is charged to (e.g. WIP Plant & Machinery)
  custom_project_department       – department value that marks a purchase as a project purchase (default "Project")

Flow: Material Request (Purchase) or Purchase Order with the project department → stock items get the project store
as warehouse → Purchase Receipt (and Purchase Invoice with Update Stock) against such a PO receives into the project
store → any Material Issue out of the project store is charged to the capex account (see StockEntry override).
"""

import frappe
from frappe.utils import cint


def get_settings():
	meta = frappe.get_meta("Stock Settings")
	if not meta.has_field("custom_project_store_warehouse"):
		return None
	values = frappe.db.get_value(
		"Stock Settings",
		"Stock Settings",
		["custom_project_store_warehouse", "custom_project_capex_account", "custom_project_department"],
		as_dict=True,
	)
	if not values or not values.custom_project_store_warehouse:
		return None
	values.custom_project_department = (values.custom_project_department or "Project").strip()
	return values


def _is_stock_item(item_code):
	return item_code and cint(frappe.get_cached_value("Item", item_code, "is_stock_item"))


def _warehouse_company(warehouse):
	return frappe.get_cached_value("Warehouse", warehouse, "company")


def _route_rows(doc, settings, rows, field="warehouse"):
	store = settings.custom_project_store_warehouse
	if _warehouse_company(store) != doc.company:
		return False
	changed = False
	for row in rows:
		if _is_stock_item(row.item_code) and row.get(field) != store:
			row.set(field, store)
			changed = True
	return changed


def material_request_validate(doc, method=None):
	settings = get_settings()
	if not settings or doc.get("material_request_type") != "Purchase":
		return
	if (doc.get("select_department") or "").strip() != settings.custom_project_department:
		return
	_route_rows(doc, settings, doc.items)
	if doc.meta.has_field("set_warehouse") and any(_is_stock_item(r.item_code) for r in doc.items):
		doc.set_warehouse = settings.custom_project_store_warehouse


def purchase_order_validate(doc, method=None):
	settings = get_settings()
	if not settings:
		return
	if (doc.get("custom_department") or "").strip() != settings.custom_project_department:
		return
	_route_rows(doc, settings, doc.items)
	if doc.meta.has_field("set_warehouse") and any(_is_stock_item(r.item_code) for r in doc.items):
		doc.set_warehouse = settings.custom_project_store_warehouse


def _project_po_names(settings, po_names):
	po_names = [p for p in set(po_names) if p]
	if not po_names:
		return set()
	return set(
		frappe.get_all(
			"Purchase Order",
			filters={"name": ["in", po_names], "custom_department": settings.custom_project_department},
			pluck="name",
		)
	)


def purchase_receipt_validate(doc, method=None):
	"""Receive stock items of project POs into the project store (also used for Purchase Invoice with Update Stock)."""
	settings = get_settings()
	if not settings or cint(doc.get("is_return")):
		return
	if doc.doctype == "Purchase Invoice" and not cint(doc.get("update_stock")):
		return
	project_pos = _project_po_names(settings, [r.get("purchase_order") for r in doc.items])
	if not project_pos:
		return
	rows = [r for r in doc.items if r.get("purchase_order") in project_pos]
	_route_rows(doc, settings, rows)
	if rows and len(rows) == len([r for r in doc.items if _is_stock_item(r.item_code)]) and doc.meta.has_field("set_warehouse"):
		doc.set_warehouse = settings.custom_project_store_warehouse


def issue_account_for_row(company, row, settings):
	"""Capex account for a Material Issue row out of the project store, or None to leave the row as it is.

	A row already charged to a Balance Sheet asset account (e.g. Lab Equipments, Buildings, WIP Building) is kept, so a
	specific capitalisation chosen by the user wins. Anything else (expense accounts, item-group defaults) becomes the
	project capex account."""
	if not settings or not settings.custom_project_capex_account:
		return None
	if row.get("s_warehouse") != settings.custom_project_store_warehouse or row.get("t_warehouse"):
		return None
	capex = settings.custom_project_capex_account
	if frappe.get_cached_value("Account", capex, "company") != company:
		return None
	if row.get("expense_account"):
		acc = frappe.get_cached_value("Account", row.expense_account, ["root_type", "account_type"], as_dict=True)
		if acc and acc.root_type == "Asset" and acc.account_type != "Stock":
			return None
	return capex
