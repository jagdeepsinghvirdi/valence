"""
Permission helpers for list/form access control.

Who can see Leave Application and OD/WFH (Attendance Request):
- Employee: own requests only
- HOD (Leave Approver): own department (plus rows they are leave_approver for)
- Super HOD / HR / System Manager: all

Who can see Employee master (Roster / Dashboard lists — US6 §20):
- Plain Employee: own Employee record only
- HOD (Leave Approver): own + same department tree + leave_approver reports
- Super HOD: own + department tree + leave_approver hierarchy (not full company)
- HR / System Manager / Administrator: all
"""

from __future__ import annotations

import frappe

from valence.valence.approval_hierarchy import SUPER_HOD_ROLE

# Roles that bypass department / own-only scoping on Leave / Attendance Request
UNRESTRICTED_LEAVE_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
		"Administrator",
		"Super HOD",
	}
)

# Full Employee-master access (Roster sees everyone). Super HOD is intentionally
# NOT here — matches Monthly Attendance Dashboard scoping.
UNRESTRICTED_EMPLOYEE_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
	}
)

HOD_ROLES = frozenset({"Leave Approver"})


def attendance_request_query(user: str | None = None) -> str:
	"""OD/WFH list: Super HOD/HR all; HOD department; Employee own."""
	return _request_query("Attendance Request", user)


def attendance_request_has_permission(doc, ptype: str | None = None, user: str | None = None):
	"""OD/WFH form: Super HOD/HR all; HOD department; Employee own."""
	return _request_has_permission(doc, user)


def leave_application_query(user: str | None = None) -> str:
	"""
	Extra WHERE clause for Leave Application list / link queries.

	Returns empty string for unrestricted roles (full access).
	"""
	return _request_query("Leave Application", user)


def leave_application_has_permission(doc, ptype: str | None = None, user: str | None = None):
	"""
	Mirror list scoping when opening a single Leave Application by name/URL.

	Return True/False; return None if doc is incomplete so role perms still apply.
	"""
	return _request_has_permission(doc, user)


def employee_query(user: str | None = None) -> str:
	"""
	US6 §20 — Roster / Employee list scope.

	Empty string = unrestricted. Otherwise restrict to permitted Employee names.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	scope = get_permitted_employee_names(user)
	if scope is None:
		return ""
	if not scope:
		return "1=0"

	names = ", ".join(frappe.db.escape(name) for name in scope)
	return f"`tabEmployee`.`name` in ({names})"


def employee_has_permission(doc, ptype: str | None = None, user: str | None = None):
	"""Mirror Employee list scoping for form open by name/URL."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	if not doc:
		return False

	# New documents → fall through to role DocPerm (HR create, etc.)
	if not getattr(doc, "name", None) or doc.get("__islocal"):
		return None

	scope = get_permitted_employee_names(user)
	if scope is None:
		return True
	return doc.name in scope


def get_permitted_employee_names(user: str | None = None) -> list[str] | None:
	"""
	Employee names the user may see on Roster / Employee lists.

	Returns:
	  None  → unrestricted (HR / Admin)
	  list  → allowed Employee.name values (may be empty)
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return []

	if user == "Administrator":
		return None

	roles = set(frappe.get_roles(user))
	if roles.intersection(UNRESTRICTED_EMPLOYEE_ROLES):
		return None

	employee = _employee_for_user(user)
	scope: set[str] = set()
	if employee and employee.name:
		scope.add(employee.name)

	is_super_hod = SUPER_HOD_ROLE in roles
	if (_is_hod(user) or is_super_hod) and employee and employee.department:
		departments = _department_descendants(employee.department)
		scope.update(
			frappe.get_all(
				"Employee",
				filters={"department": ["in", departments]},
				pluck="name",
			)
		)

	scope.update(_reporting_employees(user))

	if is_super_hod:
		# One level of reports' reports (same as Monthly Attendance Dashboard)
		direct = list(_reporting_employees(user))
		if direct:
			for report_user in frappe.get_all(
				"Employee",
				filters={"name": ["in", direct], "user_id": ["is", "set"]},
				pluck="user_id",
			):
				if report_user and report_user != user:
					scope.update(_reporting_employees(report_user))

	return sorted(scope)


def user_can_access_employee(employee: str, user: str | None = None) -> bool:
	"""True if `user` may view/act on this Employee in Roster tooling."""
	if not employee:
		return False
	scope = get_permitted_employee_names(user)
	if scope is None:
		return True
	return employee in scope


def _reporting_employees(user: str) -> set[str]:
	names: set[str] = set()
	if frappe.db.has_column("Employee", "leave_approver"):
		names.update(
			frappe.get_all("Employee", filters={"leave_approver": user}, pluck="name")
		)

	if frappe.db.exists("DocType", "Department Approver"):
		departments = frappe.get_all(
			"Department Approver",
			filters={"approver": user, "parentfield": "leave_approvers"},
			pluck="parent",
		)
		if departments:
			expanded: set[str] = set()
			for department in departments:
				expanded.update(_department_descendants(department))
			names.update(
				frappe.get_all(
					"Employee",
					filters={"department": ["in", list(expanded)]},
					pluck="name",
				)
			)
	return names


def _department_descendants(department: str) -> list[str]:
	bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return [department]
	rows = frappe.get_all(
		"Department",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
	)
	return rows or [department]


def _request_query(doctype: str, user: str | None = None) -> str:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if _has_unrestricted_leave_access(user):
		return ""

	table = f"`tab{doctype}`"
	conditions: list[str] = [
		f"{table}.`owner` = {frappe.db.escape(user)}",
	]

	employee = _employee_for_user(user)
	if employee:
		conditions.append(f"{table}.`employee` = {frappe.db.escape(employee.name)}")

	if _is_hod(user):
		conditions.append(
			(
				f"{table}.`employee` in ("
				"select `name` from `tabEmployee` "
				f"where `leave_approver` = {frappe.db.escape(user)})"
			)
		)
		if doctype == "Leave Application":
			conditions.append(f"{table}.`leave_approver` = {frappe.db.escape(user)}")
		if employee and employee.department:
			if doctype == "Leave Application":
				conditions.append(
					f"{table}.`department` = {frappe.db.escape(employee.department)}"
				)
			conditions.append(
				(
					f"{table}.`employee` in ("
					"select `name` from `tabEmployee` "
					f"where `department` = {frappe.db.escape(employee.department)})"
				)
			)

	return f"({' OR '.join(conditions)})"


def _request_has_permission(doc, user: str | None = None):
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	if _has_unrestricted_leave_access(user):
		return True

	if not doc:
		return False

	if getattr(doc, "owner", None) == user:
		return True

	if getattr(doc, "leave_approver", None) == user:
		return True

	if getattr(doc, "employee", None) and (
		frappe.db.get_value("Employee", doc.employee, "leave_approver") == user
	):
		return True

	employee = _employee_for_user(user)
	if not employee:
		return False

	if getattr(doc, "employee", None) == employee.name:
		return True

	if not _is_hod(user):
		return False

	if employee.department:
		doc_dept = getattr(doc, "department", None)
		if not doc_dept and getattr(doc, "employee", None):
			doc_dept = frappe.db.get_value("Employee", doc.employee, "department")
		if doc_dept and doc_dept == employee.department:
			return True

	return False


def _is_hod(user: str) -> bool:
	return bool(HOD_ROLES.intersection(frappe.get_roles(user)))


def _has_unrestricted_leave_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(UNRESTRICTED_LEAVE_ROLES.intersection(frappe.get_roles(user)))


def _employee_for_user(user: str):
	return frappe.db.get_value(
		"Employee",
		{"user_id": user},
		["name", "department"],
		as_dict=True,
	)
