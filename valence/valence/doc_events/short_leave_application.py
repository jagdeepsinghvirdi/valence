"""
Short Leave Application — employee-initiated, portal-applied short leave.

This is deliberately separate from the existing point-based auto-deduction
system (Short Leave Ledger + Short Leave Logic, driven by Attendance Settings
.use_late_coming_rules). That system reacts passively to punch times; this one
is an active employee request, per the corrected #6 policy (Aug 2026,
updated after client review of the demo):

  - Personal Short Leave: duration capped per request (default 2 hrs,
    configurable) — beyond that, the employee must apply Half Day / Full
    Day Leave instead. Also capped per month (default 2, configurable).
  - Official Short Leave: NO duration cap, NO monthly cap — still logged
    and counted for records, just not limited.
  - Only ONE Short Leave Application allowed per employee per day, any
    type.
  - Single-level approval by the Reporting Head (Leave Approver role).

ALL of the numbers above live on Attendance Settings, not hardcoded here, so
HR can change policy without a dev change. See:
  - short_leave_max_duration_hours
  - short_leave_personal_monthly_cap
  - short_leave_official_monthly_cap   (0 / blank = unlimited)
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, time_diff_in_hours, get_first_day, get_last_day


DEFAULT_MAX_DURATION_HOURS = 2
DEFAULT_PERSONAL_MONTHLY_CAP = 2
DEFAULT_OFFICIAL_MONTHLY_CAP = 0  # 0 = unlimited


def validate(doc, method=None):
	set_employee_from_session_if_needed(doc)
	restrict_employee_to_self_for_regular_employees(doc)
	set_duration(doc)
	validate_duration_against_settings(doc)
	validate_one_per_day(doc)
	validate_monthly_cap(doc)
	set_defaults(doc)


def set_employee_from_session_if_needed(doc):
	if doc.employee or not doc.is_new():
		return
	linked_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if linked_employee:
		doc.employee = linked_employee


def restrict_employee_to_self_for_regular_employees(doc):
	if _is_privileged_user():
		return  # HR / Approver roles may file on behalf of anyone

	linked_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if linked_employee and doc.employee != linked_employee:
		frappe.throw(
			_("You can only apply for Short Leave for yourself."),
			title=_("Not Allowed"),
		)


@frappe.whitelist()
def is_privileged_user():
	"""
	Whitelisted so the client (short_leave_application.js) can ask the
	server directly whether the current user may file a Short Leave on
	someone else's behalf — single source of truth, see
	restrict_employee_to_self_for_regular_employees / _is_privileged_user.
	"""
	return _is_privileged_user()


def _is_privileged_user():
	"""
	Reuses this app's existing, already-verified HR-role check rather than
	maintaining a second, separately-guessed role list. See
	valence.valence.doc_events.leave_application._is_hr_user — the same
	roles (HR Manager / HR User / System Manager) are already trusted there
	for the same kind of "can act on behalf of others" decision.

	"Leave Approver" is added on top since that's the role this app already
	uses specifically for Reporting Head approval — see the permissions on
	Attendance Settings and valence.valence.setup.short_leave_workflow.
	"""
	try:
		from valence.valence.doc_events.leave_application import _is_hr_user

		if _is_hr_user():
			return True
	except Exception:
		pass

	return "Leave Approver" in frappe.get_roles()


def before_submit(doc, method=None):
	sync_status_from_workflow(doc)


def on_update(doc, method=None):
	sync_status_from_workflow(doc)
	if doc.get("workflow_state") == "Pending Approval":
		share_with_approver(doc)


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

def set_duration(doc):
	if not (doc.date and doc.from_time and doc.to_time):
		doc.duration_hours = 0
		return

	from_dt = get_datetime(f"{doc.date} {doc.from_time}")
	to_dt = get_datetime(f"{doc.date} {doc.to_time}")

	if to_dt <= from_dt:
		frappe.throw(_("To Time must be after From Time."), title=_("Invalid Time Range"))

	doc.duration_hours = round(time_diff_in_hours(to_dt, from_dt), 2)


def validate_duration_against_settings(doc):
	# Duration cap applies to Personal only. Official Short Leave has no
	# duration limit — confirmed policy: "for
	# official short leave no capping of 2 hrs and counts in month." It's
	# still logged/tracked (counted for records), just not limited.
	if doc.short_leave_type == "Official":
		return

	# 0 / blank is treated as "not configured yet" here, not "zero allowed" —
	# a Single doctype doesn't backfill field defaults on existing records,
	# so a freshly migrated site can have this sitting at 0 until HR saves it.
	max_hours = frappe.db.get_single_value("Attendance Settings", "short_leave_max_duration_hours")
	max_hours = max_hours or DEFAULT_MAX_DURATION_HOURS

	if doc.duration_hours > max_hours:
		frappe.throw(
			_(
				"This Short Leave is {0} hrs, which is more than the allowed {1} hrs. "
				"Please apply for Half Day or Full Day Leave instead — this request will "
				"not count against your Short Leave limit."
			).format(doc.duration_hours, max_hours),
			title=_("Duration Exceeds Limit"),
		)


def validate_one_per_day(doc):
	"""Only one Short Leave Application per employee per day, any type."""
	if not doc.employee or not doc.date:
		return

	existing = frappe.get_all(
		"Short Leave Application",
		filters={
			"employee": doc.employee,
			"date": doc.date,
			"docstatus": ["!=", 2],
			"name": ["!=", doc.name or ""],
		},
		pluck="name",
	)

	if existing:
		frappe.throw(
			_(
				"{0} already has a Short Leave Application on {1} ({2}). "
				"Only one Short Leave is allowed per day."
			).format(doc.employee_name or doc.employee, doc.date, existing[0]),
			title=_("Short Leave Already Applied For This Date"),
		)


# ---------------------------------------------------------------------------
# Monthly cap (Official = unlimited by default, Personal = capped)
# ---------------------------------------------------------------------------

def validate_monthly_cap(doc):
	if not doc.employee or not doc.date or not doc.short_leave_type:
		return

	if doc.short_leave_type == "Official":
		# 0 / blank genuinely means "unlimited" for Official — that's the confirmed policy default.
		cap = frappe.db.get_single_value("Attendance Settings", "short_leave_official_monthly_cap")
		if not cap:
			return  # unlimited
	else:
		# 0 / blank here means "not configured yet", not "0 allowed" — fall back to the default.
		cap = frappe.db.get_single_value("Attendance Settings", "short_leave_personal_monthly_cap")
		cap = cap or DEFAULT_PERSONAL_MONTHLY_CAP

	month_start = get_first_day(doc.date)
	month_end = get_last_day(doc.date)

	used = frappe.get_all(
		"Short Leave Application",
		filters={
			"employee": doc.employee,
			"short_leave_type": doc.short_leave_type,
			"date": ["between", [month_start, month_end]],
			"docstatus": ["!=", 2],
			"name": ["!=", doc.name or ""],
		},
		pluck="name",
	)

	if len(used) >= cap:
		frappe.throw(
			_(
				"{0} has already used {1} of {2} {3} Short Leave(s) allowed this month."
			).format(doc.employee_name or doc.employee, len(used), cap, doc.short_leave_type),
			title=_("Monthly Short Leave Limit Reached"),
		)


# ---------------------------------------------------------------------------
# Workflow / status sync (mirrors Leave Application's approach)
# ---------------------------------------------------------------------------

def set_defaults(doc):
	if not doc.get("workflow_state"):
		doc.workflow_state = "Draft"
	if not doc.get("status"):
		doc.status = "Open"


def sync_status_from_workflow(doc):
	state = doc.get("workflow_state")
	if state == "Approved" and doc.status != "Approved":
		doc.status = "Approved"
	elif state == "Rejected" and doc.status != "Rejected":
		doc.status = "Rejected"
	elif state in ("Draft", "Pending Approval") and doc.docstatus == 0:
		if doc.status not in ("Open", "Cancelled"):
			doc.status = "Open"


def share_with_approver(doc):
	if not doc.leave_approver:
		return
	# Enqueue only after the current transaction actually commits. Without
	# this, the background worker can (and reliably does, in practice) pick
	# up the job and call frappe.get_doc() before this transaction's INSERT
	# is visible on the worker's own DB connection, raising a
	# DoesNotExistError that gets silently swallowed by the try/except in
	# _share_with_approver_now — leaving the approver un-shared with no
	# visible error anywhere except Error Log.
	frappe.db.after_commit.add(
		lambda: frappe.enqueue(
			"valence.valence.doc_events.short_leave_application._share_with_approver_now",
			queue="short",
			doctype=doc.doctype,
			docname=doc.name,
			approver=doc.leave_approver,
		)
	)


def _share_with_approver_now(doctype, docname, approver):
	try:
		from hrms.hr.utils import share_doc_with_approver

		doc = frappe.get_doc(doctype, docname)
		share_doc_with_approver(doc, approver)
	except Exception:
		frappe.log_error(
			title="Short Leave Application: share_with_approver failed",
			message=frappe.get_traceback(),
		)

def get_setting(fieldname, default):
	value = frappe.db.get_single_value("Attendance Settings", fieldname)
	return value if value not in (None, "") else default