import frappe
from erpnext.controllers.queries import get_filterd_batches, get_empty_batches
from frappe.utils import nowdate, today, unique
from frappe.query_builder.functions import Concat, Locate, Sum


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_batch_no(doctype, txt, searchfield, start, page_len, filters):
	doctype = "Batch"
	meta = frappe.get_meta(doctype, cached=True)
	searchfields = meta.get_search_fields()
	page_len = 30

	batches = get_batches_from_stock_ledger_entries(searchfields, txt, filters, start, page_len)
	batches.extend(get_batches_from_serial_and_batch_bundle(searchfields, txt, filters, start, page_len))

	filtered_batches = get_filterd_batches(batches)

	if filters.get("is_inward"):
		filtered_batches.extend(get_empty_batches(filters, start, page_len, filtered_batches, txt))

	return filtered_batches

def get_batches_from_stock_ledger_entries(searchfields, txt, filters, start=0, page_len=100):
	stock_ledger_entry = frappe.qb.DocType("Stock Ledger Entry")
	batch_table = frappe.qb.DocType("Batch")

	expiry_date = filters.get("posting_date") or today()

	query = (
		frappe.qb.from_(stock_ledger_entry)
		.inner_join(batch_table)
		.on(batch_table.name == stock_ledger_entry.batch_no)
		.select(
			stock_ledger_entry.batch_no,
			Sum(stock_ledger_entry.actual_qty).as_("qty"),
			batch_table.lot_no, 
			batch_table.concentration,
		)
		.where((batch_table.expiry_date >= expiry_date) | (batch_table.expiry_date.isnull()))
		.where((batch_table.retest_date >= expiry_date) | (batch_table.retest_date.isnull()))
		.where(stock_ledger_entry.is_cancelled == 0)
		.where(
			(stock_ledger_entry.item_code == filters.get("item_code"))
			& (batch_table.disabled == 0)
			& (stock_ledger_entry.batch_no.isnotnull())
		)
		.groupby(stock_ledger_entry.batch_no, stock_ledger_entry.warehouse)
		.having(Sum(stock_ledger_entry.actual_qty) != 0)
		.offset(start)
		.limit(page_len)
	)

	query = query.select(
		Concat("MFG-", batch_table.manufacturing_date).as_("manufacturing_date"),
		Concat("EXP-", batch_table.expiry_date).as_("expiry_date"),
	)

	if filters.get("warehouse"):
		query = query.where(stock_ledger_entry.warehouse == filters.get("warehouse"))

	for field in searchfields:
		query = query.select(batch_table[field])

	if txt:
		txt_condition = batch_table.name.like(f"%{txt}%")
		for field in [*searchfields, "name"]:
			txt_condition |= batch_table[field].like(f"%{txt}%")

		query = query.where(txt_condition)

	return query.run(as_list=1) or []

def get_batches_from_serial_and_batch_bundle(searchfields, txt, filters, start=0, page_len=100):
	bundle = frappe.qb.DocType("Serial and Batch Entry")
	stock_ledger_entry = frappe.qb.DocType("Stock Ledger Entry")
	batch_table = frappe.qb.DocType("Batch")

	expiry_date = filters.get("posting_date") or today()

	bundle_query = (
		frappe.qb.from_(bundle)
		.inner_join(stock_ledger_entry)
		.on(bundle.parent == stock_ledger_entry.serial_and_batch_bundle)
		.inner_join(batch_table)
		.on(batch_table.name == bundle.batch_no)
		.select(
			bundle.batch_no,
			Sum(bundle.qty).as_("qty"),
			batch_table.lot_no, 
			batch_table.concentration,
		)
		.where((batch_table.expiry_date >= expiry_date) | (batch_table.expiry_date.isnull()))
		.where((batch_table.retest_date >= expiry_date) | (batch_table.retest_date.isnull()))
		.where(stock_ledger_entry.is_cancelled == 0)
		.where(
			(stock_ledger_entry.item_code == filters.get("item_code"))
			& (batch_table.disabled == 0)
			& (stock_ledger_entry.serial_and_batch_bundle.isnotnull())
		)
		.groupby(bundle.batch_no, bundle.warehouse)
		.having(Sum(bundle.qty) != 0)
		.offset(start)
		.limit(page_len)
	)

	bundle_query = bundle_query.select(
		Concat("MFG-", batch_table.manufacturing_date),
		Concat("EXP-", batch_table.expiry_date),
	)

	if filters.get("warehouse"):
		bundle_query = bundle_query.where(stock_ledger_entry.warehouse == filters.get("warehouse"))

	for field in searchfields:
		bundle_query = bundle_query.select(batch_table[field])

	if txt:
		txt_condition = batch_table.name.like(f"%{txt}%")
		for field in [*searchfields, "name"]:
			txt_condition |= batch_table[field].like(f"%{txt}%")

		bundle_query = bundle_query.where(txt_condition)

	return bundle_query.run(as_list=1)