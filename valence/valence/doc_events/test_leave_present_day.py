"""Automated checks for #10 leave on Present day restriction. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_present_day.run
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, nowdate

from valence.valence.doc_events.leave_application import (
	validate_no_leave_on_present_day,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")

	hooks = frappe.get_hooks("doc_events").get("Leave Application") or {}
	ok(
		"validate hook still registered",
		"valence.valence.doc_events.leave_application.validate"
		in (hooks.get("validate") or []),
	)

	employee, company = _ensure_employee()
	leave_type = frappe.db.get_value("Leave Type", {}, "name") or "Leave Without Pay"
	leave_date = add_days(getdate(), 30)
	_cleanup(employee, leave_date)

	att_name = _ensure_present_attendance(employee, company, leave_date)
	ok("Test Present attendance created", bool(att_name), att_name or "none")

	def make_leave(from_date, to_date=None):
		return frappe._dict(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"from_date": from_date,
				"to_date": to_date or from_date,
				"leave_type": leave_type,
			}
		)

	def assert_blocked(doc, expect_block=True):
		try:
			validate_no_leave_on_present_day(doc)
			return (not expect_block), "no error"
		except frappe.ValidationError as e:
			return expect_block, str(e)
		except Exception as e:
			return False, f"UNEXPECTED {type(e).__name__}: {e}"

	with patch("valence.valence.doc_events.leave_application.frappe.get_roles", return_value=["Employee"]):
		blocked, err = assert_blocked(make_leave(leave_date), True)
		ok("Employee blocked on Present day", blocked, err[:160])
		ok("Error mentions Present", "Present" in err, err[:80])

		# Different date with no Present attendance should pass
		clear_date = add_days(leave_date, 5)
		allowed, err2 = assert_blocked(make_leave(clear_date), False)
		ok("Employee allowed when no Present attendance", allowed, err2[:80])

		# Range spanning Present day blocked
		blocked_range, err3 = assert_blocked(
			make_leave(add_days(leave_date, -1), add_days(leave_date, 1)), True
		)
		ok("Employee blocked when range includes Present day", blocked_range, err3[:80])

	# HR override
	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["HR Manager"],
	):
		allowed_hr, err4 = assert_blocked(make_leave(leave_date), False)
		ok("HR Manager can apply on Present day", allowed_hr, err4[:80])

	# Flag bypass
	frappe.flags.ignore_present_day_leave_restriction = True
	try:
		with patch(
			"valence.valence.doc_events.leave_application.frappe.get_roles",
			return_value=["Employee"],
		):
			allowed_flag, err5 = assert_blocked(make_leave(leave_date), False)
			ok("ignore_present_day_leave_restriction bypasses rule", allowed_flag, err5[:80])
	finally:
		frappe.flags.ignore_present_day_leave_restriction = False

	_cleanup(employee, leave_date)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(f"Present-day leave tests failed ({failed})")
	return {"passed": passed, "failed": failed}


def _ensure_employee():
	existing = frappe.db.get_value("Employee", {"status": "Active"}, ["name", "company"], as_dict=True)
	if existing:
		return existing.name, existing.company

	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "Present",
			"last_name": "DayTest",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": nowdate(),
			"status": "Active",
			"company": company,
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name, company


def _ensure_present_attendance(employee, company, attendance_date):
	existing = frappe.db.exists(
		"Attendance",
		{"employee": employee, "attendance_date": attendance_date, "docstatus": ["!=", 2]},
	)
	if existing:
		frappe.db.set_value("Attendance", existing, {"status": "Present", "docstatus": 1})
		frappe.db.commit()
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"company": company,
			"attendance_date": attendance_date,
			"status": "Present",
		}
	)
	# Valence attendance.validate calls get_offday_status (needs Shift Assignment custom fields).
	# Patch for unit test — we only need a submitted Present row for leave validation.
	with patch("valence.valence.doc_events.attendance.set_status"):
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True)
		doc.flags.ignore_validate = True
		doc.submit()
	frappe.db.commit()
	return doc.name


def _cleanup(employee, attendance_date):
	for name in frappe.get_all(
		"Attendance",
		filters={"employee": employee, "attendance_date": attendance_date},
		pluck="name",
	):
		try:
			doc = frappe.get_doc("Attendance", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Attendance", name, force=1, ignore_permissions=True)
		except Exception:
			pass
	frappe.db.commit()
