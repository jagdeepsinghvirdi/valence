"""
Employee master hooks for US6 §20 Roster / Dashboard scoping.

ERPNext auto-creates User Permission (Employee → self) when
`create_user_permission` is set. That locks Leave Approvers to their own
row and blocks hierarchy visibility even when permission_query_conditions
allow subordinates.

For roles that need hierarchy (or full) access, strip Employee User
Permissions and rely on `valence.valence.override.query.employee_query`.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from valence.valence.approval_hierarchy import SUPER_HOD_ROLE

# Roles whose Employee visibility is governed by employee_query / has_permission
# — must NOT be pinned to a single Employee via User Permission.
HIERARCHY_OR_FULL_ROLES = frozenset(
	{
		"Leave Approver",
		SUPER_HOD_ROLE,
		"HR Manager",
		"HR User",
		"System Manager",
	}
)


def on_update(doc, method=None):
	"""After ERPNext may add User Permissions, clear them for approver/HR users."""
	relax_employee_user_permission_if_needed(doc)


def on_user_role_change(doc, method=None):
	"""Has Role add/remove — re-sync when Leave Approver / Super HOD is granted."""
	if getattr(doc, "parenttype", None) and doc.parenttype != "User":
		return
	user = getattr(doc, "parent", None)
	if not user:
		return
	if doc.role not in HIERARCHY_OR_FULL_ROLES:
		return
	emp_name = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if emp_name:
		relax_employee_user_permission_if_needed(
			frappe._dict(
				name=emp_name,
				user_id=user,
				create_user_permission=frappe.db.get_value(
					"Employee", emp_name, "create_user_permission"
				),
			)
		)
	else:
		_delete_employee_user_permissions(user)


def relax_employee_user_permission_if_needed(doc) -> bool:
	"""
	Return True if Employee User Permissions were cleared for this user.
	"""
	user = getattr(doc, "user_id", None)
	if not user:
		return False
	if not _user_needs_query_scope(user):
		return False

	_delete_employee_user_permissions(user)

	if cint(getattr(doc, "create_user_permission", 0)):
		# Prevent ERPNext from recreating the lock on next user_id change
		if getattr(doc, "name", None) and frappe.db.exists("Employee", doc.name):
			frappe.db.set_value(
				"Employee", doc.name, "create_user_permission", 0, update_modified=False
			)
	return True


def cleanup_employee_user_permissions_for_approvers() -> int:
	"""
	One-shot / migrate: clear Employee User Permissions for hierarchy & HR users.
	Returns number of users cleaned.
	"""
	users: set[str] = set()
	for role in HIERARCHY_OR_FULL_ROLES:
		users.update(
			frappe.get_all(
				"Has Role",
				filters={"role": role, "parenttype": "User"},
				pluck="parent",
			)
		)

	cleaned = 0
	for user in users:
		if user in ("Administrator", "Guest"):
			continue
		if not frappe.db.exists("User", user):
			continue
		before = frappe.db.count("User Permission", {"user": user, "allow": "Employee"})
		_delete_employee_user_permissions(user)
		emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if emp and cint(frappe.db.get_value("Employee", emp, "create_user_permission")):
			frappe.db.set_value(
				"Employee", emp, "create_user_permission", 0, update_modified=False
			)
		if before:
			cleaned += 1
	return cleaned


def after_migrate():
	cleanup_employee_user_permissions_for_approvers()
	frappe.clear_cache()


def _user_needs_query_scope(user: str) -> bool:
	if user == "Administrator":
		return True
	return bool(HIERARCHY_OR_FULL_ROLES.intersection(frappe.get_roles(user)))


def _delete_employee_user_permissions(user: str):
	frappe.db.delete("User Permission", {"user": user, "allow": "Employee"})
