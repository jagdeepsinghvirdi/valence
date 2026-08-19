"""
End-to-end test for #4 Leave Application Super HOD workflow.

Creates minimal actors (employee / HOD / Super HOD), runs real workflow
transitions, validates status + notifications, then cleans up test leaves.

  bench --site valence.localhost execute valence.valence.doc_events.test_leave_workflow_e2e.run
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
	WORKFLOW_NAME,
	ensure_leave_application_workflow,
)

EMP_USER = "e2e.employee@valence.test"
HOD_USER = "e2e.hod@valence.test"
SUPER_HOD_USER = "e2e.superhod@valence.test"
PASSWORD = "Test@Leave123"

# Future leaves: HOD-only. Super HOD tests use backdated offsets.
FROM_OFFSET_DAYS = 10
BACKDATED_LONG_OFFSET = -40
BACKDATED_REJECT_OFFSET = -55



def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")
	ensure_leave_application_workflow()

	ok(
		"Workflow active on Leave Application",
		get_workflow_name("Leave Application") == WORKFLOW_NAME,
		str(get_workflow_name("Leave Application")),
	)

	actors = _ensure_test_actors()
	ok("Test actors ready", all(actors.values()), str({k: v.get("employee") for k, v in actors.items()}))

	leave_type = _ensure_leave_type_and_allocation(actors["employee"]["employee"])
	ok("Leave type + allocation ready", bool(leave_type), leave_type)

	_purge_existing_test_leaves(actors["employee"]["employee"])

	created_names = []

	try:
		# ------ SHORT LEAVE (< 3 days): apply → HOD approve → Approved ------
		short = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=2,
			description="E2E short leave",
			start_offset=FROM_OFFSET_DAYS,
		)
		created_names.append(short.name)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Leave Application", short.name)
			apply_workflow(doc, "Apply")

		short.reload()
		ok(
			"Short: Apply → Pending HOD",
			short.workflow_state == STATE_PENDING_HOD and short.status == "Open",
			f"state={short.workflow_state} status={short.status} working_days={short.get('custom_working_leave_days')}",
		)

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Leave Application", short.name)
			apply_workflow(doc, "Approve")

		short.reload()
		ok(
			"Short: HOD Approve → Approved (submitted)",
			short.workflow_state == STATE_APPROVED
			and short.status == "Approved"
			and short.docstatus == 1,
			f"state={short.workflow_state} status={short.status} docstatus={short.docstatus}",
		)

		# ------ FUTURE LONG LEAVE: HOD only (no Super HOD) ------
		future_long = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=4,
			description="E2E future long leave",
			start_offset=FROM_OFFSET_DAYS + 15,
		)
		created_names.append(future_long.name)

		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", future_long.name), "Apply")
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", future_long.name), "Approve")

		future_long.reload()
		ok(
			"Future long: HOD Approve → Approved (no Super HOD)",
			future_long.workflow_state == STATE_APPROVED
			and future_long.status == "Approved"
			and future_long.docstatus == 1,
			f"state={future_long.workflow_state} status={future_long.status}",
		)

		# ------ BACKDATED 3 WORKING DAYS: Super HOD (3 or more) ------
		three = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=3,
			description="E2E backdated 3-day leave",
			start_offset=BACKDATED_LONG_OFFSET - 10,
		)
		created_names.append(three.name)

		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", three.name), "Apply")
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", three.name), "Approve")

		three.reload()
		ok(
			"Backdated 3 days: HOD Approve → Pending Super HOD",
			three.workflow_state == STATE_PENDING_SUPER_HOD and three.docstatus == 0,
			f"state={three.workflow_state} status={three.status}",
		)

		# Super HOD must be able to OPEN the document (tester defect: permission denied)
		open_ok = True
		open_err = ""
		with _as_user(SUPER_HOD_USER):
			try:
				frappe.get_doc("Leave Application", three.name)
			except Exception as e:
				open_ok = False
				open_err = str(e)[:160]
		ok("Super HOD can open leave at Pending Super HOD", open_ok, open_err)

		shared = frappe.db.exists(
			"DocShare",
			{
				"share_doctype": "Leave Application",
				"share_name": three.name,
				"user": SUPER_HOD_USER,
			},
		)
		ok("Leave is shared with Super HOD user", bool(shared), str(shared))

		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", three.name), "Approve")
		three.reload()
		ok(
			"Backdated 3 days: Super HOD Approve → Approved",
			three.workflow_state == STATE_APPROVED and three.docstatus == 1,
			f"state={three.workflow_state}",
		)

		# ------ BACKDATED LONG LEAVE (> 3 working days): apply → HOD → Super HOD → Approved ------
		long = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=4,
			description="E2E backdated long leave",
			start_offset=BACKDATED_LONG_OFFSET,
		)
		created_names.append(long.name)

		with _as_user(EMP_USER):
			doc = frappe.get_doc("Leave Application", long.name)
			apply_workflow(doc, "Apply")

		long.reload()
		ok(
			"Long: Apply → Pending HOD",
			long.workflow_state == STATE_PENDING_HOD,
			f"state={long.workflow_state} working_days={long.get('custom_working_leave_days')}",
		)

		with _as_user(HOD_USER):
			doc = frappe.get_doc("Leave Application", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Backdated long: HOD Approve → Pending Super HOD",
			long.workflow_state == STATE_PENDING_SUPER_HOD and long.docstatus == 0,
			f"state={long.workflow_state} status={long.status}",
		)

		# Super HOD ToDo for SUPER_HOD_USER (and any Super HOD / HR Manager user)
		todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Leave Application",
				"reference_name": long.name,
				"status": "Open",
			},
			fields=["name", "allocated_to"],
		)
		todo_users = {t.allocated_to for t in todos}
		ok(
			"Backdated long: Super HOD ToDo created",
			SUPER_HOD_USER in todo_users,
			f"todos={list(todo_users)}",
		)

		with _as_user(SUPER_HOD_USER):
			doc = frappe.get_doc("Leave Application", long.name)
			apply_workflow(doc, "Approve")

		long.reload()
		ok(
			"Backdated long: Super HOD Approve → Approved",
			long.workflow_state == STATE_APPROVED
			and long.status == "Approved"
			and long.docstatus == 1,
			f"state={long.workflow_state} status={long.status}",
		)

		# ------ REJECT path at HOD for long leave-style app (use 4 days) ------
		rej = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=4,
			description="E2E reject at HOD",
			start_offset=FROM_OFFSET_DAYS + 30,
		)
		created_names.append(rej.name)

		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej.name), "Apply")

		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej.name), "Reject")

		rej.reload()
		ok(
			"Reject: HOD Reject → Rejected (submitted)",
			rej.workflow_state == STATE_REJECTED
			and rej.status == "Rejected"
			and rej.docstatus == 1,
			f"state={rej.workflow_state} status={rej.status}",
		)

		# ------ REJECT path at Super HOD ------
		rej2 = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=5,
			description="E2E reject at Super HOD",
			start_offset=BACKDATED_REJECT_OFFSET,
		)
		created_names.append(rej2.name)

		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej2.name), "Apply")
		with _as_user(HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej2.name), "Approve")

		rej2.reload()
		ok(
			"Reject-SH: still Pending Super HOD before reject",
			rej2.workflow_state == STATE_PENDING_SUPER_HOD,
			rej2.workflow_state,
		)

		with _as_user(SUPER_HOD_USER):
			apply_workflow(frappe.get_doc("Leave Application", rej2.name), "Reject")

		rej2.reload()
		ok(
			"Reject-SH: Super HOD Reject → Rejected",
			rej2.workflow_state == STATE_REJECTED and rej2.status == "Rejected",
			f"state={rej2.workflow_state} status={rej2.status}",
		)

		# ------ Self-approval blocked at HOD ------
		owned = _new_leave(
			actors["employee"]["employee"],
			leave_type,
			days=1,
			description="E2E self-approval guard",
			start_offset=FROM_OFFSET_DAYS + 60,
		)
		created_names.append(owned.name)
		# Make HOD the owner then apply as employee then try approve as owner
		frappe.db.set_value("Leave Application", owned.name, "owner", HOD_USER)
		with _as_user(EMP_USER):
			apply_workflow(frappe.get_doc("Leave Application", owned.name), "Apply")

		self_blocked = False
		err = ""
		with _as_user(HOD_USER):
			try:
				apply_workflow(frappe.get_doc("Leave Application", owned.name), "Approve")
			except Exception as e:
				self_blocked = "Self approval" in str(e) or "not allowed" in str(e).lower()
				err = str(e)[:160]
		ok("Self-approval blocked for document owner at Approve", self_blocked, err)

		# ------ System leave finalize still works with workflow ------
		from valence.valence.doc_events.leave_application import finalize_system_leave_application

		sys_leave = frappe.new_doc("Leave Application")
		sys_leave.employee = actors["employee"]["employee"]
		sys_leave.leave_type = leave_type
		sys_leave.from_date = add_days(getdate(), FROM_OFFSET_DAYS + 75)
		sys_leave.to_date = sys_leave.from_date
		sys_leave.half_day = 1
		sys_leave.half_day_date = sys_leave.from_date
		sys_leave.total_leave_days = 0.5
		sys_leave.description = "E2E system short leave finalize"
		sys_leave = finalize_system_leave_application(sys_leave)
		created_names.append(sys_leave.name)
		sys_leave.reload()
		ok(
			"System leave finalize: Approved + submitted under workflow",
			sys_leave.workflow_state == STATE_APPROVED
			and sys_leave.status == "Approved"
			and sys_leave.docstatus == 1,
			f"state={sys_leave.workflow_state} status={sys_leave.status}",
		)

		# ------ Short leave must NOT create Super HOD ToDo ------
		bad_todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Leave Application",
				"reference_name": short.name,
				"status": "Open",
			},
		)
		ok("Short leave has no Super HOD ToDo", len(bad_todos) == 0, str(bad_todos))

	except Exception as e:
		ok("E2E suite ran without exception", False, f"{type(e).__name__}: {e}")
		frappe.log_error(title="Leave workflow E2E", message=frappe.get_traceback())
		raise
	finally:
		frappe.set_user("Administrator")
		_cleanup_leaves(created_names)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== E2E SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	print("Actors (kept for UI testing):")
	print(f"  Employee   {EMP_USER} / {PASSWORD}")
	print(f"  HOD        {HOD_USER} / {PASSWORD}")
	print(f"  Super HOD  {SUPER_HOD_USER} / {PASSWORD}")
	if failed:
		frappe.throw(
			f"Leave workflow E2E failed ({failed}): {[n for s, n, _ in results if s == 'FAIL']}"
		)
	return {"passed": passed, "failed": failed, "actors": [EMP_USER, HOD_USER, SUPER_HOD_USER]}


def _ensure_holiday_list(company):
	"""Leave submit requires holiday list on employee or company."""
	name = "E2E Holiday List"
	if not frappe.db.exists("Holiday List", name):
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": name,
				"from_date": f"{getdate().year}-01-01",
				"to_date": f"{getdate().year}-12-31",
			}
		).insert(ignore_permissions=True)

	# Company default
	if frappe.db.has_column("Company", "default_holiday_list"):
		frappe.db.set_value("Company", company, "default_holiday_list", name)

	return name


def _ensure_test_actors():
	"""Create employee, HOD, Super HOD users + employees; wire leave_approver."""
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	if not company:
		frappe.throw("No Company found — create a Company first")

	holiday_list = _ensure_holiday_list(company)

	# Users
	_ensure_user(EMP_USER, "E2E", "Employee", ["Employee"])
	_ensure_user(HOD_USER, "E2E", "HOD", ["Employee", "Leave Approver"])
	_ensure_user(SUPER_HOD_USER, "E2E", "SuperHOD", ["Employee", "Super HOD"])

	# Shared department so HOD list/form access works with #5 dept scoping
	dept = _ensure_department("E2E Leave Dept", company)

	# Employees
	emp = _ensure_employee("E2E Employee", EMP_USER, company, holiday_list=holiday_list)
	hod = _ensure_employee("E2E HOD", HOD_USER, company, holiday_list=holiday_list)
	super_emp = _ensure_employee("E2E Super HOD", SUPER_HOD_USER, company, holiday_list=holiday_list)

	# Employee reports leave to HOD user as leave_approver
	frappe.db.set_value("Employee", emp, "leave_approver", HOD_USER)
	frappe.db.set_value("Employee", emp, "user_id", EMP_USER)
	frappe.db.set_value("Employee", emp, "holiday_list", holiday_list)
	frappe.db.set_value("Employee", emp, "department", dept)
	frappe.db.set_value("Employee", hod, "user_id", HOD_USER)
	frappe.db.set_value("Employee", hod, "holiday_list", holiday_list)
	frappe.db.set_value("Employee", hod, "department", dept)
	frappe.db.set_value("Employee", super_emp, "user_id", SUPER_HOD_USER)
	frappe.db.set_value("Employee", super_emp, "holiday_list", holiday_list)

	frappe.db.commit()
	return {
		"employee": {"user": EMP_USER, "employee": emp, "department": dept},
		"hod": {"user": HOD_USER, "employee": hod, "department": dept},
		"super_hod": {"user": SUPER_HOD_USER, "employee": super_emp},
	}


def _ensure_user(email, first, last, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
				"new_password": PASSWORD,
				"user_type": "System User",
			}
		)
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.enabled = 1
		user.save(ignore_permissions=True)

	# Reset password every run so UI login is reliable
	from frappe.utils.password import update_password

	update_password(email, PASSWORD)

	user = frappe.get_doc("User", email)
	# Strip privilege that would skip self-approval / HR exceptions unintentionally for employee actor
	for r in ("System Manager", "HR Manager", "HR User", "Administrator"):
		if r not in roles:
			user.remove_roles(r)
	for r in roles:
		user.add_roles(r)
	frappe.db.commit()


def _ensure_employee(full_name, user_id, company, leave_approver=None, holiday_list=None):
	existing = frappe.db.get_value("Employee", {"user_id": user_id}, "name")
	if existing:
		if holiday_list:
			frappe.db.set_value("Employee", existing, "holiday_list", holiday_list)
		return existing

	# Prefer matching by employee_name for re-runs
	existing = frappe.db.get_value("Employee", {"employee_name": full_name}, "name")
	if existing:
		frappe.db.set_value("Employee", existing, "user_id", user_id)
		if leave_approver:
			frappe.db.set_value("Employee", existing, "leave_approver", leave_approver)
		if holiday_list:
			frappe.db.set_value("Employee", existing, "holiday_list", holiday_list)
		return existing

	parts = full_name.split(" ", 1)
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": parts[0],
			"last_name": parts[1] if len(parts) > 1 else "",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": nowdate(),
			"status": "Active",
			"company": company,
			"user_id": user_id,
			"leave_approver": leave_approver,
			"holiday_list": holiday_list,
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_leave_type_and_allocation(employee):
	"""Prefer LWP (often no allocation needed); still allocate for safety."""
	leave_type = "Leave Without Pay"
	if not frappe.db.exists("Leave Type", leave_type):
		leave_type = frappe.db.get_value("Leave Type", {}, "name")

	# Allocation optional for LWP if is_lwp
	is_lwp = frappe.db.get_value("Leave Type", leave_type, "is_lwp")
	if not is_lwp:
		from_date = getdate()
		to_date = add_days(from_date, 365)
		exists = frappe.db.exists(
			"Leave Allocation",
			{
				"employee": employee,
				"leave_type": leave_type,
				"docstatus": 1,
				"from_date": ["<=", to_date],
				"to_date": [">=", from_date],
			},
		)
		if not exists:
			alloc = frappe.get_doc(
				{
					"doctype": "Leave Allocation",
					"employee": employee,
					"leave_type": leave_type,
					"from_date": from_date,
					"to_date": to_date,
					"new_leaves_allocated": 30,
				}
			)
			alloc.insert(ignore_permissions=True)
			alloc.submit()

	return leave_type


def _ensure_department(name, company):
	existing = frappe.db.get_value("Department", {"department_name": name, "company": company}, "name")
	if existing:
		return existing
	if frappe.db.exists("Department", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Department",
			"department_name": name,
			"company": company,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _new_leave(employee, leave_type, days, description, start_offset=None):
	"""Create leave draft; force custom_working_leave_days for workflow routing tests.

	`days` here means intended working-day count for Super HOD threshold tests
	(backdated + above threshold → Super HOD; future / ≤ threshold → HOD only).
	"""
	if start_offset is None:
		start_offset = FROM_OFFSET_DAYS

	from_date = add_days(getdate(), start_offset)
	# Use calendar span ~= days so HRMS is happy; then force working-days field
	to_date = add_days(from_date, max(days - 1, 0))

	emp_fields = frappe.db.get_value(
		"Employee", employee, ["leave_approver", "department"], as_dict=True
	) or frappe._dict()

	doc = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"leave_type": leave_type,
			"from_date": from_date,
			"to_date": to_date,
			"description": description,
			"status": "Open",
			"leave_approver": emp_fields.leave_approver or HOD_USER,
			"department": emp_fields.department,
		}
	)

	prev_present = getattr(frappe.flags, "ignore_present_day_leave_restriction", False)
	prev_window = getattr(frappe.flags, "ignore_leave_creation_window", False)
	if getdate(from_date) < getdate():
		frappe.flags.ignore_present_day_leave_restriction = True
		frappe.flags.ignore_leave_creation_window = True
	try:
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.ignore_present_day_leave_restriction = prev_present
		frappe.flags.ignore_leave_creation_window = prev_window
	doc.reload()

	# Pin working-days field used by workflow conditions
	frappe.db.set_value(
		"Leave Application",
		doc.name,
		{
			"custom_working_leave_days": float(days),
			"total_leave_days": float(days),
		},
		update_modified=False,
	)
	doc.reload()
	return doc


def _purge_existing_test_leaves(employee):
	"""Remove leftover E2E/QA leave docs so re-runs do not hit overlap errors."""
	names = frappe.get_all(
		"Leave Application",
		filters={"employee": employee},
		pluck="name",
	)
	_cleanup_leaves(names)


@contextmanager
def _as_user(user):
	prev = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(prev)


def _cleanup_leaves(names):
	"""Cancel/delete test leave applications; keep users for UI retest."""
	for name in names:
		if not name or not frappe.db.exists("Leave Application", name):
			continue
		try:
			# Close related todos
			for todo in frappe.get_all(
				"ToDo",
				filters={"reference_type": "Leave Application", "reference_name": name},
				pluck="name",
			):
				frappe.delete_doc("ToDo", todo, force=1, ignore_permissions=True)

			doc = frappe.get_doc("Leave Application", name)
			if doc.docstatus == 1:
				# Cancel may need workflow; force via db for cleanup
				frappe.db.set_value(
					"Leave Application",
					name,
					{"docstatus": 2, "status": "Cancelled", "workflow_state": "Rejected"},
					update_modified=False,
				)
				try:
					doc = frappe.get_doc("Leave Application", name)
					doc.run_method("on_cancel")
				except Exception:
					pass
			frappe.delete_doc("Leave Application", name, force=1, ignore_permissions=True)
		except Exception as e:
			print(f"[WARN] cleanup {name}: {e}")
	frappe.db.commit()
