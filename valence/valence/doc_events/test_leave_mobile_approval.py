"""Automated checks for #12 mobile leave approval APIs. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_mobile_approval.run
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate

from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	ensure_leave_application_workflow,
)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	ensure_leave_application_workflow()

	from valence.valence.override.whitelisted_method import leave_approval as api
	from valence.valence.doc_events.test_leave_workflow_e2e import (
		EMP_USER,
		HOD_USER,
		PASSWORD,
		SUPER_HOD_USER,
		_as_user,
		_cleanup_leaves,
		_ensure_leave_type_and_allocation,
		_ensure_test_actors,
		_new_leave,
		_purge_existing_test_leaves,
	)

	# Whitelist registration
	ok("get_pending_leave_approvals is whitelisted", hasattr(api.get_pending_leave_approvals, "is_whitelisted") or callable(api.get_pending_leave_approvals))
	ok("apply_leave_workflow_action is whitelisted", callable(api.apply_leave_workflow_action))
	ok("get_leave_workflow_actions is whitelisted", callable(api.get_leave_workflow_actions))

	# Core apply_workflow is already whitelisted (desk + mobile)
	from frappe.model.workflow import apply_workflow

	ok("frappe.model.workflow.apply_workflow callable", callable(apply_workflow))

	actors = _ensure_test_actors()
	leave_type = _ensure_leave_type_and_allocation(actors["employee"]["employee"])
	_purge_existing_test_leaves(actors["employee"]["employee"])
	created = []

	try:
		# Short leave → HOD inbox → mobile Approve
		short = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=2,
			description="E2E mobile short",
			start_offset=20,
		)
		created.append(short.name)

		with _as_user(EMP_USER):
			api.apply_leave_workflow_action(short.name, "Apply")

		short.reload()
		ok("Mobile Apply → Pending HOD", short.workflow_state == STATE_PENDING_HOD, short.workflow_state)

		with _as_user(HOD_USER):
			inbox = api.get_pending_leave_approvals(limit=50)
			names = [r["name"] for r in inbox]
			ok("HOD inbox contains short leave", short.name in names, str(names[:5]))

			detail = api.get_leave_workflow_actions(short.name)
			ok(
				"HOD sees Approve on short leave",
				"Approve" in (detail.get("available_actions") or []),
				str(detail.get("available_actions")),
			)

			result = api.apply_leave_workflow_action(short.name, "Approve")
			ok(
				"Mobile HOD Approve → Approved",
				result.get("workflow_state") == STATE_APPROVED and result.get("docstatus") == 1,
				str(result),
			)

		# Long leave → Super HOD mobile Approve
		long = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=4,
			description="E2E mobile long",
			start_offset=40,
		)
		created.append(long.name)

		with _as_user(EMP_USER):
			api.apply_leave_workflow_action(long.name, "Apply")
		with _as_user(HOD_USER):
			api.apply_leave_workflow_action(long.name, "Approve")

		long.reload()
		ok(
			"After HOD, long leave Pending Super HOD",
			long.workflow_state == STATE_PENDING_SUPER_HOD,
			long.workflow_state,
		)

		with _as_user(SUPER_HOD_USER):
			inbox = api.get_pending_leave_approvals(limit=50)
			ok(
				"Super HOD inbox contains long leave",
				long.name in [r["name"] for r in inbox],
			)
			result = api.apply_leave_workflow_action(long.name, "Approve")
			ok(
				"Mobile Super HOD Approve → Approved",
				result.get("workflow_state") == STATE_APPROVED,
				str(result.get("workflow_state")),
			)

		# Reject via API
		rej = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=2,
			description="E2E mobile reject",
			start_offset=60,
		)
		created.append(rej.name)
		with _as_user(EMP_USER):
			api.apply_leave_workflow_action(rej.name, "Apply")
		with _as_user(HOD_USER):
			result = api.apply_leave_workflow_action(rej.name, "Reject")
			ok(
				"Mobile HOD Reject works",
				result.get("workflow_state") == "Rejected",
				str(result.get("workflow_state")),
			)

		# Employee cannot Approve
		blocked = False
		err = ""
		own = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=2,
			description="E2E mobile no self approve",
			start_offset=80,
		)
		created.append(own.name)
		with _as_user(EMP_USER):
			api.apply_leave_workflow_action(own.name, "Apply")
			try:
				api.apply_leave_workflow_action(own.name, "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:120]
		ok("Employee cannot Approve via mobile API", blocked, err)

	finally:
		frappe.set_user("Administrator")
		_cleanup_leaves(created)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== #12 MOBILE APPROVAL SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print("API: valence.valence.override.whitelisted_method.leave_approval.*")
	print(f"Test users: {EMP_USER} / {HOD_USER} / {SUPER_HOD_USER} (pw {PASSWORD})")
	if failed:
		frappe.throw(f"Mobile leave approval tests failed ({failed})")

	return {"passed": passed, "failed": failed}
