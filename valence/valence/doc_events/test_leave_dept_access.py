"""Automated checks for #5 department-wise leave access. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_leave_dept_access.run
"""

from __future__ import annotations

import frappe
from frappe.utils import nowdate


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	from valence.valence.override.query import (
		leave_application_has_permission,
		leave_application_query,
		_has_unrestricted_leave_access,
	)

	frappe.set_user("Administrator")

	# 1) Hooks wired
	pqc = frappe.get_hooks("permission_query_conditions") or {}
	hp = frappe.get_hooks("has_permission") or {}
	ok(
		"permission_query_conditions registered for Leave Application",
		"valence.valence.override.query.leave_application_query"
		in (pqc.get("Leave Application") or []),
		str(pqc.get("Leave Application")),
	)
	ok(
		"has_permission registered for Leave Application",
		"valence.valence.override.query.leave_application_has_permission"
		in (hp.get("Leave Application") or []),
		str(hp.get("Leave Application")),
	)

	# 2) HR / System unrestricted
	ok("Administrator unrestricted", _has_unrestricted_leave_access("Administrator") is True)
	ok(
		"Administrator query is empty (full list)",
		leave_application_query("Administrator") == "",
		leave_application_query("Administrator")[:80],
	)

	# 3) Seed two departments + employees if possible
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	if not company:
		ok("Company available for dept seed", False, "No Company — skip data checks")
		_print_summary(results)
		return {"results": results}

	dept_a = _ensure_department("E2E Dept A", company)
	dept_b = _ensure_department("E2E Dept B", company)
	ok("Two test departments exist", bool(dept_a and dept_b), f"{dept_a} / {dept_b}")

	user_a = "e2e.dept.a@valence.test"
	user_b = "e2e.dept.b@valence.test"
	_ensure_user(user_a, "Dept", "A", ["Employee"])
	_ensure_user(user_b, "Dept", "B", ["Employee"])

	emp_a = _ensure_employee("E2E Dept A Emp", user_a, company, dept_a)
	emp_b = _ensure_employee("E2E Dept B Emp", user_b, company, dept_b)
	ok("Employees linked to departments", bool(emp_a and emp_b), f"{emp_a} / {emp_b}")

	q_a = leave_application_query(user_a)
	q_b = leave_application_query(user_b)
	ok("Dept A user gets a restrictive query", bool(q_a) and dept_a in q_a, q_a[:160])
	ok("Dept B user gets a restrictive query", bool(q_b) and dept_b in q_b, q_b[:160])
	ok("Dept A query mentions dept A", dept_a in q_a)
	ok("Dept A query does not mention dept B only as filter", dept_b not in q_a)

	# 4) has_permission by department
	fake_a = frappe._dict(
		{
			"doctype": "Leave Application",
			"employee": emp_a,
			"department": dept_a,
			"leave_approver": None,
			"owner": "Administrator",
		}
	)
	fake_b = frappe._dict(
		{
			"doctype": "Leave Application",
			"employee": emp_b,
			"department": dept_b,
			"leave_approver": None,
			"owner": "Administrator",
		}
	)
	ok(
		"Dept A user can read same-dept leave",
		leave_application_has_permission(fake_a, "read", user_a) is True,
	)
	ok(
		"Dept A user cannot read other-dept leave",
		leave_application_has_permission(fake_b, "read", user_a) is False,
	)
	ok(
		"Leave approver can read cross-dept leave",
		leave_application_has_permission(
			frappe._dict(
				{
					"employee": emp_b,
					"department": dept_b,
					"leave_approver": user_a,
					"owner": "nobody@example.com",
				}
			),
			"read",
			user_a,
		)
		is True,
	)

	# Approver via Employee master (form field blank) — HOD approve path
	frappe.db.set_value("Employee", emp_b, "leave_approver", user_a)
	ok(
		"Employee.leave_approver grants cross-dept read when leave field blank",
		leave_application_has_permission(
			frappe._dict(
				{
					"employee": emp_b,
					"department": dept_b,
					"leave_approver": None,
					"owner": "nobody@example.com",
				}
			),
			"read",
			user_a,
		)
		is True,
	)
	# Reset so later tests / re-runs stay isolated
	frappe.db.set_value("Employee", emp_b, "leave_approver", None)
	frappe.db.commit()

	# 5) HR Manager role unrestricted if present on any user — test role set via mock roles list
	# Use _has_unrestricted with a dedicated HR-ish check: Administrator already covered
	# Simulate: attach HR Manager to a throwaway and remove after? Prefer pure function path.
	hr_roles_ok = "HR Manager" in frappe.get_all("Role", pluck="name")
	ok("HR Manager role exists in system", hr_roles_ok)

	# Guest denied
	ok("Guest query is denied", leave_application_query("Guest") == "1=0")

	_print_summary(results)
	return {"results": results, "failed": sum(1 for s, _, _ in results if s == "FAIL")}


def _print_summary(results):
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print(f"\n=== #5 department access: {len(results) - failed}/{len(results)} passed ===")
	if failed:
		print("FAILED:")
		for s, name, detail in results:
			if s == "FAIL":
				print(f"  - {name}: {detail}")


def _ensure_department(name, company):
	if frappe.db.exists("Department", name):
		return name
	# Company-specific department names sometimes include company suffix
	existing = frappe.db.get_value("Department", {"department_name": name}, "name")
	if existing:
		return existing
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


def _ensure_user(email, first, last, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
				"new_password": "Test@12345",
				"user_type": "System User",
			}
		)
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.enabled = 1
		user.save(ignore_permissions=True)

	user = frappe.get_doc("User", email)
	for r in ("System Manager", "HR Manager", "HR User", "Administrator", "Super HOD"):
		if r not in roles:
			user.remove_roles(r)
	for r in roles:
		user.add_roles(r)
	frappe.db.commit()


def _ensure_employee(full_name, user_id, company, department):
	existing = frappe.db.get_value("Employee", {"user_id": user_id}, "name")
	if existing:
		frappe.db.set_value("Employee", existing, "department", department)
		frappe.db.commit()
		return existing

	existing = frappe.db.get_value("Employee", {"employee_name": full_name}, "name")
	if existing:
		frappe.db.set_value("Employee", existing, "user_id", user_id)
		frappe.db.set_value("Employee", existing, "department", department)
		frappe.db.commit()
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
			"department": department,
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
