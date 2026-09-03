# Copyright (c) 2025, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

DEFAULT_COMP_OFF_RULES = [
	{"attendance_code": "PWO", "comp_off_days": 1.0, "enabled": 1},
	{"attendance_code": "PAW", "comp_off_days": 0.5, "enabled": 1},
	{"attendance_code": "2PWO", "comp_off_days": 2.0, "enabled": 1},
	{"attendance_code": "2PAW", "comp_off_days": 1.5, "enabled": 1},
	{"attendance_code": "HP", "comp_off_days": 1.0, "enabled": 1},
	{"attendance_code": "HP/A", "comp_off_days": 0.5, "enabled": 1},
	{"attendance_code": "2HP", "comp_off_days": 2.0, "enabled": 1},
	{"attendance_code": "2HP/A", "comp_off_days": 1.5, "enabled": 1},
	{"attendance_code": "2P", "comp_off_days": 1.0, "enabled": 0},
	{"attendance_code": "2P/A", "comp_off_days": 0.5, "enabled": 0},
]


class AttendanceSettings(Document):
	def validate(self):
		self.validate_comp_off_settings()

	def validate_comp_off_settings(self):
		if self.comp_off_enabled and not self.comp_off_leave_type:
			frappe.throw(frappe._("Comp Off Leave Type is mandatory when Comp Off Earning is enabled."))

		if not self.get("comp_off_rules"):
			for rule in DEFAULT_COMP_OFF_RULES:
				self.append("comp_off_rules", rule)
