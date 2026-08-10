"""Automated checks for #3 72-hour leave window. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_72h_window.run
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	from valence.valence.doc_events.leave_application import (
		validate,
		validate_72_hour_window,
		_is_hr_user,
	)

	frappe.set_user("Administrator")
	frappe.flags.ignore_72_hour_leave_window = False

	# 1) Hook wired
	hooks = frappe.get_hooks("doc_events").get("Leave Application") or {}
	ok(
		"Hook registered on Leave Application.validate",
		"valence.valence.doc_events.leave_application.validate"
		in (hooks.get("validate") or []),
		str(hooks),
	)

	# 2) Administrator exemption
	ok("Administrator is HR/System exempt", _is_hr_user() is True)

	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name") or frappe.db.get_value(
		"Employee", {}, "name"
	)
	leave_type = frappe.db.get_value("Leave Type", {}, "name") or "Leave Without Pay"
	ok(
		"Employee present for shell docs (optional for unit path)",
		True,
		employee or "NONE — UI full insert needs an Employee master",
	)

	def make_doc(from_date):
		return frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"from_date": from_date,
				"to_date": from_date,
				"leave_type": leave_type,
				"description": "72h window automated test",
			}
		)

	def assert_throws(doc, expect_throw=True):
		"""Only ValidationError counts as a rule block; other exceptions are failures."""
		raised = False
		err = ""
		try:
			validate_72_hour_window(doc)
		except frappe.ValidationError as e:
			raised = True
			err = str(e)
		except Exception as e:
			return False, f"UNEXPECTED {type(e).__name__}: {e}"
		return (raised == expect_throw), err

	# Non-HR role simulation for remainder of employee-path checks
	with patch("valence.valence.doc_events.leave_application.frappe.get_roles", return_value=["Employee"]):
		# 3) tomorrow blocked
		cond, err = assert_throws(make_doc(add_days(getdate(), 1)), True)
		ok("Non-HR blocked for from_date = tomorrow", cond, err[:140])
		ok("Error message mentions 72 hours", "72" in err, err[:140])

		# 4) today blocked
		cond, err = assert_throws(make_doc(getdate()), True)
		ok("Non-HR blocked for from_date = today", cond, err[:100])

		# 5) past blocked
		cond, err = assert_throws(make_doc(add_days(getdate(), -2)), True)
		ok("Non-HR blocked for past from_date", cond, err[:100])

		# 6) find first date with >= 72 hours
		safe_date = None
		for day_offset in range(1, 14):
			candidate = add_days(getdate(), day_offset)
			hours = (get_datetime(candidate) - now_datetime()).total_seconds() / 3600
			if hours >= 72:
				safe_date = candidate
				break
		if not safe_date:
			safe_date = add_days(getdate(), 5)

		hours_safe = (get_datetime(safe_date) - now_datetime()).total_seconds() / 3600
		cond, err = assert_throws(make_doc(safe_date), False)
		ok(
			f"Non-HR allowed for from_date = {safe_date}",
			cond,
			f"hours_until={hours_safe:.1f}" if cond else err[:120],
		)

		# 7) day+2 if still under 72h
		d2 = add_days(getdate(), 2)
		hours_d2 = (get_datetime(d2) - now_datetime()).total_seconds() / 3600
		if hours_d2 < 72:
			cond, err = assert_throws(make_doc(d2), True)
			ok(f"Non-HR blocked for {d2} ({hours_d2:.1f}h < 72)", cond, err[:80])
		else:
			ok(f"day+2 already >= 72h ({hours_d2:.1f}h) — skip tight case", True)

		# 8) flag bypass
		frappe.flags.ignore_72_hour_leave_window = True
		try:
			cond, err = assert_throws(make_doc(getdate()), False)
		finally:
			frappe.flags.ignore_72_hour_leave_window = False
		ok("Flag ignore_72_hour_leave_window bypasses rule", cond, err[:80] if err else "")

		# 9) missing from_date
		cond, err = assert_throws(frappe._dict(from_date=None), False)
		ok("Missing from_date does not throw", cond)

		# 10) entrypoint validate()
		raised = False
		err = ""
		try:
			validate(make_doc(add_days(getdate(), 1)))
		except frappe.ValidationError as e:
			raised = True
			err = str(e)
		ok("validate() entrypoint blocks short notice", raised, err[:120])

	# 11) HR roles allowed
	for role in ("HR Manager", "HR User", "System Manager"):
		with patch(
			"valence.valence.doc_events.leave_application.frappe.get_roles",
			return_value=[role, "Employee"],
		):
			cond, err = assert_throws(make_doc(add_days(getdate(), 1)), False)
			ok(f"{role} may apply leave for tomorrow", cond, err[:80] if err else "")

	# 12) Math sanity: boundary helper print for manual testers
	print("\n--- Manual date guide (based on NOW) ---")
	print(f"NOW: {now_datetime()}")
	for off in range(0, 6):
		d = add_days(getdate(), off)
		h = (get_datetime(d) - now_datetime()).total_seconds() / 3600
		print(f"  from_date={d}  hours_until_midnight_start={h:.1f}  →  {'ALLOW' if h >= 72 else 'BLOCK'}")

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print(f"Recommended ALLOW from_date for UI test: {safe_date}")
	if failed:
		failed_names = [n for s, n, _ in results if s == "FAIL"]
		frappe.throw(f"72h tests failed ({failed}): {failed_names}")

	return {
		"passed": passed,
		"failed": failed,
		"safe_date": str(safe_date),
		"now": str(now_datetime()),
	}
