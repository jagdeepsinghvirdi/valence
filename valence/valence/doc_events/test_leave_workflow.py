"""Automated checks for working-leave-days + Super HOD routing. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_workflow.run
"""

from __future__ import annotations

import frappe
from frappe.model.workflow import get_workflow_name, get_workflow_safe_globals
from frappe.utils import add_days, getdate

import valence.valence.doc_events.leave_application as la
from valence.valence.doc_events.leave_application import (
	WORKING_LEAVE_DAYS_FIELD,
	count_working_leave_days,
	needs_super_hod_approval,
)
from valence.valence.setup.leave_workflow import (
	COND_LONG,
	COND_SHORT,
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	WORKFLOW_NAME,
	ensure_leave_application_workflow,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	ensure_leave_application_workflow()

	ok(
		"Active workflow name",
		get_workflow_name("Leave Application") == WORKFLOW_NAME,
		str(get_workflow_name("Leave Application")),
	)
	ok("Super HOD role exists", frappe.db.exists("Role", "Super HOD"))
	ok(
		"Working leave days custom field exists",
		bool(
			frappe.db.exists(
				"Custom Field",
				{"dt": "Leave Application", "fieldname": WORKING_LEAVE_DAYS_FIELD},
			)
		),
	)

	wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
	ok(
		"Has Super HOD pending state",
		STATE_PENDING_SUPER_HOD in {s.state for s in wf.states},
	)

	def eval_cond(cond, d):
		return frappe.safe_eval(cond, get_workflow_safe_globals(), dict(doc=d))

	past = add_days(getdate(), -7)
	future = add_days(getdate(), 7)
	today = getdate()
	short_past = frappe._dict({WORKING_LEAVE_DAYS_FIELD: 3, "from_date": past})
	long_past = frappe._dict({WORKING_LEAVE_DAYS_FIELD: 4, "from_date": past})
	long_future = frappe._dict({WORKING_LEAVE_DAYS_FIELD: 4, "from_date": future})
	long_today = frappe._dict({WORKING_LEAVE_DAYS_FIELD: 4, "from_date": today})
	half_past = frappe._dict({WORKING_LEAVE_DAYS_FIELD: 0.5, "from_date": past})

	from valence.valence.setup.leave_workflow import (
		get_super_hod_working_days_threshold,
		SETTINGS_DOCTYPE,
		THRESHOLD_FIELD,
	)

	# Pin threshold=3 for condition checks, then restore
	prev = frappe.db.get_single_value(SETTINGS_DOCTYPE, THRESHOLD_FIELD)
	frappe.db.set_single_value(SETTINGS_DOCTYPE, THRESHOLD_FIELD, 3)

	ok("COND_SHORT false for backdated 3 days (3+ needs Super HOD)", eval_cond(COND_SHORT, short_past) is False)
	ok("COND_SHORT false for backdated 4 days (threshold 3)", eval_cond(COND_SHORT, long_past) is False)
	ok("COND_LONG true for backdated 4 days (threshold 3)", eval_cond(COND_LONG, long_past) is True)
	ok("COND_LONG true for backdated 3 days (3 or more)", eval_cond(COND_LONG, short_past) is True)
	ok("COND_SHORT false for future 4 days (3+ needs Super HOD)", eval_cond(COND_SHORT, long_future) is False)
	ok("COND_LONG true for future 4 days", eval_cond(COND_LONG, long_future) is True)
	ok("COND_SHORT false for same-day 4 days", eval_cond(COND_SHORT, long_today) is False)
	ok("COND_LONG true for same-day 4 days", eval_cond(COND_LONG, long_today) is True)
	ok("COND_SHORT true for backdated half day", eval_cond(COND_SHORT, half_past) is True)
	ok("needs_super_hod True for 3 @ threshold 3", needs_super_hod_approval(3) is True)
	ok("needs_super_hod True for 4 @ threshold 3 (no date)", needs_super_hod_approval(4) is True)
	ok(
		"needs_super_hod True for future 4 days",
		needs_super_hod_approval(4, from_date=future) is True,
	)
	ok(
		"needs_super_hod True for backdated 4 days",
		needs_super_hod_approval(4, from_date=past) is True,
	)

	# Customize threshold to 5 → 4 days should NOT need Super HOD
	frappe.db.set_single_value(SETTINGS_DOCTYPE, THRESHOLD_FIELD, 5)
	ok("Configurable: threshold 5 → 4 days no Super HOD", needs_super_hod_approval(4) is False)
	ok("Configurable: threshold 5 → 5 days needs Super HOD", needs_super_hod_approval(5) is True)
	ok(
		"Workflow COND_LONG respects threshold 5 (backdated 4 days)",
		eval_cond(COND_LONG, frappe._dict({WORKING_LEAVE_DAYS_FIELD: 4, "from_date": past})) is False,
	)
	ok(
		"Future 6 days needs Super HOD at threshold 5",
		eval_cond(COND_LONG, frappe._dict({WORKING_LEAVE_DAYS_FIELD: 6, "from_date": future})) is True,
	)
	ok(
		"get_super_hod_working_days_threshold reads 5",
		get_super_hod_working_days_threshold() == 5,
	)

	# Restore
	frappe.db.set_single_value(
		SETTINGS_DOCTYPE, THRESHOLD_FIELD, prev if prev not in (None, "") else 3
	)

	long_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_PENDING_SUPER_HOD
		and WORKING_LEAVE_DAYS_FIELD in (t.condition or "")
	]
	short_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_APPROVED
		and WORKING_LEAVE_DAYS_FIELD in (t.condition or "")
	]
	ok("HOD Approve → Super HOD uses working days", len(long_rows) >= 1)
	ok("HOD Approve → Approved uses working days", len(short_rows) >= 1)

	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
	if employee:
		start = getdate("2026-09-07")  # Monday
		end = getdate("2026-09-09")  # Wednesday
		days = count_working_leave_days(employee, start, end)
		ok("count_working_leave_days Mon–Wed ≥ 1", days >= 1, f"days={days}")

		past_start = add_days(getdate(), -5)
		past_end = add_days(getdate(), -3)
		past_days = count_working_leave_days(employee, past_start, past_end)
		ok("Backdated range is countable", past_days >= 0, f"days={past_days}")
	else:
		ok("Employee present for day-count sample", False, "NONE")

	ok("72h advance rule removed", not hasattr(la, "validate_72_hour_window"))
	ok("set_working_leave_days exists", hasattr(la, "set_working_leave_days"))

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print("Rule: working days < threshold → HOD only; working days >= threshold → Super HOD (any dates).")
	print("Threshold is configurable by HR / Leave Approver / Super HOD.")
	if failed:
		frappe.throw(
			f"Leave workflow tests failed ({failed}): {[n for s, n, _ in results if s == 'FAIL']}"
		)

	return {"passed": passed, "failed": failed}
