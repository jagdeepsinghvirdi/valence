"""
E2E test for #7 OD/WFH workflow on Attendance Request.

  bench --site valence.localhost execute valence.valence.doc_events.test_od_wfh_workflow_e2e.run
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.utils import add_days, getdate, nowdate

from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
)
from valence.valence.setup.od_wfh_workflow import WORKFLOW_NAME, ensure_od_wfh_workflow

EMP_USER = "e2e.employee@valence.test"
HOD_USER = "e2e.hod@valence.test"
SUPER_HOD_USER = "e2e.superhod@valence.test"

FROM_OFFSET_DAYS = 20


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

	company = frappe.db.get_value("Employee", actors["employee"]["employee"], "company")
	_purge_test_requests(actors["employee"]["employee"])
	created = []

	try:
		# Short WFH (1 day)
		short = _new_request(
			actors["employee"]["employee"],
			company,
			days=1,
			reason="Work From Home",
			description="E2E short WFH",
			start_offset=FROM_OFFSET_DAYS,
		)
		created.append(short.name)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", short.name)
			apply_workflow(doc, "Apply")

		short.reload()
		ok(
			"Short: Apply → Pending HOD",
			short.workflow_state == STATE_PENDING_HOD and short.docstatus == 0,
			f"state={short.workflow_state} days={short.total_request_days}",
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
			{"employee": actors["employee"]["employee"], "attendance_request": short.name},
		)
		ok("Short: attendance record created", bool(attendance), attendance or "none")

		# Long OD (3 days)
		long = _new_request(
			actors["employee"]["employee"],
			company,
			days=3,
			reason="On Duty",
			description="E2E long OD",
			start_offset=FROM_OFFSET_DAYS + 10,
		)
		created.append(long.name)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Apply")

		long.reload()
		ok(
			"Long: Apply → Pending HOD",
			long.workflow_state == STATE_PENDING_HOD,
			f"days={long.total_request_days}",
		)

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Long: HOD Approve → Pending Super HOD",
			long.workflow_state == STATE_PENDING_SUPER_HOD and long.docstatus == 0,
			long.workflow_state,
		)

		with _as_user(SUPER_HOD_USER):
			doc = frappe.get_doc("Attendance Request", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Long: Super HOD Approve → submitted",
			long.workflow_state == STATE_APPROVED and long.docstatus == 1,
			f"state={long.workflow_state}",
		)

		# Reject path
		rej = _new_request(
			actors["employee"]["employee"],
			company,
			days=1,
			reason="On Duty",
			description="E2E reject OD",
			start_offset=FROM_OFFSET_DAYS + 20,
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


def _new_request(employee, company, days, reason, description, start_offset):
	from_date = add_days(getdate(), start_offset)
	to_date = add_days(from_date, max(days - 1, 0))

	doc = frappe.get_doc(
		{
			"doctype": "Attendance Request",
			"employee": employee,
			"company": company,
			"from_date": from_date,
			"to_date": to_date,
			"reason": reason,
			"explanation": description,
			"include_holidays": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.reload()

	if days >= 3 and int(doc.total_request_days or 0) < 3:
		frappe.db.set_value(
			"Attendance Request", doc.name, "total_request_days", days, update_modified=False
		)
		doc.reload()
	elif days < 3 and int(doc.total_request_days or 0) >= 3:
		frappe.db.set_value(
			"Attendance Request", doc.name, "total_request_days", days, update_modified=False
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
			frappe.delete_doc("Attendance Request", name, force=1, ignore_permissions=True)
		except Exception:
			pass
	frappe.db.commit()
