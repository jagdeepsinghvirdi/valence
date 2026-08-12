"""Automated checks for #4 Super HOD leave workflow. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_workflow.run
"""

from __future__ import annotations

import frappe
from frappe.model.workflow import get_workflow_name, get_workflow_safe_globals

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
		"workflow_state custom field on Leave Application",
		bool(
			frappe.db.exists(
				"Custom Field", {"dt": "Leave Application", "fieldname": "workflow_state"}
			)
		),
	)

	wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
	state_names = {s.state for s in wf.states}
	ok(
		"Has Super HOD pending state",
		STATE_PENDING_SUPER_HOD in state_names,
		", ".join(sorted(state_names)),
	)

	def eval_cond(cond, d):
		return frappe.safe_eval(cond, get_workflow_safe_globals(), dict(doc=d))

	short_doc = frappe._dict(total_leave_days=2)
	long_doc = frappe._dict(total_leave_days=3)
	half_doc = frappe._dict(total_leave_days=0.5)

	ok("Condition SHORT true for 2 days", eval_cond(COND_SHORT, short_doc) is True)
	ok("Condition SHORT false for 3 days", eval_cond(COND_SHORT, long_doc) is False)
	ok("Condition LONG true for 3 days", eval_cond(COND_LONG, long_doc) is True)
	ok("Condition LONG false for 2 days", eval_cond(COND_LONG, short_doc) is False)
	ok("Condition SHORT true for half day", eval_cond(COND_SHORT, half_doc) is True)

	long_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_PENDING_SUPER_HOD
		and t.condition
	]
	short_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_APPROVED
		and t.condition
	]
	ok("HOD Approve → Super HOD has conditioned rows", len(long_rows) >= 1, str(len(long_rows)))
	ok("HOD Approve → Approved has conditioned rows", len(short_rows) >= 1, str(len(short_rows)))

	super_approve = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_SUPER_HOD
		and t.action == "Approve"
		and t.allowed == "Super HOD"
	]
	ok("Super HOD Approve transition exists", len(super_approve) >= 1)

	from valence.valence.doc_events.leave_application import (
		finalize_system_leave_application,
		notify_super_hod_if_needed,
	)

	ok("Notifier importable", callable(notify_super_hod_if_needed))
	ok("System leave helper importable", callable(finalize_system_leave_application))

	hooks = frappe.get_hooks("doc_events").get("Leave Application") or {}
	ok(
		"on_update hook registered",
		"valence.valence.doc_events.leave_application.on_update" in (hooks.get("on_update") or []),
	)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print(f"Workflow: {WORKFLOW_NAME}")
	print("Manual: leave ≥ 3 days → Apply → HOD Approve → Pending Super HOD → Super HOD Approve")
	if failed:
		frappe.throw(
			f"Leave workflow tests failed ({failed}): {[n for s, n, _ in results if s == 'FAIL']}"
		)

	return {"passed": passed, "failed": failed}
