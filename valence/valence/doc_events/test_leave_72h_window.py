"""Checks for 72-hour leave window + working-day Super HOD threshold. Run:
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
				"description": "72h window unit test",
			}
		)

	# Working-days helper still runs for backdated leave
	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["Employee"],
	):
		past_from = add_days(getdate(), -2)
		past_to = add_days(getdate(), -1)
		doc = make_doc(past_from, past_to)
		allowed = True
		err = ""
		try:
			set_working_leave_days(doc)
		except Exception as e:
			allowed = False
			err = str(e)
		ok("Backdated leave within window sets working days", allowed, err[:100])
		ok(
			"Backdated working days populated",
			flt_days(doc.get(WORKING_LEAVE_DAYS_FIELD)) >= 0,
			str(doc.get(WORKING_LEAVE_DAYS_FIELD)),
		)

	# Creation window = 3 working days from START date AND after END date (offs excluded)
	with patch(
		"valence.valence.doc_events.leave_application.frappe.get_roles",
		return_value=["Employee"],
	):
		within = make_doc(add_days(getdate(), -2), add_days(getdate(), -1))
		allowed = True
		err = ""
		try:
			validate_leave_creation_window(within)
		except Exception as e:
			allowed = False
			err = str(e)
		ok("Create within 3 working days of start and after end is allowed", allowed, err[:100])

		today_doc = make_doc(getdate(), getdate())
		today_ok = True
		try:
			validate_leave_creation_window(today_doc)
		except Exception:
			today_ok = False
		ok("Same-day leave creation is allowed", today_ok)

		future_doc = make_doc(add_days(getdate(), 5), add_days(getdate(), 6))
		future_ok = True
		try:
			validate_leave_creation_window(future_doc)
		except Exception:
			future_ok = False
		ok("Future leave creation is not limited by creation window", future_ok)

		too_old = make_doc(add_days(getdate(), -14), add_days(getdate(), -14))
		blocked = False
		err = ""
		try:
			validate_leave_creation_window(too_old)
		except Exception as e:
			blocked = "Creation Window" in str(e) or "working days" in str(e).lower()
			err = str(e)
		ok("Create 14 calendar days in the past is blocked", blocked, err[:160])

		old_start = make_doc(add_days(getdate(), -14), add_days(getdate(), -1))
		old_start_blocked = False
		err = ""
		try:
			validate_leave_creation_window(old_start)
		except Exception as e:
			old_start_blocked = True
			err = str(e)
		ok(
			"Start date older than 3 working days is blocked even if end date is recent",
			old_start_blocked,
			err[:120],
		)

		today = getdate()
		holiday_start = make_doc(add_days(today, -5), add_days(today, -1))
		with patch(
			"valence.valence.doc_events.leave_application._get_non_working_dates",
			return_value={add_days(today, -1), add_days(today, -2)},
		):
			holiday_ok = True
			err = ""
			try:
				validate_leave_creation_window(holiday_start)
			except Exception as e:
				holiday_ok = False
				err = str(e)
			ok(
				"Start further back is allowed when gap has week offs / holidays",
				holiday_ok,
				err[:120],
			)

		# Client flow: leave 12–14, holiday 15, week off 16 → apply until 17, 18, 19
		client_leave = make_doc(add_days(today, -5), add_days(today, -5))
		with patch(
			"valence.valence.doc_events.leave_application._get_non_working_dates",
			return_value={add_days(today, -4), add_days(today, -3)},
		):
			client_ok = True
			err = ""
			try:
				validate_leave_creation_window(client_leave)
			except Exception as e:
				client_ok = False
				err = str(e)
			ok(
				"Leave ending 5 days ago is allowed when next 2 days are holiday/week off",
				client_ok,
				err[:120],
			)

			too_late = make_doc(add_days(today, -8), add_days(today, -6))
			too_late_blocked = False
			err = ""
			try:
				validate_leave_creation_window(too_late)
			except Exception as e:
				too_late_blocked = "Creation Window" in str(e) or "working days" in str(e).lower()
				err = str(e)
			ok(
				"Leave ending 6 days ago is blocked (4th working day after end)",
				too_late_blocked,
				err[:160],
			)

		wfh = frappe.get_doc(
			{
				"doctype": "Attendance Request",
				"employee": employee,
				"from_date": add_days(getdate(), -14),
				"to_date": add_days(getdate(), -14),
				"reason": "Work From Home",
			}
		)
		wfh_blocked = False
		err = ""
		try:
			validate_leave_creation_window(wfh)
		except Exception as e:
			wfh_blocked = "Creation Window" in str(e) or "working days" in str(e).lower()
			err = str(e)
		ok("Backdated WFH uses the same start-date and end-date creation window", wfh_blocked, err[:160])

		# Existing doc, dates unchanged → approval path must not throw
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
			ok("Approval of older leave is not blocked by creation window", approve_ok, err[:100])

		with patch(
			"valence.valence.doc_events.leave_application.frappe.get_roles",
			return_value=["HR Manager"],
		):
			hr_ok = True
			try:
				validate_leave_creation_window(make_doc(add_days(getdate(), -14), add_days(getdate(), -14)))
			except Exception:
				hr_ok = False
			ok("HR can override creation window", hr_ok)

	# Threshold helpers: 3 working days or more → Super HOD
	past = add_days(getdate(), -5)
	future = add_days(getdate(), 5)
	ok("2.5 working days → no Super HOD", needs_super_hod_approval(2.5) is False)
	ok("3 working days → Super HOD (3 or more)", needs_super_hod_approval(3) is True)
	ok("4 working days → Super HOD", needs_super_hod_approval(4) is True)
	ok("Future 4 working days → no Super HOD", needs_super_hod_approval(4, from_date=future) is False)
	ok("Backdated 3 working days → Super HOD", needs_super_hod_approval(3, from_date=past) is True)

	days = count_working_leave_days(employee, "2026-09-07", "2026-09-10")
	ok("Mon–Thu count is positive", days > 0, f"days={days}")
	ok(
		"Mon–Thu Super HOD decision matches count",
		needs_super_hod_approval(days) == (days >= 3),
		f"days={days}",
	)

	one = count_working_leave_days(
		employee, "2026-09-07", "2026-09-07", half_day=1, half_day_date="2026-09-07"
	)
	ok("Single-day half-day count in {0, 0.5}", one in (0, 0.5), f"days={one}")

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print(
		"Rule: from_date or to_date more than 3 working days in the past is blocked "
		"(holidays/week offs excluded); Super HOD for backdated leave when working days >= 3."
	)
	if failed:
		frappe.throw(f"72-hour leave tests failed ({failed})")

	return {"passed": passed, "failed": failed}


def flt_days(v):
	try:
		return float(v or 0)
	except Exception:
		return -1
