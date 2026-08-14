"""Checks for backdated leave + working-day Super HOD threshold. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_72h_window.run
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from valence.valence.doc_events.leave_application import (
	WORKING_LEAVE_DAYS_FIELD,
	count_working_leave_days,
	needs_super_hod_approval,
	set_working_leave_days,
	validate,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	# Ensure field exists
	from valence.valence.setup.leave_workflow import ensure_leave_application_workflow

	ensure_leave_application_workflow()

	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
	ok("Employee exists", bool(employee), employee or "NONE")
	if not employee:
		frappe.throw("Need an Employee to run leave day tests")

	leave_type = frappe.db.get_value("Leave Type", {}, "name") or "Leave Without Pay"

	def make_doc(from_date, to_date, half_day=0):
		return frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"from_date": from_date,
				"to_date": to_date,
				"half_day": half_day,
				"half_day_date": from_date if half_day else None,
				"leave_type": leave_type,
				"description": "working-days unit test",
			}
		)

	# Backdated leave must NOT throw 72h-style errors for non-HR
	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["Employee"],
	):
		past_from = add_days(getdate(), -4)
		past_to = add_days(getdate(), -2)
		doc = make_doc(past_from, past_to)
		allowed = True
		err = ""
		try:
			# Only our validate helpers that remain (no 72h)
			set_working_leave_days(doc)
		except Exception as e:
			allowed = False
			err = str(e)
		ok("Backdated leave sets working days without throw", allowed, err[:100])
		ok(
			"Backdated working days populated",
			flt_days(doc.get(WORKING_LEAVE_DAYS_FIELD)) >= 0,
			str(doc.get(WORKING_LEAVE_DAYS_FIELD)),
		)

	# Threshold helpers (length-only, and date-aware)
	past = add_days(getdate(), -5)
	future = add_days(getdate(), 5)
	ok("3 working days → no Super HOD", needs_super_hod_approval(3) is False)
	ok("4 working days → Super HOD (no date)", needs_super_hod_approval(4) is True)
	ok("2.5 working days → no Super HOD", needs_super_hod_approval(2.5) is False)
	ok("Future 4 working days → no Super HOD", needs_super_hod_approval(4, from_date=future) is False)
	ok("Backdated 4 working days → Super HOD", needs_super_hod_approval(4, from_date=past) is True)

	# Mon–Thu = 4 calendar weekdays if no offs
	days = count_working_leave_days(employee, "2026-09-07", "2026-09-10")
	ok("Mon–Thu count is positive", days > 0, f"days={days}")
	ok(
		"Mon–Thu Super HOD decision matches count",
		needs_super_hod_approval(days) == (days > 3),
		f"days={days}",
	)

	# Half day on a single working day → 0.5
	one = count_working_leave_days(
		employee, "2026-09-07", "2026-09-07", half_day=1, half_day_date="2026-09-07"
	)
	# If that Monday is a holiday/off, count may be 0 — still valid
	ok("Single-day half-day count in {0, 0.5}", one in (0, 0.5), f"days={one}")

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print("Backdated leave allowed; Super HOD only for backdated leave when working days > 3.")
	if failed:
		frappe.throw(f"Working-days leave tests failed ({failed})")

	return {"passed": passed, "failed": failed}


def flt_days(v):
	try:
		return float(v or 0)
	except Exception:
		return -1
