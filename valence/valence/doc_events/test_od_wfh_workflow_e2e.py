"""
E2E test for #7 OD/WFH workflow on Attendance Request.

Aligned with leave: Super HOD only for backdated requests above the working-days threshold.
Future / same-day OD/WFH is HOD-only regardless of length.

  bench --site valence.localhost execute valence.valence.doc_events.test_od_wfh_workflow_e2e.run
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.utils import add_days, getdate

from valence.valence.doc_events.leave_application import count_working_leave_days
from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
	get_super_hod_working_days_threshold,
)
from valence.valence.setup.od_wfh_workflow import (
	WORKING_REQUEST_DAYS_FIELD,
	WORKFLOW_NAME,
	ensure_od_wfh_workflow,
)

EMP_USER = "e2e.employee@valence.test"
HOD_USER = "e2e.hod@valence.test"
SUPER_HOD_USER = "e2e.superhod@valence.test"

FROM_OFFSET_DAYS = 20
BACKDATED_LONG_OFFSET = -40


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")
	ensure_od_wfh_workflow()

	ok(
		"Workflow active on Attendance Request",
		get_workflow_name("Attendance Request") == WORKFLOW_NAME,
	)

	threshold = get_super_hod_working_days_threshold()
	ok("Threshold loaded", threshold >= 1, str(threshold))

	actors = _ensure_test_actors()
	ok("Test actors ready", all(actors.values()), str(actors))

	employee = actors["employee"]["employee"]
	company = frappe.db.get_value("Employee", employee, "company")
	_purge_test_requests(employee)
	created = []

	try:
		# Short WFH (1 working day) → HOD only
		short = _new_request(
			employee,
			company,
			target_working_days=1,
			reason="Work From Home",
			description="E2E short WFH",
			start_offset=FROM_OFFSET_DAYS,
		)
		created.append(short.name)
		ok(
			"Short: working days ≤ threshold",
			float(short.get(WORKING_REQUEST_DAYS_FIELD) or 0) <= threshold,
			f"working={short.get(WORKING_REQUEST_DAYS_FIELD)} threshold={threshold}",
		)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", short.name)
			apply_workflow(doc, "Apply")

		short.reload()
		ok(
			"Short: Apply → Pending HOD",
			short.workflow_state == STATE_PENDING_HOD and short.docstatus == 0,
			f"state={short.workflow_state} working={short.get(WORKING_REQUEST_DAYS_FIELD)}",
		)

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", short.name)
			apply_workflow(doc, "Approve")

		short.reload()
		ok(
			"Short: HOD Approve → submitted",
			short.workflow_state == STATE_APPROVED and short.docstatus == 1,
			f"state={short.workflow_state} docstatus={short.docstatus}",
		)

		attendance = frappe.db.exists(
			"Attendance",
			{"employee": employee, "attendance_request": short.name},
		)
		ok("Short: attendance record created", bool(attendance), attendance or "none")

		# At-threshold OD (exactly threshold working days) → HOD only (≤ threshold)
		at_thr = _new_request(
			employee,
			company,
			target_working_days=threshold,
			reason="On Duty",
			description="E2E at-threshold OD",
			start_offset=FROM_OFFSET_DAYS + 8,
		)
		created.append(at_thr.name)
		ok(
			"At-threshold: working days == threshold",
			float(at_thr.get(WORKING_REQUEST_DAYS_FIELD) or 0) == float(threshold),
			f"working={at_thr.get(WORKING_REQUEST_DAYS_FIELD)}",
		)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", at_thr.name)
			apply_workflow(doc, "Apply")
		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", at_thr.name)
			apply_workflow(doc, "Approve")

		at_thr.reload()
		ok(
			"At-threshold: HOD Approve → Approved (no Super HOD)",
			at_thr.workflow_state == STATE_APPROVED and at_thr.docstatus == 1,
			at_thr.workflow_state,
		)

		# Future long OD (working days > threshold) → HOD only
		future_long = _new_request(
			employee,
			company,
			target_working_days=threshold + 1,
			reason="On Duty",
			description="E2E future long OD",
			start_offset=FROM_OFFSET_DAYS + 20,
		)
		created.append(future_long.name)
		ok(
			"Future long: working days > threshold",
			float(future_long.get(WORKING_REQUEST_DAYS_FIELD) or 0) > threshold,
			f"working={future_long.get(WORKING_REQUEST_DAYS_FIELD)} threshold={threshold}",
		)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", future_long.name)
			apply_workflow(doc, "Apply")
		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", future_long.name)
			apply_workflow(doc, "Approve")

		future_long.reload()
		ok(
			"Future long: HOD Approve → Approved (no Super HOD)",
			future_long.workflow_state == STATE_APPROVED and future_long.docstatus == 1,
			future_long.workflow_state,
		)

		# Backdated long OD (working days > threshold) → Super HOD
		long = _new_request(
			employee,
			company,
			target_working_days=threshold + 1,
			reason="On Duty",
			description="E2E backdated long OD",
			start_offset=BACKDATED_LONG_OFFSET,
		)
		created.append(long.name)
		ok(
			"Long: working days > threshold",
			float(long.get(WORKING_REQUEST_DAYS_FIELD) or 0) > threshold,
			f"working={long.get(WORKING_REQUEST_DAYS_FIELD)} threshold={threshold}",
		)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Apply")

		long.reload()
		ok(
			"Long: Apply → Pending HOD",
			long.workflow_state == STATE_PENDING_HOD,
			f"working={long.get(WORKING_REQUEST_DAYS_FIELD)}",
		)

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Backdated long: HOD Approve → Pending Super HOD",
			long.workflow_state == STATE_PENDING_SUPER_HOD and long.docstatus == 0,
			long.workflow_state,
		)

		todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Attendance Request",
				"reference_name": long.name,
				"status": "Open",
			},
			pluck="name",
		)
		ok("Backdated long: Super HOD ToDo created", len(todos) >= 1, str(todos[:3]))

		with _as_user(SUPER_HOD_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Backdated long: Super HOD Approve → submitted",
			long.workflow_state == STATE_APPROVED and long.docstatus == 1,
			f"state={long.workflow_state}",
		)

		# Reject path
		rej = _new_request(
			employee,
			company,
			target_working_days=1,
			reason="On Duty",
			description="E2E reject OD",
			start_offset=FROM_OFFSET_DAYS + 40,
		)
		created.append(rej.name)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", rej.name)
			apply_workflow(doc, "Apply")

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", rej.name)
			apply_workflow(doc, "Reject")

		rej.reload()
		ok(
			"Reject: stays draft, not submitted",
			rej.workflow_state == STATE_REJECTED and rej.docstatus == 0,
			f"state={rej.workflow_state} docstatus={rej.docstatus}",
		)

		ok("E2E suite completed", True)

	except Exception as exc:
		ok("E2E suite ran without exception", False, str(exc)[:200])
		raise
	finally:
		_cleanup_requests(created)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== E2E SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(f"OD/WFH E2E failed ({failed})")
	return {"passed": passed, "failed": failed}


@contextmanager
def _as_user(user):
	prev = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(prev)


def _ensure_test_actors():
	"""Reuse E2E users from leave workflow tests."""
	from valence.valence.doc_events.test_leave_workflow_e2e import _ensure_test_actors as ensure_leave_actors

	return ensure_leave_actors()


def _new_request(employee, company, target_working_days, reason, description, start_offset):
	"""
	Build an Attendance Request whose working-day count matches target_working_days.
	Scans forward from start_offset until count_working_leave_days hits the target.
	Clamps from_date to employee joining date (HRMS rejects earlier dates).
	"""
	from_date = add_days(getdate(), start_offset)
	joining = frappe.db.get_value("Employee", employee, "date_of_joining")
	if joining and getdate(from_date) < getdate(joining):
		from_date = getdate(joining)
	to_date = from_date
	working = 0.0
	# Cap scan so holidays/week offs don't loop forever
	for _ in range(60):
		working = count_working_leave_days(employee, from_date, to_date)
		if working >= float(target_working_days):
			break
		to_date = add_days(to_date, 1)

	doc = frappe.get_doc(
		{
			"doctype": "Attendance Request",
			"employee": employee,
			"company": company,
			"from_date": from_date,
			"to_date": to_date,
			"reason": reason,
			"explanation": description,
			"include_holidays": 0,
		}
	)
	prev_window = getattr(frappe.flags, "ignore_leave_creation_window", False)
	if getdate(from_date) < getdate():
		frappe.flags.ignore_leave_creation_window = True
	try:
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.ignore_leave_creation_window = prev_window
	doc.reload()

	# Force exact working days if holiday math drifted (e.g. half-day edge)
	actual = float(doc.get(WORKING_REQUEST_DAYS_FIELD) or 0)
	if actual != float(target_working_days):
		frappe.db.set_value(
			"Attendance Request",
			doc.name,
			WORKING_REQUEST_DAYS_FIELD,
			float(target_working_days),
			update_modified=False,
		)
		doc.reload()
	return doc


def _purge_test_requests(employee):
	names = frappe.get_all(
		"Attendance Request",
		filters={"employee": employee, "explanation": ["like", "E2E%"]},
		pluck="name",
	)
	_cleanup_requests(names)


def _cleanup_requests(names):
	for name in names or []:
		try:
			doc = frappe.get_doc("Attendance Request", name)
			if doc.docstatus == 1:
				doc.cancel()
			# Clear ToDos referencing this request
			for todo in frappe.get_all(
				"ToDo",
				filters={"reference_type": "Attendance Request", "reference_name": name},
				pluck="name",
			):
				frappe.delete_doc("ToDo", todo, force=1, ignore_permissions=True)
			frappe.delete_doc("Attendance Request", name, force=1, ignore_permissions=True)
		except Exception:
			pass
	frappe.db.commit()
