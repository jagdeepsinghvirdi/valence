# Copyright (c) 2026, finbyz tech and contributors
# For license information, please see license.txt

import unittest

import frappe
from frappe.permissions import add_user_permission
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from valence.valence.doctype.attendance_settings.attendance_settings import (
	DEFAULT_COMP_OFF_RULES,
)
from valence.valence.doc_events.comp_off_usage import (
	get_comp_off_balance,
	get_comp_off_statement,
	validate_comp_off_application,
)
from valence.valence.report.comp_off_balance.comp_off_balance import (
	execute as execute_comp_off_balance_report,
)


class TestCompOffUsage(FrappeTestCase):
	"""Integration and unit tests for Comp Off usage, validation, and reporting."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

		cls.leave_type = cls._ensure_leave_type("Compensatory Off")
		cls.company = cls._ensure_company("Test Comp Off Company")

		cls.employee_user = cls._ensure_user("test_comp_off_employee@example.com", "Test", "Employee", ["Employee"])
		cls.hr_manager_user = cls._ensure_user("test_comp_off_hr_mgr@example.com", "Test", "HRMgr", ["Employee", "HR Manager"])

		cls.employee, _ = cls._ensure_employee("TEST-COMP-OFF-USER", cls.company, user_id=cls.employee_user)
		cls.other_employee, _ = cls._ensure_employee("TEST-COMP-OFF-OTHER", cls.company)

		# Ensure user permissions are cleanly assigned
		frappe.db.delete("User Permission", {"user": cls.employee_user})
		add_user_permission("Employee", cls.employee, cls.employee_user)

		cls.holiday_list = cls._ensure_holiday_list("Test Comp Off Usage HL")
		frappe.db.set_value("Employee", cls.employee, "holiday_list", cls.holiday_list)
		frappe.db.set_value("Employee", cls.other_employee, "holiday_list", cls.holiday_list)

		cls._configure_attendance_settings()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self._clear_records(self.employee)
		self._clear_records(self.other_employee)
		self._configure_attendance_settings()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._clear_records(self.employee)
		self._clear_records(self.other_employee)
		super().tearDown()

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
	def _ensure_company(cls, company_name):
		if not frappe.db.exists("Company", company_name):
			c = frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": company_name,
					"default_currency": "INR",
					"country": "India",
				}
			)
			c.insert(ignore_permissions=True)
		return company_name

	@classmethod
	def _ensure_employee(cls, emp_id, company, user_id=None):
		existing = None
		if user_id:
			existing = frappe.db.get_value("Employee", {"user_id": user_id}, ["name", "company"], as_dict=True)
		if not existing:
			existing = frappe.db.get_value("Employee", {"first_name": emp_id}, ["name", "company"], as_dict=True)
		if not existing:
			existing = frappe.db.get_value("Employee", {"last_name": emp_id}, ["name", "company"], as_dict=True)
		if existing:
			if user_id:
				frappe.db.set_value("Employee", existing.name, "user_id", user_id)
			return existing.name, existing.company

		emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": emp_id,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"company": company,
				"status": "Active",
				"date_of_joining": "2020-01-01",
				"user_id": user_id,
			}
		)
		emp.flags.ignore_mandatory = True
		emp.insert(ignore_permissions=True)
		return emp.name, company

	@classmethod
	def _ensure_user(cls, email, first, last, roles):
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first,
					"last_name": last,
					"send_welcome_email": 0,
					"new_password": "TestPassword@123",
					"user_type": "System User",
				}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", email)
			user.enabled = 1
			user.save(ignore_permissions=True)

		user = frappe.get_doc("User", email)
		for r in ("System Manager", "HR Manager", "HR User", "Administrator", "Super HOD"):
			if r not in roles:
				user.remove_roles(r)
		for r in roles:
			user.add_roles(r)
		frappe.db.commit()
		return email

	@classmethod
	def _ensure_holiday_list(cls, hl_name):
		if frappe.db.exists("Holiday List", hl_name):
			frappe.delete_doc("Holiday List", hl_name, force=1, ignore_permissions=True)

		hl = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": hl_name,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
			}
		)
		# 2026-06-07 is Sunday (Weekly Off)
		hl.append("holidays", {"holiday_date": "2026-06-07", "description": "Sunday Weekly Off", "weekly_off": 1})
		# 2026-06-10 is Wednesday (Public Holiday)
		hl.append("holidays", {"holiday_date": "2026-06-10", "description": "Public Holiday", "weekly_off": 0})
		# 2026-06-14 is Sunday (Weekly Off)
		hl.append("holidays", {"holiday_date": "2026-06-14", "description": "Sunday Weekly Off", "weekly_off": 1})

		hl.insert(ignore_permissions=True)
		return hl_name

	@classmethod
	def _configure_attendance_settings(cls):
		if frappe.db.exists("DocType", "Attendance Settings"):
			settings = frappe.get_single("Attendance Settings")
			settings.comp_off_enabled = 1
			settings.comp_off_leave_type = cls.leave_type
			settings.comp_off_rules = []
			for r in DEFAULT_COMP_OFF_RULES:
				settings.append("comp_off_rules", r)
			settings.save(ignore_permissions=True)

	@classmethod
	def _clear_records(cls, employee):
		frappe.db.delete("Leave Ledger Entry", {"employee": employee})
		frappe.db.delete("Leave Application", {"employee": employee})
		frappe.db.delete("Leave Allocation", {"employee": employee})
		frappe.db.commit()

	def _credit_comp_off(self, employee, leaves=2.0, from_date="2026-01-01", to_date="2026-12-31", entry_date="2026-06-01"):
		"""Allocate and credit Comp Off leaves to an employee."""
		alloc_name = frappe.db.get_value(
			"Leave Allocation",
			{"employee": employee, "leave_type": self.leave_type, "docstatus": 1},
			"name",
		)
		if not alloc_name:
			alloc = frappe.get_doc(
				{
					"doctype": "Leave Allocation",
					"employee": employee,
					"leave_type": self.leave_type,
					"company": self.company,
					"from_date": from_date,
					"to_date": to_date,
					"new_leaves_allocated": 0,
					"total_leaves_allocated": 0,
					"docstatus": 1,
				}
			)
			alloc.flags.ignore_validate = True
			alloc.insert(ignore_permissions=True)
			alloc_name = alloc.name
			frappe.db.delete("Leave Ledger Entry", {"transaction_name": alloc_name, "leaves": 0})

		alloc = frappe.get_doc("Leave Allocation", alloc_name)
		alloc.db_set("total_leaves_allocated", flt(alloc.total_leaves_allocated) + flt(leaves), update_modified=False)

		credit = frappe.get_doc(
			{
				"doctype": "Leave Ledger Entry",
				"employee": employee,
				"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
				"leave_type": self.leave_type,
				"transaction_type": "Leave Allocation",
				"transaction_name": alloc_name,
				"company": self.company,
				"leaves": flt(leaves),
				"from_date": entry_date,
				"to_date": to_date,
				"is_carry_forward": 0,
				"is_expired": 0,
				"docstatus": 1,
			}
		)
		credit.insert(ignore_permissions=True)
		return alloc_name

	def _make_leave_application(self, from_date, to_date, half_day=0, half_day_date=None, employee=None, submit=False):
		"""Create a Leave Application for testing."""
		emp = employee or self.employee
		prev_present = getattr(frappe.flags, "ignore_present_day_leave_restriction", False)
		prev_window = getattr(frappe.flags, "ignore_leave_creation_window", False)
		frappe.flags.ignore_present_day_leave_restriction = True
		frappe.flags.ignore_leave_creation_window = True

		try:
			doc = frappe.get_doc(
				{
					"doctype": "Leave Application",
					"employee": emp,
					"leave_type": self.leave_type,
					"from_date": from_date,
					"to_date": to_date,
					"half_day": half_day,
					"half_day_date": half_day_date or (from_date if half_day else None),
					"status": "Approved",
					"company": self.company,
					"follow_via_email": 0,
				}
			)
			if submit:
				doc.insert(ignore_permissions=True)
				doc.submit()
			return doc
		finally:
			frappe.flags.ignore_present_day_leave_restriction = prev_present
			frappe.flags.ignore_leave_creation_window = prev_window

	# 1. Full-day usage
	def test_full_day_usage(self):
		"""1. Full-day usage: 1 working day Comp Off correctly validates and deducts 1.0 day balance."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-05")), 2.0)

		# 2026-06-08 is a Monday (working day)
		doc = self._make_leave_application("2026-06-08", "2026-06-08")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 1.0)

		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 1.0)

	# 2. Half-day usage
	def test_half_day_usage(self):
		"""2. Half-day usage: half-day Comp Off validates and deducts 0.5 day from balance."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")

		doc = self._make_leave_application("2026-06-08", "2026-06-08", half_day=1, half_day_date="2026-06-08")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 0.5)

		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 1.5)

	# 3. Insufficient balance
	def test_insufficient_balance(self):
		"""3. Insufficient balance: applying for more days than available throws ValidationError."""
		self._credit_comp_off(self.employee, leaves=1.0, entry_date="2026-06-01")

		# 2 working days requested (Monday 2026-06-08 and Tuesday 2026-06-09)
		doc = self._make_leave_application("2026-06-08", "2026-06-09")
		with self.assertRaises(frappe.ValidationError) as cm:
			validate_comp_off_application(doc)
		self.assertIn("Insufficient Comp Off balance", str(cm.exception))

	# 4. Zero balance
	def test_zero_balance(self):
		"""4. Zero balance: applying when balance is 0.0 throws ValidationError."""
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-05")), 0.0)

		doc = self._make_leave_application("2026-06-08", "2026-06-08")
		with self.assertRaises(frappe.ValidationError) as cm:
			validate_comp_off_application(doc)
		self.assertIn("Insufficient Comp Off balance", str(cm.exception))

	# 5. Exact balance
	def test_exact_balance(self):
		"""5. Exact balance: applying for exactly the available balance succeeds and leaves 0.0 balance."""
		self._credit_comp_off(self.employee, leaves=1.0, entry_date="2026-06-01")

		doc = self._make_leave_application("2026-06-08", "2026-06-08")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 1.0)

		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 0.0)

	# 6. Cancellation reversal
	def test_cancellation_reversal(self):
		"""6. Cancellation reversal: cancelling a submitted Comp Off restores the deducted balance."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")

		doc = self._make_leave_application("2026-06-08", "2026-06-08", submit=True)
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 1.0)

		doc.cancel()
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 2.0)

	# 7. Comp Off on Weekly Off (no deduction)
	def test_comp_off_on_weekly_off_no_deduction(self):
		"""7. Comp Off on Weekly Off: applying on a Weekly Off results in 0.0 total_leave_days."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")

		# 2026-06-07 is configured as Sunday Weekly Off in Holiday List
		doc = self._make_leave_application("2026-06-07", "2026-06-07")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 0.0)

	# 8. Comp Off on Holiday (no deduction)
	def test_comp_off_on_holiday_no_deduction(self):
		"""8. Comp Off on Holiday: applying on a Public Holiday results in 0.0 total_leave_days."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")

		# 2026-06-10 is configured as Public Holiday in Holiday List
		doc = self._make_leave_application("2026-06-10", "2026-06-10")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 0.0)

	# 9. Mixed working+non-working range
	def test_mixed_working_and_non_working_range(self):
		"""9. Mixed range: range spanning 1 working day + 1 weekly off only counts working day."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")

		# 2026-06-07 is Sunday (Weekly Off) and 2026-06-08 is Monday (working day) -> 2 calendar days, 1 working day
		doc = self._make_leave_application("2026-06-07", "2026-06-08")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 1.0)

		doc.insert(ignore_permissions=True)
		doc.submit()
		# Only 1.0 day deducted from 2.0 balance
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 1.0)

	# 10. Multiple sequential applications
	def test_multiple_sequential_applications(self):
		"""10. Multiple sequential applications: consecutive applications deduct balance step by step."""
		self._credit_comp_off(self.employee, leaves=3.0, entry_date="2026-06-01")

		# Day 1
		self._make_leave_application("2026-06-08", "2026-06-08", submit=True)
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 2.0)

		# Day 2
		self._make_leave_application("2026-06-09", "2026-06-09", submit=True)
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 1.0)

		# Day 3 (2026-06-11 Thursday is a working day, since 06-10 is holiday)
		self._make_leave_application("2026-06-11", "2026-06-11", submit=True)
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 0.0)

		# Day 4: no balance remaining, next application fails
		doc4 = self._make_leave_application("2026-06-12", "2026-06-12")
		with self.assertRaises(frappe.ValidationError):
			validate_comp_off_application(doc4)

	# 11. Request greater than available
	def test_request_greater_than_available(self):
		"""11. Request greater than available: error message shows requested and available balances clearly."""
		self._credit_comp_off(self.employee, leaves=1.5, entry_date="2026-06-01")

		doc = self._make_leave_application("2026-06-08", "2026-06-09")
		with self.assertRaises(frappe.ValidationError) as cm:
			validate_comp_off_application(doc)

		err_msg = str(cm.exception)
		self.assertIn("Requested: 2.0 day(s)", err_msg)
		self.assertIn("Available balance: 1.5 day(s)", err_msg)

	# 12. Half-day worked + half-day comp off
	def test_half_day_worked_plus_half_day_comp_off(self):
		"""12. Half-day worked + half-day comp off: taking half-day Comp Off on a working day deducts 0.5."""
		self._credit_comp_off(self.employee, leaves=1.0, entry_date="2026-06-01")

		doc = self._make_leave_application("2026-06-08", "2026-06-08", half_day=1, half_day_date="2026-06-08")
		validate_comp_off_application(doc)
		self.assertEqual(flt(doc.total_leave_days), 0.5)

		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(flt(get_comp_off_balance(self.employee, "2026-06-15")), 0.5)

	# 13. Earned vs consumed vs balance via get_comp_off_statement
	def test_earned_vs_consumed_vs_balance_via_get_comp_off_statement(self):
		"""13. Statement integrity: get_comp_off_statement correctly aggregates earned, consumed, and balance."""
		self._credit_comp_off(self.employee, leaves=1.0, entry_date="2026-06-01")
		self._credit_comp_off(self.employee, leaves=1.0, entry_date="2026-06-02")
		self._make_leave_application("2026-06-08", "2026-06-08", submit=True)

		statement = get_comp_off_statement(self.employee, "2026-06-01", "2026-06-30")
		total_earned = sum(flt(e.earned) for e in statement)
		total_consumed = sum(flt(e.consumed) for e in statement)
		current_balance = flt(get_comp_off_balance(self.employee, "2026-06-30"))

		self.assertEqual(total_earned, 2.0)
		self.assertEqual(total_consumed, 1.0)
		self.assertEqual(current_balance, 1.0)
		self.assertEqual(flt(total_earned - total_consumed, 2), 1.0)

	# 14. Employee without allocation
	def test_employee_without_allocation(self):
		"""14. Employee without allocation: balance is 0.0 and application is blocked."""
		no_alloc_emp, _ = self._ensure_employee("TEST-COMP-OFF-NO-ALLOC", self.company)
		self._clear_records(no_alloc_emp)

		self.assertEqual(flt(get_comp_off_balance(no_alloc_emp, "2026-06-15")), 0.0)

		doc = self._make_leave_application("2026-06-08", "2026-06-08", employee=no_alloc_emp)
		with self.assertRaises(frappe.ValidationError):
			validate_comp_off_application(doc)

	# 15. Invalid employee
	def test_invalid_employee(self):
		"""15. Invalid employee: get_comp_off_balance throws error when employee does not exist."""
		with self.assertRaises(frappe.ValidationError) as cm:
			get_comp_off_balance("NON-EXISTENT-EMP-99999", "2026-06-15")
		self.assertIn("Employee NON-EXISTENT-EMP-99999 does not exist.", str(cm.exception))

	# 16. Permission checks in the report
	def test_report_permission_checks(self):
		"""16. Report permission: Employee role only sees own record; HR Manager sees all scoped employees."""
		self._credit_comp_off(self.employee, leaves=2.0, entry_date="2026-06-01")
		self._credit_comp_off(self.other_employee, leaves=1.0, entry_date="2026-06-01")

		# Standard Employee user view (ensure user permission active)
		frappe.set_user(self.employee_user)
		_, emp_data = execute_comp_off_balance_report({"from_date": "2026-06-01", "to_date": "2026-06-30"})
		emp_names = [row["employee"] for row in emp_data]
		self.assertIn(self.employee, emp_names)
		self.assertNotIn(self.other_employee, emp_names)

		# HR Manager user view
		frappe.set_user(self.hr_manager_user)
		_, hr_data = execute_comp_off_balance_report({"from_date": "2026-06-01", "to_date": "2026-06-30"})
		hr_emp_names = [row["employee"] for row in hr_data]
		self.assertIn(self.employee, hr_emp_names)
		self.assertIn(self.other_employee, hr_emp_names)


def run():
	"""Runner function for unit and integration checks."""
	suite = unittest.TestSuite()
	suite.addTest(unittest.makeSuite(TestCompOffUsage))
	runner = unittest.TextTestRunner(verbosity=2)
	result = runner.run(suite)
	return len(result.failures) + len(result.errors)
