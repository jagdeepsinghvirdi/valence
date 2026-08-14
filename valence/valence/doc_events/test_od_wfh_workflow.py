"""Automated checks for #7 OD/WFH workflow. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_od_wfh_workflow.run
"""

from __future__ import annotations

import frappe
from frappe.model.workflow import get_workflow_name

from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
)
from valence.valence.setup.od_wfh_workflow import (
	COND_LONG,
	COND_SHORT,
	DOCTYPE,
	WORKING_REQUEST_DAYS_FIELD,
	WORKFLOW_NAME,
	ensure_od_wfh_workflow,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")
	ensure_od_wfh_workflow()

	ok(
		"Active workflow on Attendance Request",
		get_workflow_name(DOCTYPE) == WORKFLOW_NAME,
		str(get_workflow_name(DOCTYPE)),
	)
	ok(
		"workflow_state custom field exists",
		bool(
			frappe.db.exists(
				"Custom Field", {"dt": DOCTYPE, "fieldname": "workflow_state"}
			)
		),
	)
	ok(
		"total_request_days custom field exists",
		bool(
			frappe.db.exists(
				"Custom Field", {"dt": DOCTYPE, "fieldname": "total_request_days"}
			)
		),
	)
	ok(
		"working request days field exists",
		bool(
			frappe.db.exists(
				"Custom Field", {"dt": DOCTYPE, "fieldname": WORKING_REQUEST_DAYS_FIELD}
			)
		),
	)

	wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
	state_names = {s.state for s in wf.states}
	ok("Has pending HOD state", STATE_PENDING_HOD in state_names)
	ok("Has Super HOD pending state", STATE_PENDING_SUPER_HOD in state_names)
	ok("Has Approved state (submitted)", STATE_APPROVED in state_names)

	short_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_APPROVED
		and t.condition
	]
	long_rows = [
		t
		for t in wf.transitions
		if t.state == STATE_PENDING_HOD
		and t.action == "Approve"
		and t.next_state == STATE_PENDING_SUPER_HOD
		and t.condition
	]
	ok("HOD short Approve path exists", len(short_rows) >= 1)
	ok("HOD long → Super HOD path exists", len(long_rows) >= 1)
	ok(
		"Short condition uses working days + threshold",
		COND_SHORT in (short_rows[0].condition if short_rows else ""),
		short_rows[0].condition if short_rows else "",
	)
	ok(
		"Long condition uses backdated + working days + threshold",
		COND_LONG in (long_rows[0].condition if long_rows else ""),
		long_rows[0].condition if long_rows else "",
	)
	ok(
		"Long condition requires backdated from_date",
		"from_date" in (long_rows[0].condition if long_rows else "")
		and "now_datetime" in (long_rows[0].condition if long_rows else ""),
	)
	ok(
		"Conditions reference Attendance Settings threshold",
		"super_hod_working_days_threshold" in (short_rows[0].condition if short_rows else ""),
	)

	# No self-approval on approve transitions
	self_ok = all(
		not cint(t.allow_self_approval)
		for t in wf.transitions
		if t.action in ("Approve", "Reject") and t.state != "Draft"
	)
	ok("Approve/Reject transitions disallow self-approval", self_ok)

	hooks = frappe.get_hooks("doc_events").get("Attendance Request") or {}
	ok(
		"validate hook registered",
		"valence.valence.doc_events.attendance_request.validate"
		in (hooks.get("validate") or []),
		str(hooks.get("validate")),
	)
	ok(
		"on_update hook registered",
		"valence.valence.doc_events.attendance_request.on_update"
		in (hooks.get("on_update") or []),
	)

	from valence.valence.doc_events.attendance_request import (
		validate_mandatory_explanation,
		validate_no_self_approval,
	)

	ok("Explanation validator importable", callable(validate_mandatory_explanation))
	ok("Self-approval validator importable", callable(validate_no_self_approval))

	# Explanation required
	threw = False
	try:
		doc = frappe._dict(
			{
				"doctype": DOCTYPE,
				"employee": "HR-EMP-00001",
				"reason": "Work From Home",
				"explanation": "   ",
			}
		)
		validate_mandatory_explanation(doc)
	except frappe.ValidationError:
		threw = True
	ok("Blank explanation blocked", threw)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(f"OD/WFH workflow tests failed ({failed})")
	return {"passed": passed, "failed": failed}


def cint(v):
	from frappe.utils import cint as _cint

	return _cint(v)
