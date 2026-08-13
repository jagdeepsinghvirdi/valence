"""Chemical Stock Entry based-on validation — skip when items already exist.

Chemical default:
  Based on Item <item> Required in Raw Materials

Valence rule:
  - If the Stock Entry has at least one item row with item_code → skip based-on check
    (save allowed without Based On item in raw materials).
  - If items are empty → keep chemical behaviour.

Manufacturing Settings → Make Based On Item Optional still skips the check entirely.
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
						"already has at least one item row; otherwise chemical default applies."
					),
					"module": "Valence",
				}
			]
		},
		ignore_validate=True,
		update=True,
	)


def apply_based_on_item_optional_patch():
	"""Wrap chemical check_based_on_item so Based On is optional when items exist."""
	try:
		from chemical.chemical.override.doc_event import stock_entry as chem_se
	except ImportError:
		return

	# Bump flag when wrapper logic changes
	if getattr(chem_se, "_valence_based_on_any_item_patched", False):
		return

	if not hasattr(chem_se, "check_based_on_item"):
		return

	_original = chem_se.check_based_on_item

	def check_based_on_item(doc):
		if _is_based_on_item_optional():
			return
		# Any item line present → do not require Based On item in raw materials
		if _has_any_item_row(doc):
			return
		return _original(doc)

	chem_se.check_based_on_item = check_based_on_item
	chem_se._valence_based_on_any_item_patched = True
	chem_se._valence_based_on_consumption_patched = True
	chem_se._valence_based_on_optional_patched = True


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


def after_migrate():
	ensure_based_on_item_optional_field()
	frappe.clear_cache()
