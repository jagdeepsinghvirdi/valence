"""
Extended Leave Approval Workflow — acceptance tests from the client PDF.

Covers Leave Application + OD/WFH (Attendance Request):
- No self-approval (Employee / HOD / Super HOD), even with Leave Approver role
- Assigned leave_approver can approve; other-department Leave Approver cannot
- Same-department Leave Approver (HOD) can approve (Desk Actions)
- Super HOD with no higher approver → HR
- No HR → Administrator (DBA)
- Rules apply to pending docs and mobile API path

  bench --site valence.localhost execute valence.valence.doc_events.test_extended_leave_approval.run
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, getdate

from valence.valence.approval_hierarchy import (
	get_effective_leave_approver,
	get_raw_leave_approver,
	patch_workflow_approval_access,
	resolve_hod_stage_routing,
	user_may_approve_or_reject,
)
from valence.valence.doc_events.test_leave_workflow_e2e import (
	EMP_USER,
	HOD_USER,
	SUPER_HOD_USER,
	_as_user,
	_ensure_department,
	_ensure_employee,
	_ensure_leave_type_and_allocation,
	_ensure_test_actors,
	_ensure_user,
	_new_leave,
	_purge_existing_test_leaves,
)
from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
	ensure_leave_application_workflow,
)
from valence.valence.setup.od_wfh_workflow import ensure_od_wfh_workflow

HR_USER = "e2e.hr@valence.test"
OTHER_HOD_USER = "e2e.otherhod@valence.test"
SAME_DEPT_HOD_USER = "e2e.samedept.hod@valence.test"

FROM_OFFSET = 120  # far from OD/WFH e2e dates (0–20) to avoid overlap


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")
	patch_workflow_approval_access()
	ensure_leave_application_workflow()
	ensure_od_wfh_workflow()
	cleanup_e2e_attendance_requests()

	actors = _ensure_test_actors()
	_ensure_user(HR_USER, "E2E", "HR", ["Employee", "HR Manager"])
	_ensure_user(OTHER_HOD_USER, "E2E", "OtherHOD", ["Employee", "Leave Approver"])
	_ensure_user(SAME_DEPT_HOD_USER, "E2E", "SameDeptHOD", ["Employee", "Leave Approver"])

	# Wire hierarchy: emp → HOD → Super HOD; HOD's leave goes to Super HOD
	emp = actors["employee"]["employee"]
	hod_emp = actors["hod"]["employee"]
	super_emp = actors["super_hod"]["employee"]
	company = frappe.db.get_value("Employee", emp, "company")
	holiday_list = frappe.db.get_value("Employee", emp, "holiday_list")
	dept = actors["employee"].get("department") or frappe.db.get_value("Employee", emp, "department")

	# HR as employee (for self-approval-as-HR case)
	hr_emp = _ensure_employee("E2E HR Emp", HR_USER, company, holiday_list=holiday_list)
	frappe.db.set_value("Employee", hr_emp, "user_id", HR_USER)
	frappe.db.set_value("Employee", hr_emp, "leave_approver", HOD_USER)
	frappe.db.set_value("Employee", hr_emp, "department", dept)
	frappe.db.set_value("Employee", hr_emp, "holiday_list", holiday_list)

	# Other-department HOD (Leave Approver role only — must NOT get Actions)
	other_dept = _ensure_department("E2E Other Dept Ext", company)
	other_hod_emp = _ensure_employee(
		"E2E Other Dept HOD", OTHER_HOD_USER, company, holiday_list=holiday_list
	)
	frappe.db.set_value("Employee", other_hod_emp, "department", other_dept)

	# Same-department backup HOD (not named leave_approver — must get Actions)
	same_dept_hod_emp = _ensure_employee(
		"E2E Same Dept HOD", SAME_DEPT_HOD_USER, company, holiday_list=holiday_list
	)
	frappe.db.set_value("Employee", same_dept_hod_emp, "department", dept)

	frappe.db.set_value("Employee", emp, "leave_approver", HOD_USER)
	frappe.db.set_value("Employee", hod_emp, "leave_approver", SUPER_HOD_USER)
	# Super HOD has no higher approver (self) → must fall back to HR / Admin
	frappe.db.set_value("Employee", super_emp, "leave_approver", SUPER_HOD_USER)
	frappe.db.commit()

	leave_type = _ensure_leave_type_and_allocation(emp)
	_ensure_leave_type_and_allocation(hod_emp)
	_ensure_leave_type_and_allocation(super_emp)
	_ensure_leave_type_and_allocation(hr_emp)
	_purge_existing_test_leaves(emp)
	_purge_existing_test_leaves(hod_emp)
	_purge_existing_test_leaves(super_emp)
	_purge_existing_test_leaves(hr_emp)

	created = []

	try:
		# --- Routing helpers ---
		ok(
			"Employee effective leave approver is HOD",
			get_effective_leave_approver(emp) == HOD_USER,
			str(get_effective_leave_approver(emp)),
		)
		ok(
			"HOD effective leave approver is Super HOD",
			get_effective_leave_approver(hod_emp) == SUPER_HOD_USER,
			str(get_effective_leave_approver(hod_emp)),
		)
		routing = resolve_hod_stage_routing(super_emp)
		ok(
			"Super HOD with self leave_approver routes to HR (or Admin)",
			routing["level"] in ("hr", "administrator"),
			str(routing),
		)

		# --- Example 1: Employee cannot self-approve even with Leave Approver role ---
		emp_leave = _new_leave(
			emp, leave_type, days=1, description="EXT emp self", start_offset=FROM_OFFSET
		)
		created.append(emp_leave.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", emp_leave.name), "Apply")

		# Temporarily give employee Leave Approver role
		frappe.get_doc("User", EMP_USER).add_roles("Leave Approver")
		frappe.db.commit()
		blocked = False
		err = ""
		with _as_user(EMP_USER):
			doc = frappe.get_doc("Leave Application", emp_leave.name)
			ok(
				"Employee with Leave Approver role still cannot Approve (hierarchy)",
				not user_may_approve_or_reject(doc, EMP_USER),
			)
			try:
				apply_workflow(doc, "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("Employee self-approve blocked at Apply path", blocked, err)
		frappe.get_doc("User", EMP_USER).remove_roles("Leave Approver")
		frappe.db.commit()

		# Assigned HOD can approve
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", emp_leave.name), "Approve")
		emp_leave.reload()
		ok(
			"Assigned HOD can approve employee leave",
			emp_leave.workflow_state == STATE_APPROVED,
			emp_leave.workflow_state,
		)

		# --- Wrong Leave Approver (role only) cannot approve ---
		emp_leave2 = _new_leave(
			emp, leave_type, days=1, description="EXT wrong hod", start_offset=FROM_OFFSET + 5
		)
		created.append(emp_leave2.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", emp_leave2.name), "Apply")

		blocked = False
		err = ""
		with _as_user(OTHER_HOD_USER):
			doc = frappe.get_doc("Leave Application", emp_leave2.name)
			ok(
				"Other Leave Approver is not allowed by hierarchy",
				not user_may_approve_or_reject(doc, OTHER_HOD_USER),
			)
			try:
				apply_workflow(doc, "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("Other Leave Approver Approve blocked", blocked, err)

		# --- Same-department HOD sees Actions even when not named leave_approver ---
		same_leave = _new_leave(
			emp,
			leave_type,
			days=1,
			description="EXT same dept hod",
			start_offset=FROM_OFFSET + 7,
		)
		created.append(same_leave.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", same_leave.name), "Apply")
		with _as_user(SAME_DEPT_HOD_USER):
			doc = frappe.get_doc("Leave Application", same_leave.name)
			ok(
				"Same-department HOD may Approve (Desk Actions fix)",
				user_may_approve_or_reject(doc, SAME_DEPT_HOD_USER),
			)
			apply_workflow(doc, "Approve")
		same_leave.reload()
		ok(
			"Same-department HOD can complete Approve",
			same_leave.workflow_state == STATE_APPROVED,
			same_leave.workflow_state,
		)

		# --- Example 2: HOD cannot approve own leave → Super HOD ---
		hod_leave = _new_leave(
			hod_emp, leave_type, days=1, description="EXT hod self", start_offset=FROM_OFFSET + 10
		)
		created.append(hod_leave.name)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", hod_leave.name), "Apply")

		blocked = False
		err = ""
		with _as_user(HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", hod_leave.name), "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("HOD cannot approve own leave", blocked, err)

		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", hod_leave.name), "Approve")
		hod_leave.reload()
		ok(
			"HOD leave approved by assigned Super HOD",
			hod_leave.workflow_state == STATE_APPROVED,
			hod_leave.workflow_state,
		)

		# --- Example 3: Super HOD leave → HR ---
		sh_leave = _new_leave(
			super_emp, leave_type, days=1, description="EXT superhod", start_offset=FROM_OFFSET + 15
		)
		created.append(sh_leave.name)
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", sh_leave.name), "Apply")

		blocked = False
		err = ""
		with _as_user(SUPER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", sh_leave.name), "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("Super HOD cannot approve own leave", blocked, err)

		# Random Leave Approver must not approve Super HOD leave
		blocked = False
		with _as_user(HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", sh_leave.name), "Approve")
			except Exception:
				blocked = True
		ok("HOD cannot approve Super HOD leave (routed to HR)", blocked)

		with _as_user(HR_USER):
			apply_workflow(frappe.get_doc("Leave Application", sh_leave.name), "Approve")
		sh_leave.reload()
		ok(
			"Super HOD leave approved by HR",
			sh_leave.workflow_state == STATE_APPROVED,
			sh_leave.workflow_state,
		)

		# --- Example 4: No HR → Administrator ---
		with patch(
			"valence.valence.approval_hierarchy.get_hr_users",
			return_value=[],
		):
			r = resolve_hod_stage_routing(super_emp)
			ok(
				"No HR → administrator routing",
				r["level"] == "administrator" and r["users"] == ["Administrator"],
				str(r),
			)

			admin_leave = _new_leave(
				super_emp,
				leave_type,
				days=1,
				description="EXT admin fallback",
				start_offset=FROM_OFFSET + 20,
			)
			created.append(admin_leave.name)
			with _as_user(SUPER_HOD_USER):
				apply_workflow(frappe.get_doc("Leave Application", admin_leave.name), "Apply")

			# Hierarchy check under patched get_hr_users
			doc = frappe.get_doc("Leave Application", admin_leave.name)
			ok(
				"Administrator may approve when HR unavailable",
				user_may_approve_or_reject(doc, "Administrator"),
			)
			with _as_user("Administrator"):
				# Keep patch active during approve
				with patch(
					"valence.valence.approval_hierarchy.get_hr_users",
					return_value=[],
				):
					apply_workflow(
						frappe.get_doc("Leave Application", admin_leave.name), "Approve"
					)
			admin_leave.reload()
			ok(
				"Super HOD leave approved by Administrator when no HR",
				admin_leave.workflow_state == STATE_APPROVED,
				admin_leave.workflow_state,
			)

		# --- Pending request: hierarchy still enforced ---
		pending = _new_leave(
			emp, leave_type, days=1, description="EXT pending", start_offset=FROM_OFFSET + 25
		)
		created.append(pending.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", pending.name), "Apply")
		pending.reload()
		ok("Pending leave sits at Pending HOD", pending.workflow_state == STATE_PENDING_HOD)
		blocked = False
		with _as_user(OTHER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", pending.name), "Approve")
			except Exception:
				blocked = True
		ok("Already-pending leave still blocks wrong approver", blocked)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", pending.name), "Approve")
		pending.reload()
		ok("Already-pending leave approved by correct HOD", pending.workflow_state == STATE_APPROVED)

		# --- Mobile API respects hierarchy ---
		from valence.valence.override.whitelisted_method import leave_approval as api

		mob = _new_leave(
			emp, leave_type, days=1, description="EXT mobile", start_offset=FROM_OFFSET + 30
		)
		created.append(mob.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", mob.name), "Apply")

		with _as_user(OTHER_HOD_USER):
			inbox = api.get_pending_leave_approvals()
			names = [r["name"] for r in inbox]
			ok("Mobile inbox excludes leave for wrong Leave Approver", mob.name not in names, str(names))

		with _as_user(HOD_USER):
			inbox = api.get_pending_leave_approvals()
			names = [r["name"] for r in inbox]
			ok("Mobile inbox includes leave for assigned HOD", mob.name in names, str(names))
			api.apply_leave_workflow_action(mob.name, "Approve")
		mob.reload()
		ok("Mobile API Approve by assigned HOD works", mob.workflow_state == STATE_APPROVED)

		# --- OD/WFH same self-approval + hierarchy ---
		od = _new_od(emp, company, start_offset=FROM_OFFSET + 35)
		created.append(("Attendance Request", od.name))
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od.name), "Apply")

		frappe.get_doc("User", EMP_USER).add_roles("Leave Approver")
		frappe.db.commit()
		blocked = False
		err = ""
		with _as_user(EMP_USER):
			try:
				apply_workflow(frappe.get_doc("Attendance Request", od.name), "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("OD/WFH: employee self-approve blocked", blocked, err)
		frappe.get_doc("User", EMP_USER).remove_roles("Leave Approver")
		frappe.db.commit()

		blocked = False
		with _as_user(OTHER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Attendance Request", od.name), "Approve")
			except Exception:
				blocked = True
		ok("OD/WFH: wrong Leave Approver blocked", blocked)

		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od.name), "Approve")
		od.reload()
		ok(
			"OD/WFH: assigned HOD can approve",
			od.workflow_state == STATE_APPROVED,
			od.workflow_state,
		)

		# Super HOD OD → HR
		sh_od = _new_od(super_emp, company, start_offset=FROM_OFFSET + 40)
		created.append(("Attendance Request", sh_od.name))
		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", sh_od.name), "Apply")
		blocked = False
		with _as_user(SUPER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Attendance Request", sh_od.name), "Approve")
			except Exception:
				blocked = True
		ok("OD/WFH: Super HOD self-approve blocked", blocked)
		with _as_user(HR_USER):
			apply_workflow(frappe.get_doc("Attendance Request", sh_od.name), "Approve")
		sh_od.reload()
		ok(
			"OD/WFH: Super HOD request approved by HR",
			sh_od.workflow_state == STATE_APPROVED,
			sh_od.workflow_state,
		)

		# ========== EXTRA EDGE CASES (full PDF coverage) ==========

		# --- HR cannot approve own leave (HR has full authority, but not for self) ---
		hr_leave = _new_leave(
			hr_emp, leave_type, days=1, description="EXT hr self", start_offset=FROM_OFFSET + 45
		)
		created.append(hr_leave.name)
		with _as_user(HR_USER):
			apply_workflow(frappe.get_doc("Leave Application", hr_leave.name), "Apply")
		blocked = False
		err = ""
		with _as_user(HR_USER):
			doc = frappe.get_doc("Leave Application", hr_leave.name)
			ok(
				"HR applicant is not allowed by hierarchy for own leave",
				not user_may_approve_or_reject(doc, HR_USER),
			)
			try:
				apply_workflow(doc, "Approve")
			except Exception as e:
				blocked = True
				err = str(e)[:180]
		ok("HR cannot approve own leave", blocked, err)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", hr_leave.name), "Approve")
		hr_leave.reload()
		ok(
			"HR leave approved by assigned HOD",
			hr_leave.workflow_state == STATE_APPROVED,
			hr_leave.workflow_state,
		)

		# --- Reject: wrong approver blocked; correct HOD can Reject ---
		rej = _new_leave(
			emp, leave_type, days=1, description="EXT reject", start_offset=FROM_OFFSET + 50
		)
		created.append(rej.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej.name), "Apply")
		blocked = False
		with _as_user(OTHER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", rej.name), "Reject")
			except Exception:
				blocked = True
		ok("Reject: wrong Leave Approver blocked", blocked)
		blocked = False
		with _as_user(EMP_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", rej.name), "Reject")
			except Exception:
				blocked = True
		ok("Reject: applicant self-reject blocked", blocked)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej.name), "Reject")
		rej.reload()
		ok(
			"Reject: assigned HOD can Reject",
			rej.workflow_state == STATE_REJECTED,
			rej.workflow_state,
		)

		# --- Super HOD stage: applicant who is Super HOD cannot self-approve ---
		# Give Super HOD a real leave_approver (HOD) so long leave reaches Super HOD stage
		prev_sh_approver = frappe.db.get_value("Employee", super_emp, "leave_approver")
		frappe.db.set_value("Employee", super_emp, "leave_approver", HOD_USER)
		frappe.db.commit()
		try:
			sh_long = _new_leave(
				super_emp,
				leave_type,
				days=4,
				description="EXT sh stage self",
				start_offset=FROM_OFFSET + 55,
			)
			created.append(sh_long.name)
			with _as_user(SUPER_HOD_USER):
				apply_workflow(frappe.get_doc("Leave Application", sh_long.name), "Apply")
			with _as_user(HOD_USER):
				apply_workflow(frappe.get_doc("Leave Application", sh_long.name), "Approve")
			sh_long.reload()
			ok(
				"Long Super HOD leave reaches Pending Super HOD",
				sh_long.workflow_state == STATE_PENDING_SUPER_HOD,
				sh_long.workflow_state,
			)
			blocked = False
			err = ""
			with _as_user(SUPER_HOD_USER):
				doc = frappe.get_doc("Leave Application", sh_long.name)
				ok(
					"Super HOD stage: applicant cannot Approve (hierarchy)",
					not user_may_approve_or_reject(doc, SUPER_HOD_USER),
				)
				try:
					apply_workflow(doc, "Approve")
				except Exception as e:
					blocked = True
					err = str(e)[:180]
			ok("Super HOD stage: self-approve blocked", blocked, err)
			with _as_user(HR_USER):
				apply_workflow(frappe.get_doc("Leave Application", sh_long.name), "Approve")
			sh_long.reload()
			ok(
				"Super HOD stage: HR can Approve applicant's long leave",
				sh_long.workflow_state == STATE_APPROVED,
				sh_long.workflow_state,
			)
		finally:
			frappe.db.set_value("Employee", super_emp, "leave_approver", prev_sh_approver or SUPER_HOD_USER)
			frappe.db.commit()

		# --- Department Approver when Employee.leave_approver empty ---
		prev_emp_approver = frappe.db.get_value("Employee", emp, "leave_approver")
		frappe.db.set_value("Employee", emp, "leave_approver", None)
		# Ensure department has OTHER_HOD as department leave approver
		_ensure_department_leave_approver(dept, OTHER_HOD_USER)
		frappe.db.commit()
		try:
			raw = get_raw_leave_approver(emp)
			eff = get_effective_leave_approver(emp)
			ok(
				"Empty Employee.leave_approver falls back to Department Approver",
				raw == OTHER_HOD_USER and eff == OTHER_HOD_USER,
				f"raw={raw} eff={eff}",
			)
			dept_leave = _new_leave(
				emp, leave_type, days=1, description="EXT dept approver", start_offset=FROM_OFFSET + 65
			)
			created.append(dept_leave.name)
			# Force leave_approver field on doc to match department resolution
			frappe.db.set_value("Leave Application", dept_leave.name, "leave_approver", OTHER_HOD_USER)
			with _as_user(EMP_USER):
				apply_workflow(frappe.get_doc("Leave Application", dept_leave.name), "Apply")
			blocked = False
			with _as_user(HOD_USER):
				try:
					apply_workflow(frappe.get_doc("Leave Application", dept_leave.name), "Approve")
				except Exception:
					blocked = True
			ok("Department Approver path: old HOD blocked", blocked)
			with _as_user(OTHER_HOD_USER):
				apply_workflow(frappe.get_doc("Leave Application", dept_leave.name), "Approve")
			dept_leave.reload()
			ok(
				"Department Approver can approve when Employee.leave_approver empty",
				dept_leave.workflow_state == STATE_APPROVED,
				dept_leave.workflow_state,
			)
		finally:
			frappe.db.set_value("Employee", emp, "leave_approver", prev_emp_approver or HOD_USER)
			frappe.db.commit()

		# --- Desk transitions (get_transitions) hide Approve for wrong/self users ---
		import frappe.model.workflow as workflow_mod
		from valence.valence.approval_hierarchy import share_with_users

		# Ensure emp hierarchy is back to assigned HOD after department-approver case
		frappe.db.set_value("Employee", emp, "leave_approver", HOD_USER)
		_ensure_department_leave_approver(dept, HOD_USER)
		frappe.db.commit()

		desk = _new_leave(
			emp, leave_type, days=1, description="EXT desk transitions", start_offset=FROM_OFFSET + 70
		)
		created.append(desk.name)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", desk.name), "Apply")
		# Share so OTHER_HOD can open the form (Desk would still hide Approve via hierarchy)
		share_with_users(frappe.get_doc("Leave Application", desk.name), [OTHER_HOD_USER, HOD_USER])
		with _as_user(EMP_USER):
			actions = {
				(t.get("action") if isinstance(t, dict) else t.action)
				for t in workflow_mod.get_transitions(frappe.get_doc("Leave Application", desk.name))
			}
			ok(
				"Desk transitions: applicant has no Approve/Reject",
				"Approve" not in actions and "Reject" not in actions,
				str(actions),
			)
		with _as_user(OTHER_HOD_USER):
			doc = frappe.get_doc("Leave Application", desk.name)
			ok(
				"Desk hierarchy: wrong Leave Approver cannot approve",
				not user_may_approve_or_reject(doc, OTHER_HOD_USER),
			)
			actions = {
				(t.get("action") if isinstance(t, dict) else t.action)
				for t in workflow_mod.get_transitions(doc)
			}
			ok(
				"Desk transitions: wrong Leave Approver has no Approve",
				"Approve" not in actions,
				str(actions),
			)
		with _as_user(HOD_USER):
			actions = {
				(t.get("action") if isinstance(t, dict) else t.action)
				for t in workflow_mod.get_transitions(frappe.get_doc("Leave Application", desk.name))
			}
			ok(
				"Desk transitions: assigned HOD sees Approve",
				"Approve" in actions,
				str(actions),
			)
			apply_workflow(frappe.get_doc("Leave Application", desk.name), "Approve")

		# --- OD/WFH: Admin fallback when no HR ---
		with patch("valence.valence.approval_hierarchy.get_hr_users", return_value=[]):
			r = resolve_hod_stage_routing(super_emp)
			ok(
				"OD path routing: no HR → administrator",
				r["level"] == "administrator",
				str(r),
			)
			od_admin = _new_od(super_emp, company, start_offset=FROM_OFFSET + 75)
			created.append(("Attendance Request", od_admin.name))
			with _as_user(SUPER_HOD_USER):
				apply_workflow(frappe.get_doc("Attendance Request", od_admin.name), "Apply")
			doc = frappe.get_doc("Attendance Request", od_admin.name)
			ok(
				"OD/WFH: Administrator may approve when HR unavailable",
				user_may_approve_or_reject(doc, "Administrator"),
			)
			with _as_user("Administrator"):
				with patch("valence.valence.approval_hierarchy.get_hr_users", return_value=[]):
					apply_workflow(
						frappe.get_doc("Attendance Request", od_admin.name), "Approve"
					)
			od_admin.reload()
			ok(
				"OD/WFH: Admin approved Super HOD request when no HR",
				od_admin.workflow_state == STATE_APPROVED,
				od_admin.workflow_state,
			)

		# --- OD/WFH Reject under hierarchy ---
		od_rej = _new_od(emp, company, start_offset=FROM_OFFSET + 80)
		created.append(("Attendance Request", od_rej.name))
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od_rej.name), "Apply")
		blocked = False
		with _as_user(OTHER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Attendance Request", od_rej.name), "Reject")
			except Exception:
				blocked = True
		ok("OD/WFH Reject: wrong Leave Approver blocked", blocked)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od_rej.name), "Reject")
		od_rej.reload()
		ok(
			"OD/WFH Reject: assigned HOD can Reject",
			od_rej.workflow_state == STATE_REJECTED,
			od_rej.workflow_state,
		)

		# --- Pending OD still enforces hierarchy ---
		od_pending = _new_od(emp, company, start_offset=FROM_OFFSET + 85)
		created.append(("Attendance Request", od_pending.name))
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od_pending.name), "Apply")
		blocked = False
		with _as_user(OTHER_HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Attendance Request", od_pending.name), "Approve")
			except Exception:
				blocked = True
		ok("OD/WFH pending: wrong approver still blocked", blocked)
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Attendance Request", od_pending.name), "Approve")
		od_pending.reload()
		ok(
			"OD/WFH pending: correct HOD can still approve",
			od_pending.workflow_state == STATE_APPROVED,
			od_pending.workflow_state,
		)

	except Exception as e:
		ok("Suite ran without exception", False, f"{type(e).__name__}: {e}")
		frappe.log_error(title="Extended leave approval tests", message=frappe.get_traceback())
		raise
	finally:
		frappe.set_user("Administrator")
		_cleanup(created)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== EXTENDED LEAVE APPROVAL SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(
			f"Extended leave approval failed ({failed}): "
			f"{[n for s, n, _ in results if s == 'FAIL']}"
		)
	return {"passed": passed, "failed": failed}


def _new_od(employee, company, start_offset=0):
	day = add_days(getdate(), start_offset)
	doc = frappe.get_doc(
		{
			"doctype": "Attendance Request",
			"employee": employee,
			"company": company,
			"from_date": day,
			"to_date": day,
			"reason": "Work From Home",
			"explanation": "Extended approval OD/WFH test",
			"workflow_state": "Draft",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _cleanup(created):
	for item in created:
		try:
			if isinstance(item, tuple):
				doctype, name = item
			else:
				doctype, name = "Leave Application", item
			if not frappe.db.exists(doctype, name):
				continue
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				try:
					doc.cancel()
				except Exception:
					frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
			frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
		except Exception:
			frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE name=%s", name)
	frappe.db.commit()


def cleanup_e2e_attendance_requests():
	"""Remove leftover Attendance Requests for e2e employees (safe for local QA)."""
	emps = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", [EMP_USER, HOD_USER, SUPER_HOD_USER, HR_USER]]},
		pluck="name",
	)
	if not emps:
		return
	names = frappe.get_all(
		"Attendance Request",
		filters={"employee": ["in", emps]},
		pluck="name",
	)
	_cleanup([("Attendance Request", n) for n in names])


def _ensure_department_leave_approver(department: str | None, approver_user: str):
	"""Set Department.leave_approvers first row to approver_user (HRMS fallback)."""
	if not department:
		return
	dept = frappe.get_doc("Department", department)
	# Clear and set single leave approver
	dept.set("leave_approvers", [])
	dept.append("leave_approvers", {"approver": approver_user})
	dept.save(ignore_permissions=True)
	frappe.db.commit()
