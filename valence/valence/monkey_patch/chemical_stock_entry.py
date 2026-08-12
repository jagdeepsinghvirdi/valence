"""Optional bypass for chemical Stock Entry based-on raw-material validation.

Chemical validates on SE save:
  Based on Item <item> Required in Raw Materials
(see chemical.chemical.override.doc_event.stock_entry.check_based_on_item)

Manufacturing Settings → Make Based On Item Optional (custom_based_on_item_optional)
skips that check so the entry can still be saved when process allows it.
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
						"If enabled, Stock Entry can be saved even when the Yield Based On item "
						"is missing from raw materials (skips chemical based-on validation)."
					),
					"module": "Valence",
				}
			]
		},
		ignore_validate=True,
		update=True,
	)


def apply_based_on_item_optional_patch():
	"""Wrap chemical check_based_on_item so the Manufacturing Settings flag is respected."""
	try:
		from chemical.chemical.override.doc_event import stock_entry as chem_se
	except ImportError:
		return

	if getattr(chem_se, "_valence_based_on_optional_patched", False):
		return

	if not hasattr(chem_se, "check_based_on_item"):
		return

	_original = chem_se.check_based_on_item

	def check_based_on_item(doc):
		if _is_based_on_item_optional():
			return
		return _original(doc)

	chem_se.check_based_on_item = check_based_on_item
	chem_se._valence_based_on_optional_patched = True


def _is_based_on_item_optional() -> bool:
	try:
		return cint(
			frappe.db.get_single_value("Manufacturing Settings", "custom_based_on_item_optional") or 0
		)
	except Exception:
		# Field not migrated yet, or transient DB error — keep chemical rule strict
		return False


def after_migrate():
	ensure_based_on_item_optional_field()
	frappe.clear_cache()
