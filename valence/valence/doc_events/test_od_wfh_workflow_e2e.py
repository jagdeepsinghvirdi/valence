"""
E2E test for #7 OD/WFH workflow on Attendance Request.

Every OD/WFH request requires HOD then Super HOD — including same-day,
half-day, future, and backdated requests.

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
BACKDATED_OFFSET = -2  # within 72-hour window so creation is allowed


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

	actors = _ensure_test_actors()
	ok("Test actors ready", all(actors.values()), str(actors))

	employee = actors["employee"]["employee"]
	company = frappe.db.get_value("Employee", employee, "company")
	_purge_test_requests(employee)
	created = []

	try:
		# Same-day WFH (tester case) → Super HOD required
		same_day = _new_request(
			employee,
			company,
			target_working_days=1,
			reason="Work From Home",
			description="E2E same-day WFH",
			start_offset=0,
		)
		created.append(same_day.name)
		_apply_and_hod_approve(same_day.name)
		same_day.reload()
		ok(
			"Same-day WFH: HOD Approve → Pending Super HOD",
			same_day.workflow_state == STATE_PENDING_SUPER_HOD and same_day.docstatus == 0,
			same_day.workflow_state,
		)
		open_ok = True
		open_err = ""
		with _as_user(SUPER_HOD_USER):
			try:
				frappe.get_doc("Attendance Request", same_day.name)
			except Exception as e:
				open_ok = False
				open_err = str(e)[:160]
		ok("Super HOD can open same-day OD/WFH", open_ok, open_err)
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", same_day.name), "Approve")
		same_day.reload()
		ok(
			"Same-day WFH: Super HOD Approve → Approved",
			same_day.workflow_state == STATE_APPROVED and same_day.docstatus == 1,
			same_day.workflow_state,
		)

		# Half-day style 1-day OD (tester case) still needs Super HOD after HOD
		half = _new_request(
			employee,
			company,
			target_working_days=1,
			reason="On Duty",
			description="E2E half-day-style OD",
			start_offset=FROM_OFFSET_DAYS,
			half_day=1,
		)
		created.append(half.name)
		_apply_and_hod_approve(half.name)
		half.reload()
		ok(
			"Half-day OD: HOD Approve → Pending Super HOD",
			half.workflow_state == STATE_PENDING_SUPER_HOD,
			half.workflow_state,
		)
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", half.name), "Approve")
		half.reload()
		ok(
			"Half-day OD: Super HOD Approve → Approved",
			half.workflow_state == STATE_APPROVED,
			half.workflow_state,
		)

		# Future multi-day OD → Super HOD still required
		future_long = _new_request(
			employee,
			company,
			target_working_days=4,
			reason="On Duty",
			description="E2E future long OD",
			start_offset=FROM_OFFSET_DAYS + 20,
		)
		created.append(future_long.name)
		_apply_and_hod_approve(future_long.name)
		future_long.reload()
		ok(
			"Future long: HOD Approve → Pending Super HOD",
			future_long.workflow_state == STATE_PENDING_SUPER_HOD,
			future_long.workflow_state,
		)
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", future_long.name), "Approve")
		future_long.reload()
		ok(
			"Future long: Super HOD Approve → Approved",
			future_long.workflow_state == STATE_APPROVED and future_long.docstatus == 1,
			future_long.workflow_state,
		)

		# Backdated (within 72h window) → Super HOD + ToDo
		backdated = _new_request(
			employee,
			company,
			target_working_days=1,
			reason="Work From Home",
			description="E2E backdated WFH",
			start_offset=BACKDATED_OFFSET,
		)
		created.append(backdated.name)
		_apply_and_hod_approve(backdated.name)
		backdated.reload()
		ok(
			"Backdated WFH: HOD Approve → Pending Super HOD",
			backdated.workflow_state == STATE_PENDING_SUPER_HOD,
			backdated.workflow_state,
		)
		todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Attendance Request",
				"reference_name": backdated.name,
				"status": "Open",
			},
			pluck="name",
		)
		ok("Backdated WFH: Super HOD ToDo created", len(todos) >= 1, str(todos[:3]))
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", backdated.name), "Approve")
		backdated.reload()
		ok(
			"Backdated WFH: Super HOD Approve → Approved",
			backdated.workflow_state == STATE_APPROVED,
			backdated.workflow_state,
		)

		# Reject at HOD still works without Super HOD
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
			apply_workflow(frappe.get_doc("Attendance Request", rej.name), "Apply")
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", rej.name), "Reject")
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


def _apply_and_hod_approve(name):
	with _as_user(EMP_USER):
		apply_workflow(frappe.get_doc("Attendance Request", name), "Apply")
	with _as_user(HOD_USER):
		apply_workflow(frappe.get_doc("Attendance Request", name), "Approve")


@contextmanager
def _as_user(user):
	prev = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(prev)


def _ensure_test_actors():
	from valence.valence.doc_events.test_leave_workflow_e2e import _ensure_test_actors as ensure_leave_actors

	return ensure_leave_actors()


def _new_request(employee, company, target_working_days, reason, description, start_offset, half_day=0):
	from_date = add_days(getdate(), start_offset)
	joining = frappe.db.get_value("Employee", employee, "date_of_joining")
	if joining and getdate(from_date) < getdate(joining):
		from_date = getdate(joining)
	from_date = _next_free_attendance_date(employee, from_date, forward=start_offset >= 0)
	to_date = from_date
	working = 0.0
	for _ in range(60):
		working = count_working_leave_days(employee, from_date, to_date)
		if working >= float(target_working_days):
			break
		to_date = add_days(to_date, 1)

	payload = {
		"doctype": "Attendance Request",
		"employee": employee,
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
		"reason": reason,
		"explanation": description,
		"include_holidays": 0,
	}
	if half_day and frappe.get_meta("Attendance Request").has_field("half_day"):
		payload["half_day"] = 1
		if frappe.get_meta("Attendance Request").has_field("half_day_date"):
			payload["half_day_date"] = from_date

	doc = frappe.get_doc(payload)
	prev_window = getattr(frappe.flags, "ignore_leave_creation_window", False)
	if getdate(from_date) < getdate():
		frappe.flags.ignore_leave_creation_window = True
	try:
		_clear_attendance(employee, from_date, to_date)
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.ignore_leave_creation_window = prev_window
	doc.reload()

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


def _clear_attendance(employee, start, end):
	names = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [start, end]],
			"docstatus": ["<", 2],
		},
		pluck="name",
	)
	for name in names:
		try:
			doc = frappe.get_doc("Attendance", name)
			if doc.docstatus == 1:
				try:
					doc.cancel()
				except Exception:
					frappe.db.set_value("Attendance", name, "docstatus", 2)
			frappe.delete_doc("Attendance", name, force=1, ignore_permissions=True)
		except Exception:
			pass
	frappe.db.commit()


def _next_free_attendance_date(employee, start, forward=True):
	"""Skip dates that already have Attendance so HRMS does not refuse the request."""
	d = getdate(start)
	step = 1 if forward else -1
	for _ in range(60):
		exists = frappe.db.exists(
			"Attendance",
			{"employee": employee, "attendance_date": d, "docstatus": ["<", 2]},
		)
		if not exists:
			return d
		d = add_days(d, step)
	return getdate(start)


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
