"""Chemical Stock Entry based-on handling when Based On item is omitted.

1) check_based_on_item — skip when SE already has any item rows (or Settings flag ON).
2) cal_target_yield_cons — skip yield calc when based_on item is not on the SE
   (avoids KeyError: based_on after check is skipped).
"""

from __future__ import annotations

import frappe
from frappe.utils import cint


def ensure_based_on_item_optional_field():
	"""Idempotent custom field on Manufacturing Settings."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Manufacturing Settings": [
				{
					"fieldname": "custom_based_on_item_optional",
					"label": "Make Based On Item Optional",
					"fieldtype": "Check",
					"insert_after": "custom_job_card_over_lap_time_not_required",
					"default": "0",
					"description": (
						"If enabled, always skip chemical Based On raw-material validation. "
						"When disabled: Based On check is skipped automatically if the Stock Entry "
						"already has at least one item row; yield calc is also skipped when Based On "
						"item is missing from items."
					),
					"module": "Valence",
				}
			]
		},
		ignore_validate=True,
		update=True,
	)


def apply_based_on_item_optional_patch():
	"""Wrap chemical based-on validate + yield helpers for optional Based On item."""
	try:
		from chemical.chemical.override.doc_event import stock_entry as chem_se
	except ImportError:
		return

	_patch_check_based_on_item(chem_se)
	_patch_cal_target_yield_cons(chem_se)


def _patch_check_based_on_item(chem_se):
	if getattr(chem_se, "_valence_based_on_any_item_patched", False):
		return
	if not hasattr(chem_se, "check_based_on_item"):
		return

	_original = chem_se.check_based_on_item

	def check_based_on_item(doc):
		if _is_based_on_item_optional():
			return
		if _has_any_item_row(doc):
			return
		return _original(doc)

	chem_se.check_based_on_item = check_based_on_item
	chem_se._valence_based_on_any_item_patched = True


def _patch_cal_target_yield_cons(chem_se):
	"""Avoid KeyError when based_on item is not in SE items (after optional skip)."""
	if getattr(chem_se, "_valence_cal_target_yield_safe_patched", False):
		return
	if not hasattr(chem_se, "cal_target_yield_cons"):
		return

	_original = chem_se.cal_target_yield_cons

	def cal_target_yield_cons(doc):
		based_on = (doc.get("based_on") or "").strip()
		if based_on and not _item_on_stock_entry(doc, based_on):
			# Based On omitted from items — cannot compute batch_yield from it
			return
		return _original(doc)

	chem_se.cal_target_yield_cons = cal_target_yield_cons
	chem_se._valence_cal_target_yield_safe_patched = True


def _is_based_on_item_optional() -> bool:
	try:
		return cint(
			frappe.db.get_single_value("Manufacturing Settings", "custom_based_on_item_optional") or 0
		)
	except Exception:
		return False


def _has_any_item_row(doc) -> bool:
	for row in doc.get("items") or []:
		if row.get("item_code"):
			return True
	return False


def _item_on_stock_entry(doc, item_code: str) -> bool:
	for row in doc.get("items") or []:
		if row.get("item_code") == item_code:
			return True
	return False


def after_migrate():
	ensure_based_on_item_optional_field()
	frappe.clear_cache()
