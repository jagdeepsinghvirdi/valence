# Copyright (c) 2026, finbyz tech and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, nowdate

from valence.valence.attendance_code import get_attendance_code
from valence.valence.doctype.attendance_settings.attendance_settings import (
	DEFAULT_COMP_OFF_RULES,
)
from valence.valence.tasks.comp_off_earning import (
	_match_comp_off_rule,
	get_attendance_comp_off_entries,
	get_comp_off_earned,
	get_comp_off_leave_type,
	process_comp_off_earning,
	process_comp_off_for_attendance,
	reverse_comp_off_for_attendance,
	run_daily_comp_off_earning,
)


class TestCompOffEarningUnit(unittest.TestCase):
	"""Pure unit tests for comp off rule matching and get_comp_off_earned."""

	def test_rule_matching_enabled_codes(self):
		"""E1-E10: Verify rule matching for all 10 enabled codes."""
		rules = DEFAULT_COMP_OFF_RULES
		self.assertEqual(_match_comp_off_rule("PWO", rules, 1), 1.0)
		self.assertEqual(_match_comp_off_rule("PAW", rules, 1), 0.5)
		self.assertEqual(_match_comp_off_rule("2PWO", rules, 1), 2.0)
		self.assertEqual(_match_comp_off_rule("2PAW", rules, 1), 1.5)
		self.assertEqual(_match_comp_off_rule("HP", rules, 1), 1.0)
		self.assertEqual(_match_comp_off_rule("HP/A", rules, 1), 0.5)
		self.assertEqual(_match_comp_off_rule("2HP", rules, 1), 2.0)
		self.assertEqual(_match_comp_off_rule("2HP/A", rules, 1), 1.5)
		self.assertEqual(_match_comp_off_rule("2P", rules, 1), 1.0)
		self.assertEqual(_match_comp_off_rule("2P/A", rules, 1), 0.5)

	def test_rule_matching_explicitly_disabled_code(self):
		"""E20: Explicitly disabled rule (enabled = 0) returns 0.0."""
		custom_rules = [
			{"attendance_code": "2P", "comp_off_days": 1.0, "enabled": 0},
			{"attendance_code": "PWO", "comp_off_days": 1.0, "enabled": 0},
		]
		self.assertEqual(_match_comp_off_rule("2P", custom_rules, 1), 0.0)
		self.assertEqual(_match_comp_off_rule("PWO", custom_rules, 1), 0.0)

	def test_rule_matching_non_qualifying_codes(self):
		"""E11-E17: Non-qualifying codes (P, A, WO, H, TT, P/A, leaves) return 0.0."""
		rules = DEFAULT_COMP_OFF_RULES
		for non_qualifying in ("P", "A", "WO", "H", "TT", "P/A", "A/P", "CL", "SL", "EL", "L/L", None, ""):
			self.assertEqual(_match_comp_off_rule(non_qualifying, rules, 1), 0.0)

	def test_rule_matching_when_setting_disabled(self):
		"""E19: Global comp_off_enabled = 0 disables earning."""
		rules = DEFAULT_COMP_OFF_RULES
		self.assertEqual(_match_comp_off_rule("PWO", rules, 0), 0.0)
		self.assertEqual(_match_comp_off_rule("2PWO", rules, 0), 0.0)

	@patch("valence.valence.tasks.comp_off_earning.get_attendance_code")
	@patch("frappe.db.get_single_value")
	@patch("frappe.get_single")
	def test_get_comp_off_earned_disabled_setting(self, mock_get_single, mock_db_value, mock_get_code):
		"""E19: get_comp_off_earned returns 0.0 immediately when setting disabled."""
		mock_db_value.return_value = 0
		res = get_comp_off_earned({"status": "Present", "working_hours": 8})
		self.assertEqual(res, 0.0)
		mock_get_code.assert_not_called()

	@patch("valence.valence.tasks.comp_off_earning.get_attendance_code")
	@patch("frappe.db.get_single_value")
	@patch("frappe.get_single")
	def test_get_comp_off_earned_qualifying(self, mock_get_single, mock_db_value, mock_get_code):
		"""E1: get_comp_off_earned returns matching rule days for qualifying code."""
		mock_db_value.return_value = 1
		mock_get_code.return_value = "PWO"
		settings_mock = unittest.mock.MagicMock()
		settings_mock.get.return_value = DEFAULT_COMP_OFF_RULES
		mock_get_single.return_value = settings_mock

		res = get_comp_off_earned({"status": "Present", "working_hours": 8})
		self.assertEqual(res, 1.0)

	def test_on_duty_and_wfh_codes(self):
		"""E18: OD / WFH on normal day derives P/0.0, but on Weekly Off/Holiday earns Comp Off."""
		# Normal day OD / WFH -> P -> 0.0 Comp Off
		wfh_normal = {"status": "Work From Home", "working_hours": 8.0}
		self.assertEqual(get_attendance_code(wfh_normal, context={"day_type": "Normal"}), "P")
		self.assertEqual(_match_comp_off_rule("P", DEFAULT_COMP_OFF_RULES, 1), 0.0)

		# Weekly Off WFH full day -> PWO -> 1.0 Comp Off
		wfh_wo = {"status": "Work From Home", "working_hours": 8.0}
		self.assertEqual(get_attendance_code(wfh_wo, context={"day_type": "Weekly Off"}), "PWO")
		self.assertEqual(_match_comp_off_rule("PWO", DEFAULT_COMP_OFF_RULES, 1), 1.0)

		# Holiday OD half day -> HP/A -> 0.5 Comp Off
		od_holiday = {"status": "On Duty", "working_hours": 4.0}
		self.assertEqual(get_attendance_code(od_holiday, context={"day_type": "Holiday"}), "HP/A")
		self.assertEqual(_match_comp_off_rule("HP/A", DEFAULT_COMP_OFF_RULES, 1), 0.5)

	def test_custom_rule_comp_off_days(self):
		"""E21: Custom comp_off_days in configured rules is respected."""
		custom_rules = [
			{"attendance_code": "PWO", "comp_off_days": 1.5, "enabled": 1},
			{"attendance_code": "PAW", "comp_off_days": 0.75, "enabled": 1},
		]
		self.assertEqual(_match_comp_off_rule("PWO", custom_rules, 1), 1.5)
		self.assertEqual(_match_comp_off_rule("PAW", custom_rules, 1), 0.75)


class TestCompOffEarningIntegration(FrappeTestCase):
	"""Database integration tests using Frappe test framework."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.leave_type = cls._ensure_leave_type("Compensatory Off")
		cls.employee, cls.company = cls._ensure_employee()
		cls._configure_attendance_settings()

	@classmethod
	def _ensure_leave_type(cls, name):
		if not frappe.db.exists("Leave Type", name):
			doc = frappe.get_doc(
				{
					"doctype": "Leave Type",
					"leave_type_name": name,
					"is_compensatory": 1,
					"include_holiday": 1,
				}
			)
			doc.insert(ignore_permissions=True)
		return name

	@classmethod
	def _ensure_employee(cls, emp_name="TEST-COMP-OFF-EMP"):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			company = "Test Comp Off Company"
			if not frappe.db.exists("Company", company):
				c = frappe.get_doc(
					{
						"doctype": "Company",
						"company_name": company,
						"default_currency": "INR",
						"country": "India",
					}
				)
				c.insert(ignore_permissions=True)

		existing = frappe.db.get_value("Employee", {"name": emp_name}, ["name", "company"], as_dict=True)
		if existing:
			return existing.name, existing.company

		emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Test",
				"last_name": emp_name.replace("TEST-", ""),
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"company": company,
				"status": "Active",
				"date_of_joining": "2020-01-01",
			}
		)
		emp.insert(ignore_permissions=True)
		return emp.name, company

	@classmethod
	def _configure_attendance_settings(cls):
		if frappe.db.exists("DocType", "Attendance Settings"):
			settings = frappe.get_single("Attendance Settings")
			if not settings.leave_creation_window_days:
				settings.leave_creation_window_days = 3
			if not settings.super_hod_working_days_threshold:
				settings.super_hod_working_days_threshold = 3
			if not settings.short_leave_max_duration_hours:
				settings.short_leave_max_duration_hours = 2.0
			if not settings.short_leave_personal_monthly_cap:
				settings.short_leave_personal_monthly_cap = 2
			if not settings.offday_full_day_hours:
				settings.offday_full_day_hours = 6.0

			settings.comp_off_enabled = 1
			settings.comp_off_auto_credit = 1
			settings.comp_off_leave_type = cls.leave_type
			settings.comp_off_rules = []
			for r in DEFAULT_COMP_OFF_RULES:
				settings.append("comp_off_rules", r)
			settings.save(ignore_permissions=True)

	def _make_submitted_attendance(self, att_date, status="Present", hours=8.0, employee=None):
		emp = employee or self.employee
		existing = frappe.db.get_value("Attendance", {"employee": emp, "attendance_date": att_date}, "name")
		if existing:
			frappe.delete_doc("Attendance", existing, force=1, ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": emp,
				"attendance_date": att_date,
				"status": status,
				"working_hours": hours,
				"company": self.company,
				"docstatus": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_comp_off_leave_type_validation(self):
		"""E22: Ensures strict leave type configuration with no silent fallbacks."""
		frappe.db.set_single_value("Attendance Settings", "comp_off_leave_type", "")
		with self.assertRaises(frappe.ValidationError):
			get_comp_off_leave_type()

		frappe.db.set_single_value("Attendance Settings", "comp_off_leave_type", "Non Existent Leave Type 99")
		with self.assertRaises(frappe.ValidationError):
			get_comp_off_leave_type()

		# Ensure AttendanceSettings document validation also enforces comp_off_leave_type when enabled
		settings = frappe.get_single("Attendance Settings")
		settings.comp_off_enabled = 1
		settings.comp_off_leave_type = ""
		with self.assertRaises(frappe.ValidationError):
			settings.validate()

		# Restore
		settings.comp_off_leave_type = self.leave_type
		settings.validate()
		frappe.db.set_single_value("Attendance Settings", "comp_off_leave_type", self.leave_type)
		self.assertEqual(get_comp_off_leave_type(), self.leave_type)

	def test_automatic_allocation_and_ledger_credit(self):
		"""E23, E24, E25: Qualifying attendance auto-creates Leave Allocation and posts positive Leave Ledger Entry."""
		att_date = add_days(nowdate(), -50)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		# Mock attendance code to PWO
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		# Verify Leave Ledger Entry
		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		self.assertEqual(flt(entries[0].leaves), 1.0)
		self.assertEqual(entries[0].transaction_type, "Leave Allocation")
		self.assertEqual(entries[0].get("custom_attendance"), att.name)

		# Verify Leave Allocation
		alloc_name = entries[0].transaction_name
		self.assertTrue(bool(alloc_name))
		alloc = frappe.get_doc("Leave Allocation", alloc_name)
		self.assertGreaterEqual(flt(alloc.total_leaves_allocated), 1.0)

	def test_audit_comment_on_leave_allocation(self):
		"""E26: Audit comment is added to the linked Leave Allocation on credit."""
		att_date = add_days(nowdate(), -60)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		alloc_name = entries[0].transaction_name

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Leave Allocation", "reference_name": alloc_name},
			fields=["content"],
		)
		self.assertTrue(any(att.name in c.get("content", "") for c in comments))

	def test_comp_off_idempotency(self):
		"""E27: Processing the same attendance multiple times must not duplicate ledger entries."""
		att_date = add_days(nowdate(), -51)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)
			process_comp_off_for_attendance(att.name)
			process_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		self.assertEqual(flt(entries[0].leaves), 1.0)

	def test_reprocessing_on_attendance_change(self):
		"""E28: Amending an attendance code from PAW (0.5) to 2PWO (2.0) reverses 0.5 and credits 2.0."""
		att_date = add_days(nowdate(), -52)
		att = self._make_submitted_attendance(att_date, status="Present", hours=4.0)

		# Initial credit: PAW -> 0.5
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PAW"):
			process_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		self.assertEqual(flt(entries[0].leaves), 0.5)
		alloc_name = entries[0].transaction_name

		# Reprocess: changed to 2PWO -> 2.0
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="2PWO"):
			process_comp_off_for_attendance(att.name)

		entries_after = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		# 1 initial (+0.5), 1 reversal (-0.5), 1 new credit (+2.0) -> total 3 entries, net sum = 2.0
		self.assertEqual(len(entries_after), 3)
		net_sum = sum(flt(e.leaves) for e in entries_after)
		self.assertEqual(net_sum, 2.0)

	def test_reprocessing_to_non_qualifying_code(self):
		"""E29: Changing qualifying Attendance to non-qualifying code reverses credit completely."""
		att_date = add_days(nowdate(), -61)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		# Initial credit: PWO -> 1.0
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		alloc_name = entries[0].transaction_name
		alloc_doc = frappe.get_doc("Leave Allocation", alloc_name)
		initial_total = flt(alloc_doc.total_leaves_allocated)

		# Reprocess to regular P -> 0.0 Comp Off
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="P"):
			process_comp_off_for_attendance(att.name)

		entries_after = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries_after), 2)  # 1 initial +1.0, 1 reversal -1.0
		self.assertEqual(sum(flt(e.leaves) for e in entries_after), 0.0)

		alloc_after = frappe.get_doc("Leave Allocation", alloc_name)
		self.assertEqual(flt(alloc_after.total_leaves_allocated), initial_total - 1.0)

	def test_reversal_on_cancellation(self):
		"""E30: Cancelling attendance must post offsetting negative ledger entry and decrement allocation."""
		att_date = add_days(nowdate(), -53)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries), 1)
		alloc_name = entries[0].transaction_name
		alloc_before = frappe.get_doc("Leave Allocation", alloc_name)
		initial_total = flt(alloc_before.total_leaves_allocated)

		# Cancel attendance
		reverse_comp_off_for_attendance(att.name)

		entries_after = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(entries_after), 2)
		net_sum = sum(flt(e.leaves) for e in entries_after)
		self.assertEqual(net_sum, 0.0)

		alloc_after = frappe.get_doc("Leave Allocation", alloc_name)
		self.assertEqual(flt(alloc_after.total_leaves_allocated), initial_total - 1.0)

	def test_historical_leave_type_reversal(self):
		"""E33: Reversal must use the historical leave type from the ledger even if settings change."""
		att_date = add_days(nowdate(), -54)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		# Change setting to something else or blank
		frappe.db.set_single_value("Attendance Settings", "comp_off_leave_type", "")

		# Reversal should still succeed using historical entry
		reverse_comp_off_for_attendance(att.name)

		entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		net_sum = sum(flt(e.leaves) for e in entries)
		self.assertEqual(net_sum, 0.0)

		# Restore setting
		frappe.db.set_single_value("Attendance Settings", "comp_off_leave_type", self.leave_type)

	def test_unrelated_ledger_entry_isolation(self):
		"""E31: Unrelated Leave Ledger Entry on the same date is NOT affected by Comp Off reversal."""
		att_date = add_days(nowdate(), -55)
		att = self._make_submitted_attendance(att_date, status="Present", hours=8.0)

		# Credit Comp Off
		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att.name)

		comp_off_entries = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(comp_off_entries), 1)
		alloc_name = comp_off_entries[0].transaction_name

		# Create an unrelated manual / other ledger entry on the exact same date
		unrelated_entry = frappe.get_doc(
			{
				"doctype": "Leave Ledger Entry",
				"employee": self.employee,
				"employee_name": "Test Comp Off",
				"leave_type": self.leave_type,
				"transaction_type": "Leave Allocation",
				"transaction_name": alloc_name,
				"company": self.company,
				"leaves": 5.0,
				"from_date": att_date,
				"to_date": att_date,
				"is_carry_forward": 0,
				"is_expired": 0,
			}
		)
		unrelated_entry.insert(ignore_permissions=True)
		unrelated_entry.submit()

		# Reverse Comp Off for the attendance
		reverse_comp_off_for_attendance(att.name)

		# Comp Off entries for this attendance must be net 0
		comp_off_after = get_attendance_comp_off_entries(att.name, self.employee, att_date, self.leave_type)
		self.assertEqual(len(comp_off_after), 2)
		self.assertEqual(sum(flt(e.leaves) for e in comp_off_after), 0.0)

		# The unrelated entry must still exist and remain untouched
		unrelated_doc = frappe.get_doc("Leave Ledger Entry", unrelated_entry.name)
		self.assertEqual(unrelated_doc.docstatus, 1)
		self.assertEqual(flt(unrelated_doc.leaves), 5.0)

	def test_distinct_attendance_identities_no_collision(self):
		"""E32: Two distinct Attendance records maintain independent ledger entries and reversals."""
		att_date1 = add_days(nowdate(), -56)
		att_date2 = add_days(nowdate(), -57)
		att1 = self._make_submitted_attendance(att_date1, status="Present", hours=8.0)
		att2 = self._make_submitted_attendance(att_date2, status="Present", hours=4.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(att1.name)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PAW"):
			process_comp_off_for_attendance(att2.name)

		entries1 = get_attendance_comp_off_entries(att1.name, self.employee, att_date1, self.leave_type)
		entries2 = get_attendance_comp_off_entries(att2.name, self.employee, att_date2, self.leave_type)
		self.assertEqual(sum(flt(e.leaves) for e in entries1), 1.0)
		self.assertEqual(sum(flt(e.leaves) for e in entries2), 0.5)

		# Reverse att1 only
		reverse_comp_off_for_attendance(att1.name)

		entries1_after = get_attendance_comp_off_entries(att1.name, self.employee, att_date1, self.leave_type)
		entries2_after = get_attendance_comp_off_entries(att2.name, self.employee, att_date2, self.leave_type)

		self.assertEqual(sum(flt(e.leaves) for e in entries1_after), 0.0)
		self.assertEqual(sum(flt(e.leaves) for e in entries2_after), 0.5)

	def test_batch_processing_date_range(self):
		"""E34: Date-range batch processing processes all qualifying submitted Attendance records."""
		d1 = add_days(nowdate(), -65)
		d2 = add_days(nowdate(), -64)
		d3 = add_days(nowdate(), -63)
		att1 = self._make_submitted_attendance(d1, status="Present", hours=8.0)
		att2 = self._make_submitted_attendance(d2, status="Present", hours=8.0)
		att3 = self._make_submitted_attendance(d3, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			res = process_comp_off_earning(from_date=d1, to_date=d3, employee=self.employee)

		self.assertGreaterEqual(res.get("processed", 0), 3)
		for att in (att1, att2, att3):
			entries = get_attendance_comp_off_entries(att.name, self.employee, att.attendance_date, self.leave_type)
			self.assertEqual(sum(flt(e.leaves) for e in entries), 1.0)

	def test_batch_processing_employee_filter(self):
		"""E35: Employee filter processes only the requested employee."""
		emp2, _ = self._ensure_employee("TEST-COMP-OFF-EMP2")
		d = add_days(nowdate(), -66)
		att1 = self._make_submitted_attendance(d, status="Present", hours=8.0, employee=self.employee)
		att2 = self._make_submitted_attendance(d, status="Present", hours=8.0, employee=emp2)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_earning(from_date=d, to_date=d, employee=self.employee)

		entries1 = get_attendance_comp_off_entries(att1.name, self.employee, d, self.leave_type)
		entries2 = get_attendance_comp_off_entries(att2.name, emp2, d, self.leave_type)

		self.assertEqual(sum(flt(e.leaves) for e in entries1), 1.0)
		self.assertEqual(sum(flt(e.leaves) for e in entries2), 0.0)

	def test_draft_attendance_does_not_earn_comp_off(self):
		"""E36: Draft Attendance (docstatus = 0) does not earn Comp Off."""
		d = add_days(nowdate(), -67)
		existing = frappe.db.get_value("Attendance", {"employee": self.employee, "attendance_date": d}, "name")
		if existing:
			frappe.delete_doc("Attendance", existing, force=1, ignore_permissions=True)

		draft_att = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": self.employee,
				"attendance_date": d,
				"status": "Present",
				"working_hours": 8.0,
				"company": self.company,
				"docstatus": 0,
			}
		)
		draft_att.insert(ignore_permissions=True)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			process_comp_off_for_attendance(draft_att.name)

		entries = get_attendance_comp_off_entries(draft_att.name, self.employee, d, self.leave_type)
		self.assertEqual(entries, [])

	def test_run_daily_comp_off_earning_processes_yesterday(self):
		"""E37: run_daily_comp_off_earning() processes the intended previous-day Attendance."""
		yesterday = add_days(nowdate(), -1)
		att = self._make_submitted_attendance(yesterday, status="Present", hours=8.0)

		with patch("valence.valence.tasks.comp_off_earning.get_attendance_code", return_value="PWO"):
			run_daily_comp_off_earning()

		entries = get_attendance_comp_off_entries(att.name, self.employee, yesterday, self.leave_type)
		self.assertEqual(sum(flt(e.leaves) for e in entries), 1.0)


def run():
	"""Runner function for unit and integration checks."""
	suite = unittest.TestSuite()
	suite.addTest(unittest.makeSuite(TestCompOffEarningUnit))
	suite.addTest(unittest.makeSuite(TestCompOffEarningIntegration))
	runner = unittest.TextTestRunner(verbosity=2)
	result = runner.run(suite)
	return len(result.failures) + len(result.errors)
