"""Automated checks for #11 resigned employee leave types. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_resignation.run
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from valence.valence.doc_events.leave_application import (
	get_leave_type_filter_for_employee,
	validate_resigned_employee_leave_type,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")

	lwp = _ensure_leave_type("Leave Without Pay", is_lwp=1)
	sick = _ensure_leave_type("Sick Leave", is_lwp=0)
	casual = _ensure_leave_type("Casual Leave", is_lwp=0)

	active_emp = _ensure_employee("E2E Active Emp", resigned=False)
	resigned_emp = _ensure_employee("E2E Resigned Emp", resigned=True)

	def make_doc(employee, leave_type):
		return frappe._dict(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": nowdate(),
				"to_date": nowdate(),
			}
		)

	def assert_blocked(doc, expect_block=True):
		try:
			validate_resigned_employee_leave_type(doc)
			return (not expect_block), "no error"
		except frappe.ValidationError as e:
			return expect_block, str(e)
		except Exception as e:
			return False, f"UNEXPECTED {type(e).__name__}: {e}"

	with patch("valence.valence.doc_events.leave_application.frappe.get_roles", return_value=["Employee"]):
		allowed_active, err = assert_blocked(make_doc(active_emp, casual), False)
		ok("Active employee can apply Casual Leave", allowed_active, err[:80])

		blocked, err = assert_blocked(make_doc(resigned_emp, casual), True)
		ok("Resigned employee blocked for Casual Leave", blocked, err[:120])

		allowed_lwp, err2 = assert_blocked(make_doc(resigned_emp, lwp), False)
		ok("Resigned employee allowed LWP", allowed_lwp, err2[:80])

		allowed_sick, err3 = assert_blocked(make_doc(resigned_emp, sick), False)
		ok("Resigned employee allowed Sick Leave", allowed_sick, err3[:80])

		notice_emp = _ensure_employee("E2E Notice Emp", resigned=False)
		if frappe.get_meta("Employee").has_field("resignation_letter_date"):
			frappe.db.set_value("Employee", notice_emp, "resignation_letter_date", nowdate())
			frappe.db.commit()
			notice_blocked, errn = assert_blocked(make_doc(notice_emp, casual), True)
			ok("Notice-period employee blocked for Casual Leave", notice_blocked, errn[:120])
			notice_filter = get_leave_type_filter_for_employee(notice_emp)
			ok(
				"Notice-period dropdown only LWP and Sick Leave",
				bool(notice_filter)
				and set(notice_filter) <= {"Leave Without Pay", "Sick Leave"}
				and casual not in (notice_filter or []),
				str(notice_filter),
			)

	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["HR Manager"],
	):
		allowed_hr, err4 = assert_blocked(make_doc(resigned_emp, casual), False)
		ok("HR Manager can apply any leave for resigned employee", allowed_hr, err4[:80])

	frappe.flags.ignore_resigned_leave_type_check = True
	try:
		with patch(
			"valence.valence.doc_events.leave_application.frappe.get_roles",
			return_value=["Employee"],
		):
			allowed_flag, err5 = assert_blocked(make_doc(resigned_emp, casual), False)
			ok("ignore_resigned_leave_type_check bypasses rule", allowed_flag, err5[:80])
	finally:
		frappe.flags.ignore_resigned_leave_type_check = False

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(f"Resignation leave tests failed ({failed})")
	return {"passed": passed, "failed": failed}


def _ensure_leave_type(name, is_lwp=0):
	if frappe.db.exists("Leave Type", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Leave Type",
			"leave_type_name": name,
			"is_lwp": is_lwp,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return name


def _ensure_employee(name, resigned=False):
	existing = frappe.db.get_value("Employee", {"employee_name": name}, "name")
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	if existing:
		frappe.db.set_value(
			"Employee",
			existing,
			{
				"status": "Left" if resigned else "Active",
				"relieving_date": nowdate() if resigned else None,
			},
		)
		frappe.db.commit()
		return existing

	parts = name.split(" ", 1)
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": parts[0],
			"last_name": parts[1] if len(parts) > 1 else "",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": nowdate(),
			"status": "Left" if resigned else "Active",
			"relieving_date": nowdate() if resigned else None,
			"company": company,
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
