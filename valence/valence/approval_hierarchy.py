"""
Extended Leave Approval Workflow — shared approval hierarchy.

Rules (Desk + API + pending docs):
1. Identify the applicant (Employee.user_id).
2. Route by assigned Leave Approver — not merely "has Leave Approver role".
3. Never allow self-approval at any level.
4. If no valid leave approver (missing or self), route to HR.
5. If no HR available, route to Administrator (DBA).
6. Same rules for Leave Application and Attendance Request (OD/WFH).
"""

from __future__ import annotations

import frappe
from frappe import _

from valence.valence.setup.leave_workflow import (
	STATE_APPROVED,
	STATE_PENDING_HOD,
	STATE_PENDING_SUPER_HOD,
	STATE_REJECTED,
)

HR_ROLES = ("HR Manager", "HR User")
SUPER_HOD_ROLE = "Super HOD"
LEAVE_APPROVER_ROLE = "Leave Approver"
SYSTEM_ROLES = ("System Manager",)

APPROVAL_ACTIONS = frozenset({"Approve", "Reject"})

# Workflow states where Approve/Reject are approval decisions (not Apply)
PENDING_APPROVAL_STATES = (STATE_PENDING_HOD, STATE_PENDING_SUPER_HOD)

SUPPORTED_DOCTYPES = ("Leave Application", "Attendance Request")


def get_applicant_user(employee: str | None) -> str | None:
	if not employee:
		return None
	return frappe.db.get_value("Employee", employee, "user_id")


def is_applicant(user: str | None, employee: str | None) -> bool:
	applicant = get_applicant_user(employee)
	return bool(user and applicant and user == applicant)


def user_has_any_role(user: str, roles: tuple[str, ...] | list[str]) -> bool:
	if not user or user in ("Guest",):
		return False
	user_roles = set(frappe.get_roles(user))
	return bool(user_roles.intersection(roles))


def is_hr_authority(user: str) -> bool:
	"""HR has full authority to approve (but still cannot self-approve)."""
	if not user or user == "Guest":
		return False
	if user == "Administrator":
		return True
	return user_has_any_role(user, list(HR_ROLES) + list(SYSTEM_ROLES))


def is_super_hod_user(user: str | None) -> bool:
	if not user:
		return False
	return user_has_any_role(user, (SUPER_HOD_ROLE,))


def get_raw_leave_approver(employee: str | None) -> str | None:
	"""Employee.leave_approver or first Department leave approver (HRMS)."""
	if not employee:
		return None
	try:
		from hrms.hr.doctype.leave_application.leave_application import get_leave_approver

		return (get_leave_approver(employee) or "").strip() or None
	except Exception:
		approver = frappe.db.get_value("Employee", employee, "leave_approver")
		return (approver or "").strip() or None


def get_effective_leave_approver(employee: str | None) -> str | None:
	"""
	Assigned leave approver if valid and not the applicant themselves.
	Self / missing → None (caller must fall back to HR / Administrator).
	"""
	applicant = get_applicant_user(employee)
	approver = get_raw_leave_approver(employee)
	if not approver:
		return None
	if not frappe.db.exists("User", approver):
		return None
	if cint_enabled_user(approver) is False:
		return None
	if applicant and approver == applicant:
		return None
	return approver


def cint_enabled_user(user: str) -> bool:
	enabled = frappe.db.get_value("User", user, "enabled")
	return bool(enabled)


def get_hr_users(exclude_user: str | None = None) -> list[str]:
	"""Enabled HR Manager / HR User accounts, excluding the applicant."""
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", list(HR_ROLES)], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	out: list[str] = []
	for user in users:
		if not user or user in ("Guest", "Administrator"):
			continue
		if exclude_user and user == exclude_user:
			continue
		if not cint_enabled_user(user):
			continue
		if user not in out:
			out.append(user)
	return out


def resolve_hod_stage_routing(employee: str | None) -> dict:
	"""
	Who should act at the first approval stage (Pending HOD).

	Returns:
	  {
	    "level": "leave_approver" | "hr" | "administrator",
	    "users": [...],
	  }
	"""
	applicant = get_applicant_user(employee)
	approver = get_effective_leave_approver(employee)
	if approver:
		return {"level": "leave_approver", "users": [approver]}

	hr_users = get_hr_users(exclude_user=applicant)
	if hr_users:
		return {"level": "hr", "users": hr_users}

	return {"level": "administrator", "users": ["Administrator"]}


def user_may_approve_or_reject(doc, user: str | None = None) -> bool:
	"""
	True if `user` may Approve/Reject this leave/OD/WFH under hierarchy rules.
	Self-approval is always False.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	employee = doc.get("employee")
	if is_applicant(user, employee):
		return False

	state = doc.get("workflow_state") or "Draft"

	if state == STATE_PENDING_HOD:
		return _may_act_at_hod_stage(user, employee)

	if state == STATE_PENDING_SUPER_HOD:
		return _may_act_at_super_hod_stage(user, employee)

	return False


def _may_act_at_hod_stage(user: str, employee: str | None) -> bool:
	# Administrator is the ultimate fallback — always allowed so flow never sticks
	if user == "Administrator":
		return True

	# HR / System Manager have full authority (PDF) — still blocked from self via caller
	if user_has_any_role(user, list(HR_ROLES) + list(SYSTEM_ROLES)):
		return True

	routing = resolve_hod_stage_routing(employee)
	if routing["level"] == "leave_approver":
		# Must be the assigned leave approver — Leave Approver role alone is not enough
		return user in routing["users"]

	if routing["level"] == "hr":
		return user in routing["users"] or user_has_any_role(user, list(HR_ROLES))

	return user == "Administrator"


def _may_act_at_super_hod_stage(user: str, employee: str | None) -> bool:
	if user == "Administrator":
		return True
	if user_has_any_role(user, list(HR_ROLES) + list(SYSTEM_ROLES)):
		return True
	if user_has_any_role(user, (SUPER_HOD_ROLE,)):
		return True
	# No Super HOD / HR left → only Admin (already True above). Role-only Leave Approver: no.
	return False


def validate_no_self_approval(doc, label: str | None = None):
	"""
	Block applicant from approving/rejecting their own request on workflow
	state change. Apply (Draft → Pending HOD) remains allowed.
	"""
	employee = doc.get("employee")
	user = frappe.session.user
	if not is_applicant(user, employee):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	old_state = before.get("workflow_state") or "Draft"
	new_state = doc.get("workflow_state") or "Draft"
	if old_state == new_state:
		return

	# Applicant may Apply only
	if old_state == "Draft" and new_state == STATE_PENDING_HOD:
		return

	if new_state in (STATE_APPROVED, STATE_PENDING_SUPER_HOD, STATE_REJECTED):
		if old_state in PENDING_APPROVAL_STATES:
			doctype_label = label or _(doc.doctype)
			frappe.throw(
				_("You cannot approve or reject your own {0}.").format(doctype_label),
				title=_("Self-Approval Not Allowed"),
			)


def validate_approver_authority(doc, label: str | None = None):
	"""
	On Approve/Reject transitions, ensure the session user is the correct
	hierarchy approver (assigned leave approver / Super HOD / HR / Admin).
	Applies to new and already-pending documents.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return

	# Background / system paths may set flags
	if getattr(frappe.flags, "ignore_approval_hierarchy", False):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	old_state = before.get("workflow_state") or "Draft"
	new_state = doc.get("workflow_state") or "Draft"
	if old_state == new_state:
		return

	# Only enforce on approval decisions from pending states
	if old_state not in PENDING_APPROVAL_STATES:
		return
	if new_state not in (STATE_APPROVED, STATE_PENDING_SUPER_HOD, STATE_REJECTED):
		return

	# Self-approval first (clearer message)
	if is_applicant(user, doc.get("employee")):
		doctype_label = label or _(doc.doctype)
		frappe.throw(
			_("You cannot approve or reject your own {0}.").format(doctype_label),
			title=_("Self-Approval Not Allowed"),
		)

	# Temporarily set doc state to the *pending* state for authority check
	# (user_may_approve_or_reject keys off current workflow_state)
	pending_state = old_state
	current = doc.get("workflow_state")
	doc.workflow_state = pending_state
	try:
		allowed = user_may_approve_or_reject(doc, user)
	finally:
		doc.workflow_state = current

	if not allowed:
		doctype_label = label or _(doc.doctype)
		frappe.throw(
			_(
				"You are not the assigned approver for this {0}. "
				"Approval must follow the applicant's leave-approver hierarchy "
				"(or HR / Administrator fallback)."
			).format(doctype_label),
			title=_("Not the Correct Approver"),
			exc=frappe.PermissionError,
		)


def get_hod_stage_share_users(employee: str | None) -> list[str]:
	"""Users who should receive DocShare / ToDo when request enters Pending HOD."""
	routing = resolve_hod_stage_routing(employee)
	users = list(routing["users"])
	# Always keep HR in the loop as full authority (except applicant)
	applicant = get_applicant_user(employee)
	for hr in get_hr_users(exclude_user=applicant):
		if hr not in users:
			users.append(hr)
	return users


def share_with_users(doc, users: list[str]):
	if not doc or not doc.name:
		return
	for user in users:
		if not user or user in ("Guest",):
			continue
		try:
			frappe.share.add_docshare(
				doc.doctype,
				doc.name,
				user,
				write=1,
				submit=1,
				share=1,
				flags={"ignore_share_permission": True},
			)
		except Exception:
			frappe.log_error(
				title="Approval hierarchy share failed",
				message=frappe.get_traceback(),
			)


def ensure_todos_for_users(doc, users: list[str], subject: str, message: str):
	for user in users:
		if not user or user in ("Guest",):
			continue
		existing = frappe.db.exists(
			"ToDo",
			{
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"allocated_to": user,
				"status": "Open",
			},
		)
		if existing:
			continue
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"description": message,
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"assigned_by": frappe.session.user,
				"priority": "High",
			}
		).insert(ignore_permissions=True)

		if hasattr(frappe, "publish_realtime"):
			frappe.publish_realtime(
				event="notification",
				message={"type": "Alert", "message": subject},
				user=user,
			)


def route_pending_hod(doc):
	"""
	When a request first enters Pending HOD Approval, share/notify the correct
	approver chain (assigned leave approver, or HR, or Administrator).
	"""
	if doc.get("workflow_state") != STATE_PENDING_HOD:
		return

	before = doc.get_doc_before_save()
	if before and before.get("workflow_state") == STATE_PENDING_HOD:
		return

	routing = resolve_hod_stage_routing(doc.get("employee"))
	users = get_hod_stage_share_users(doc.get("employee"))
	share_with_users(doc, users)

	# Leave Application: keep leave_approver field pointing at effective approver when possible
	if doc.doctype == "Leave Application" and doc.meta.has_field("leave_approver"):
		if routing["level"] == "leave_approver" and routing["users"]:
			if doc.leave_approver != routing["users"][0]:
				doc.db_set("leave_approver", routing["users"][0], update_modified=False)
		elif routing["level"] == "hr" and routing["users"]:
			# Point at first HR so lists/filters still show an approver
			if doc.leave_approver != routing["users"][0]:
				doc.db_set("leave_approver", routing["users"][0], update_modified=False)
		elif routing["level"] == "administrator":
			if doc.leave_approver != "Administrator":
				doc.db_set("leave_approver", "Administrator", update_modified=False)

	level_label = {
		"leave_approver": _("Leave Approver / HOD"),
		"hr": _("HR"),
		"administrator": _("Administrator (DBA)"),
	}.get(routing["level"], routing["level"])

	# ToDos only for HR / Administrator fallback — assigned leave approver already
	# gets DocShare (and HRMS leave_approver notifications). Avoid noisy ToDos on
	# every normal HOD-stage leave.
	if routing["level"] in ("hr", "administrator"):
		subject = _("{0} needs approval ({1}): {2}").format(doc.doctype, level_label, doc.name)
		message = _("{0} {1} for {2} is pending approval by {3}.").format(
			doc.doctype,
			doc.name,
			doc.get("employee_name") or doc.get("employee"),
			level_label,
		)
		ensure_todos_for_users(doc, routing["users"], subject, message)


def patch_workflow_approval_access():
	"""
	Extend Frappe workflow so Desk buttons + apply_workflow respect hierarchy
	(assigned leave approver / no self-approval / HR / Administrator fallback).

	Note: this Frappe build's get_transitions() only checks roles — it does not
	call has_approval_access. We patch both get_transitions and has_approval_access.

	Important: patched get_transitions must stay @frappe.whitelist()'d, otherwise
	Desk save → get_transitions returns 403 Method Not Allowed.
	"""
	import frappe.model.workflow as workflow_mod

	access_patched = getattr(workflow_mod.has_approval_access, "_valence_hierarchy_patched", False)
	transitions_fn = workflow_mod.get_transitions
	transitions_patched = getattr(transitions_fn, "_valence_hierarchy_patched", False)
	transitions_whitelisted = transitions_fn in getattr(frappe, "whitelisted", [])

	if access_patched and transitions_patched and transitions_whitelisted:
		return

	if not access_patched:
		original_access = workflow_mod.has_approval_access

		def has_approval_access(user, doc, transition):
			if not original_access(user, doc, transition):
				return False

			if not doc or getattr(doc, "doctype", None) not in SUPPORTED_DOCTYPES:
				return True

			action = None
			if isinstance(transition, dict):
				action = transition.get("action")
			else:
				action = getattr(transition, "action", None)

			if action not in APPROVAL_ACTIONS:
				return True

			return user_may_approve_or_reject(doc, user)

		has_approval_access._valence_hierarchy_patched = True  # type: ignore[attr-defined]
		workflow_mod.has_approval_access = has_approval_access

	if not transitions_patched or not transitions_whitelisted:
		# If a previous broken patch exists, unwrap to the real original once
		original_get_transitions = workflow_mod.get_transitions
		if getattr(original_get_transitions, "_valence_hierarchy_patched", False):
			original_get_transitions = getattr(
				original_get_transitions, "_valence_original_get_transitions", original_get_transitions
			)

		def get_transitions(doc, workflow=None, raise_exception=False):
			transitions = original_get_transitions(
				doc, workflow=workflow, raise_exception=raise_exception
			)
			if not doc or getattr(doc, "doctype", None) not in SUPPORTED_DOCTYPES:
				return transitions

			user = frappe.session.user
			filtered = []
			for transition in transitions:
				action = (
					transition.get("action")
					if isinstance(transition, dict)
					else getattr(transition, "action", None)
				)
				if action in APPROVAL_ACTIONS and not user_may_approve_or_reject(doc, user):
					continue
				filtered.append(transition)
			return filtered

		get_transitions._valence_hierarchy_patched = True  # type: ignore[attr-defined]
		get_transitions._valence_original_get_transitions = original_get_transitions  # type: ignore[attr-defined]

		# Keep HTTP access for Desk (same as stock @frappe.whitelist on get_transitions)
		whitelisted = getattr(frappe, "whitelisted", None)
		if isinstance(whitelisted, list):
			if get_transitions not in whitelisted:
				whitelisted.append(get_transitions)
			# Drop stale broken wrapper if present
			if (
				transitions_fn is not get_transitions
				and getattr(transitions_fn, "_valence_hierarchy_patched", False)
				and transitions_fn in whitelisted
			):
				try:
					whitelisted.remove(transitions_fn)
				except ValueError:
					pass

		allowed_map = getattr(frappe, "allowed_http_methods_for_whitelisted_func", None)
		if isinstance(allowed_map, dict):
			allowed_map[get_transitions] = allowed_map.get(
				original_get_transitions, ["GET", "POST", "PUT", "DELETE"]
			)

		workflow_mod.get_transitions = get_transitions
