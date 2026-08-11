"""
Permission helpers for list/form access control.

#5 Department-wise Leave Access Control (Track B)
Employees and HODs only see leave applications for their department (plus own
applications and rows where they are leave_approver). HR and system roles see all.
"""

from __future__ import annotations

import frappe

# Roles that bypass department scoping
UNRESTRICTED_LEAVE_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
		"Administrator",
		# Super HOD final-approves 3+ day leave org-wide (#4)
		"Super HOD",
	}
)


def leave_application_query(user: str | None = None) -> str:
	"""
	Extra WHERE clause for Leave Application list / link queries.

	Returns empty string for unrestricted roles (full access).
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if _has_unrestricted_leave_access(user):
		return ""

	conditions: list[str] = [
		f"`tabLeave Application`.`leave_approver` = {frappe.db.escape(user)}",
		f"`tabLeave Application`.`owner` = {frappe.db.escape(user)}",
		# Approver on Employee master (leave form field may be empty after API insert)
		(
			"`tabLeave Application`.`employee` in ("
			"select `name` from `tabEmployee` "
			f"where `leave_approver` = {frappe.db.escape(user)})"
		),
	]

	employee = _employee_for_user(user)
	if employee:
		conditions.append(
			f"`tabLeave Application`.`employee` = {frappe.db.escape(employee.name)}"
		)
		if employee.department:
			conditions.append(
				f"`tabLeave Application`.`department` = {frappe.db.escape(employee.department)}"
			)

	return f"({' OR '.join(conditions)})"


def leave_application_has_permission(doc, ptype: str | None = None, user: str | None = None):
	"""
	Mirror list scoping when opening a single Leave Application by name/URL.

	Return True/False; return None if doc is incomplete so role perms still apply.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	if _has_unrestricted_leave_access(user):
		return True

	if not doc:
		return False

	# Approver / creator can always act (workflow + own draft)
	if getattr(doc, "leave_approver", None) == user:
		return True
	if getattr(doc, "owner", None) == user:
		return True

	# Wired leave approver on Employee master (HOD approve path)
	if getattr(doc, "employee", None) and (
		frappe.db.get_value("Employee", doc.employee, "leave_approver") == user
	):
		return True

	employee = _employee_for_user(user)
	if not employee:
		return False

	if getattr(doc, "employee", None) == employee.name:
		return True

	if employee.department and getattr(doc, "department", None) == employee.department:
		return True

	return False


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
