"""
Permission helpers for list/form access control.

Who can see Leave Application and OD/WFH (Attendance Request):
- Employee: own requests only
- HOD (Leave Approver): own department (plus rows they are leave_approver for)
- Super HOD / HR / System Manager: all
"""

from __future__ import annotations

import frappe

# Roles that bypass department / own-only scoping
UNRESTRICTED_LEAVE_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
		"Administrator",
		"Super HOD",
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
