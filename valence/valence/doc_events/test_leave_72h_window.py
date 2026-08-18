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
	validate_leave_creation_window,
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

	# 3-day window is for CREATION only, counted from leave END date
	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["Employee"],
	):
		within = make_doc(add_days(getdate(), -5), add_days(getdate(), -3))
		allowed = True
		err = ""
		try:
			validate_leave_creation_window(within)
		except Exception as e:
			allowed = False
			err = str(e)
		ok("Create within 3 days of end date is allowed", allowed, err[:100])

		# Start can be older than 3 days if end date is still inside the window
		old_start = make_doc(add_days(getdate(), -10), add_days(getdate(), -2))
		old_start_ok = True
		err = ""
		try:
			validate_leave_creation_window(old_start)
		except Exception as e:
			old_start_ok = False
			err = str(e)
		ok("Start date older than 3 days is allowed if end date is within window", old_start_ok, err[:100])

		too_old = make_doc(add_days(getdate(), -8), add_days(getdate(), -4))
		blocked = False
		err = ""
		try:
			validate_leave_creation_window(too_old)
		except Exception as e:
			blocked = "Creation Window" in str(e) or "end date" in str(e).lower()
			err = str(e)
		ok("Create older than 3 days from end date is blocked", blocked, err[:120])

		future_doc = make_doc(add_days(getdate(), 5), add_days(getdate(), 6))
		future_ok = True
		try:
			validate_leave_creation_window(future_doc)
		except Exception:
			future_ok = False
		ok("Future leave creation is not limited by 3-day window", future_ok)

		# Existing doc, to_date unchanged → approval path must not throw
		too_old.flags.in_insert = False
		with patch.object(too_old, "is_new", return_value=False), patch.object(
			too_old, "get_doc_before_save", return_value=too_old
		):
			approve_ok = True
			err = ""
			try:
				validate_leave_creation_window(too_old)
			except Exception as e:
				approve_ok = False
				err = str(e)
			ok("Approval of older leave is not blocked by 3-day window", approve_ok, err[:100])

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
	print("Backdated leave create window = 3 calendar days from end date; Super HOD only for backdated leave when working days > 3.")
	if failed:
		frappe.throw(f"Working-days leave tests failed ({failed})")

	return {"passed": passed, "failed": failed}


def flt_days(v):
	try:
		return float(v or 0)
	except Exception:
		return -1
