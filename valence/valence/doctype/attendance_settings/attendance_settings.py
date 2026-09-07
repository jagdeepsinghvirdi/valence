# Copyright (c) 2025, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

DEFAULT_COMP_OFF_RULES = [
	{"attendance_code": "PWO", "comp_off_days": 1.0, "enabled": 1},
	{"attendance_code": "PAW", "comp_off_days": 0.5, "enabled": 1},
	{"attendance_code": "2PWO", "comp_off_days": 2.0, "enabled": 1},
	{"attendance_code": "2PAW", "comp_off_days": 1.5, "enabled": 1},
	{"attendance_code": "HP", "comp_off_days": 1.0, "enabled": 1},
	{"attendance_code": "HP/A", "comp_off_days": 0.5, "enabled": 1},
	{"attendance_code": "2HP", "comp_off_days": 2.0, "enabled": 1},
	{"attendance_code": "2HP/A", "comp_off_days": 1.5, "enabled": 1},
	{"attendance_code": "2P", "comp_off_days": 1.0, "enabled": 1},
	{"attendance_code": "2P/A", "comp_off_days": 0.5, "enabled": 1},
]


class AttendanceSettings(Document):
	def validate(self):
		self.validate_comp_off_settings()

	def validate_comp_off_settings(self):
		if self.comp_off_enabled and not self.comp_off_leave_type:
			frappe.throw(frappe._("Comp Off Leave Type is mandatory when Comp Off Earning is enabled."))

		seen_codes = set()
		for rule in self.get("comp_off_rules") or []:
			comp_off_days = rule.get("comp_off_days") if isinstance(rule, dict) else getattr(rule, "comp_off_days", 0.0)
			attendance_code = rule.get("attendance_code") if isinstance(rule, dict) else getattr(rule, "attendance_code", None)
			if flt(comp_off_days) < 0:
				frappe.throw(
					frappe._("Comp Off Days cannot be negative for attendance code {0}.").format(
						attendance_code
					)
				)
			if attendance_code:
				if attendance_code in seen_codes:
					frappe.throw(
						frappe._("Duplicate Comp Off Rule for attendance code {0}.").format(
							attendance_code
						)
					)
				seen_codes.add(attendance_code)

	def set_default_comp_off_rules(self):
		"""Helper to initialize default rules on fresh setup without overwriting intentional empties."""
		if not self.get("comp_off_rules"):
			for rule in DEFAULT_COMP_OFF_RULES:
				self.append("comp_off_rules", rule)
