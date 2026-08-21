import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate
from frappe.model.workflow import get_workflow_name

# Shared by Track A (#8) and Track B (#3, #4 extras, #10, #11).
# Keep each rule in its own function; coordinate before editing this file.

SUPER_HOD_STATE = "Pending Super HOD Approval"
WORKING_LEAVE_DAYS_FIELD = "custom_working_leave_days"


def validate(doc, method=None):
	"""Leave Application validate — runs each rule in order."""
	set_working_leave_days(doc, method)
	validate_leave_creation_window(doc, method)
	validate_no_leave_on_present_day(doc, method)
	validate_resigned_employee_leave_type(doc, method)
	sync_leave_status_from_workflow(doc, method)
	# Extended Leave Approval Workflow (self-approval + hierarchy)
	from valence.valence.approval_hierarchy import (
		validate_approver_authority,
		validate_no_self_approval,
	)

	validate_no_self_approval(doc, label=_("leave application"))
	validate_approver_authority(doc, label=_("leave application"))


def before_submit(doc, method=None):
	"""Ensure HRMS status matches terminal workflow states before submit."""
	sync_leave_status_from_workflow(doc, method)


def on_update(doc, method=None):
	"""Side-effects after save (workflow notifications, etc.)."""
	from valence.valence.approval_hierarchy import route_pending_hod

	route_pending_hod(doc)
	notify_super_hod_if_needed(doc, method)


def sync_leave_status_from_workflow(doc, method=None):
	"""
	#4 Keep Leave Application.status aligned with workflow_state.

	HRMS on_submit requires status in (Approved, Rejected). Workflow
	update_field can be skipped for some roles/paths — force sync here.
	"""
	state = doc.get("workflow_state")
	if state == "Approved" and doc.status != "Approved":
		doc.status = "Approved"
	elif state == "Rejected" and doc.status != "Rejected":
		doc.status = "Rejected"
	elif state in (
		"Draft",
		"Pending HOD Approval",
		"Pending Super HOD Approval",
	) and doc.docstatus == 0:
		if doc.status not in ("Open", "Cancelled"):
			doc.status = "Open"


def set_working_leave_days(doc, method=None):
	"""
	#3 Leave length for approval routing.

	Counts working days between from_date and to_date, excluding:
	- Holidays (Holiday List)
	- Weekly offs (Holiday List weekly_off + Shift Assignment custom_off_day)

	Backdated leave is allowed only within the working-day creation-window rule
	(see validate_leave_creation_window). Super HOD uses this field when
	working days >= Attendance Settings → Super HOD After Working Days
	(configurable, default 3), for future, same-day, and backdated leave.
	"""
	if not doc.meta.has_field(WORKING_LEAVE_DAYS_FIELD):
		return

	if not doc.employee or not doc.from_date or not doc.to_date:
		doc.set(WORKING_LEAVE_DAYS_FIELD, 0)
		return

	days = count_working_leave_days(
		doc.employee,
		doc.from_date,
		doc.to_date,
		half_day=cint(doc.half_day),
		half_day_date=doc.half_day_date,
	)
	doc.set(WORKING_LEAVE_DAYS_FIELD, days)


def count_working_leave_days(employee, from_date, to_date, half_day=0, half_day_date=None) -> float:
	"""Working days in [from_date, to_date], excluding holidays and week offs."""
	start, end = getdate(from_date), getdate(to_date)
	if end < start:
		return 0.0

	non_working = _get_non_working_dates(employee, start, end)
	half_day_on = getdate(half_day_date) if half_day and half_day_date else None

	days = 0.0
	current = start
	while current <= end:
		if current not in non_working:
			if half_day_on and current == half_day_on:
				days += 0.5
			else:
				days += 1.0
		current = add_days(current, 1)

	return flt(days, 1)


def _get_non_working_dates(employee, start, end) -> set:
	"""Union of holiday-list dates (incl. weekly_off rows) and shift weekly off weekdays."""
	non_working = set()

	try:
		from hrms.hr.utils import get_holiday_dates_for_employee

		for d in get_holiday_dates_for_employee(employee, start, end):
			non_working.add(getdate(d))
	except Exception:
		# No holiday list / raise_exception — still apply shift weekly offs below
		pass

	# Explicit weekly_off holidays (in case list fetch omitted some)
	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
	if holiday_list:
		for d in frappe.get_all(
			"Holiday",
			filters={
				"parent": holiday_list,
				"holiday_date": ["between", [start, end]],
				"weekly_off": 1,
			},
			pluck="holiday_date",
		):
			non_working.add(getdate(d))

	# Shift Assignment weekly off weekday (e.g. Sunday)
	off_weekday = _get_shift_weekly_off_weekday(employee, start, end)
	if off_weekday:
		current = start
		while current <= end:
			if current.strftime("%A") == off_weekday:
				non_working.add(current)
			current = add_days(current, 1)

	return non_working


def _get_shift_weekly_off_weekday(employee, start, end):
	"""Return weekday name from active Shift Assignment.custom_off_day, if any."""
	if not frappe.db.has_column("Shift Assignment", "custom_off_day"):
		return None

	assignments = frappe.get_all(
		"Shift Assignment",
		filters={"employee": employee, "start_date": ["<=", end], "docstatus": 1},
		or_filters=[["end_date", ">=", start], ["end_date", "is", "not set"]],
		fields=["custom_off_day"],
		order_by="start_date desc",
	)
	for row in assignments:
		if row.custom_off_day:
			return row.custom_off_day
	return None


def validate_leave_creation_window(doc, method=None):
	"""
	Creation window after the leave / request END date, counted in working days
	(holidays + weekly offs excluded). Default 3.

	Employees can apply backdated Leave or OD/WFH until this many working days
	have passed after to_date. Applying on or before to_date is always allowed.
	Approval has no time limit — HOD / Super HOD can approve anytime. HR can override.
	"""
	if getattr(frappe.flags, "ignore_leave_creation_window", False):
		return

	if _is_hr_user():
		return

	end_date = doc.to_date or doc.from_date
	if not end_date:
		return

	# Approval and other updates: skip if the period did not change
	if not doc.is_new():
		before = doc.get_doc_before_save()
		if before:
			before_end = before.to_date or before.from_date
			if (
				before.from_date
				and before_end
				and getdate(before.from_date) == getdate(doc.from_date)
				and getdate(before_end) == getdate(end_date)
			):
				return

	from valence.valence.setup.leave_workflow import get_leave_creation_window_days

	window = get_leave_creation_window_days()
	end_date = getdate(end_date)
	today = getdate()
	if end_date >= today:
		return

	elapsed = _working_days_after_end(doc.employee, end_date, today)
	if elapsed <= window:
		return

	deadline = _last_apply_date(doc.employee, end_date, window)
	kind = _("leave") if doc.doctype == "Leave Application" else _("OD/WFH request")
	frappe.throw(
		_(
			"Backdated {0} can be created only within {1} working days after the end date "
			"(holidays and weekly offs excluded). Last date to apply for this period was {2}."
		).format(kind, frappe.bold(window), formatdate(deadline)),
		title=_("Creation Window Exceeded"),
	)


def _working_days_after_end(employee, to_date, today) -> float:
	"""Working days strictly after to_date through today (inclusive)."""
	start = add_days(getdate(to_date), 1)
	if start > getdate(today):
		return 0.0
	if not employee:
		return float((getdate(today) - start).days + 1)
	return count_working_leave_days(employee, start, today)


def _last_apply_date(employee, to_date, window):
	"""Nth working day after to_date (holidays and weekly offs skipped)."""
	start = add_days(getdate(to_date), 1)
	if window <= 0:
		return start
	if not employee:
		return add_days(start, window - 1)

	horizon = add_days(start, 90)
	non_working = _get_non_working_dates(employee, start, horizon)
	found = 0
	current = start
	last = start
	for _ in range(90):
		if current not in non_working:
			found += 1
			last = current
			if found >= window:
				return last
		current = add_days(current, 1)
	return last



def needs_super_hod_approval(working_days, from_date=None) -> bool:
	"""True when working days are at or above the Super HOD threshold.

	Applies to future, same-day, and backdated leave. `from_date` is unused
	(kept so existing callers do not break).
	"""
	from valence.valence.setup.leave_workflow import get_super_hod_working_days_threshold

	return flt(working_days) >= get_super_hod_working_days_threshold()


def validate_no_leave_on_present_day(doc, method=None):
	"""
	#10 Leave on Present Day Restriction (Track B)

	Employees cannot apply leave for dates already marked Present in Attendance.
	HR roles can override.
	"""
	if getattr(frappe.flags, "ignore_present_day_leave_restriction", False):
		return

	if _is_hr_user():
		return

	if not doc.employee or not doc.from_date or not doc.to_date:
		return

	present_dates = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"attendance_date": ["between", [doc.from_date, doc.to_date]],
			"status": "Present",
			"docstatus": 1,
		},
		pluck="attendance_date",
		order_by="attendance_date asc",
	)

	if not present_dates:
		return

	dates_str = ", ".join(formatdate(d) for d in present_dates)
	frappe.throw(
		_(
			"Leave cannot be applied for date(s) already marked Present in Attendance: {0}. "
			"Please contact HR if you need to change this."
		).format(dates_str),
		title=_("Present Day Conflict"),
	)


ALLOWED_RESIGNED_LEAVE_TYPES = frozenset({"Leave Without Pay", "Sick Leave"})


def employee_in_resign_period(employee) -> bool:
	"""True if employee has resigned, is serving notice, or is already relieved."""
	if not employee:
		return False
	fields = ["status", "relieving_date"]
	meta = frappe.get_meta("Employee")
	if meta.has_field("resignation_letter_date"):
		fields.append("resignation_letter_date")
	emp = frappe.db.get_value("Employee", employee, fields, as_dict=True)
	if not emp:
		return False
	if emp.status == "Left":
		return True
	if emp.get("relieving_date"):
		return True
	resignation = emp.get("resignation_letter_date")
	if resignation and getdate(resignation) <= getdate():
		return True
	return False


def resigned_leave_types_allowed() -> list:
	"""Leave Type names that exist and are allowed during resign/notice period."""
	return frappe.get_all(
		"Leave Type",
		filters={"name": ["in", list(ALLOWED_RESIGNED_LEAVE_TYPES)]},
		pluck="name",
	)


@frappe.whitelist()
def get_leave_type_filter_for_employee(employee):
	"""None = no extra filter. List = only these leave types in the dropdown."""
	if not employee or _is_hr_user():
		return None
	if not employee_in_resign_period(employee):
		return None
	return resigned_leave_types_allowed()


@frappe.whitelist()
def get_leave_types(employee, date=None):
	"""HRMS mobile/list of leave types, restricted during resign/notice period."""
	from hrms.api import get_leave_types as hrms_get_leave_types

	types = hrms_get_leave_types(employee, date)
	allowed = get_leave_type_filter_for_employee(employee)
	if not allowed:
		return types
	allowed_set = set(allowed)
	return [lt for lt in types if lt in allowed_set]


def validate_resigned_employee_leave_type(doc, method=None):
	"""
	#11 Resignation Option (Track B)

	Resigned / notice-period employees may only apply LWP or Sick Leave.
	HR roles can override.
	"""
	if getattr(frappe.flags, "ignore_resigned_leave_type_check", False):
		return

	if _is_hr_user():
		return

	if not doc.employee or not doc.leave_type:
		return

	if not employee_in_resign_period(doc.employee):
		return

	if doc.leave_type not in ALLOWED_RESIGNED_LEAVE_TYPES:
		frappe.throw(
			_(
				"During resignation / notice period you can only apply for Leave Without Pay or Sick Leave. "
				"Selected leave type: {0}."
			).format(frappe.bold(doc.leave_type)),
			title=_("Leave Type Not Allowed"),
		)


def notify_super_hod_if_needed(doc, method=None):
	"""
	#4 Extended Leave Approval — when HOD sends leave at or above the working-day
	threshold to Super HOD, share the document and create ToDos.
	Sharing is required so User Permissions on Employee cannot block Super HOD.
	"""
	if doc.get("workflow_state") != SUPER_HOD_STATE:
		return

	# Only when the state just changed into Super HOD pending
	before = doc.get_doc_before_save()
	if before and before.get("workflow_state") == SUPER_HOD_STATE:
		return

	share_doc_with_super_hod(doc)
	_notify_super_hod_approvers(doc)


def share_doc_with_super_hod(doc):
	"""Grant Super HOD / HR Manager access so they can open and approve the document.

	Must ignore share-permission checks: HOD (Leave Approver) often cannot Share,
	and swallowing that error is what blocked Super HOD in team-lead testing.

	If no Super HOD / HR Manager users exist, fall back to Administrator (DBA)
	so the request cannot get stuck without an approver.
	"""
	if not doc.name:
		return
	from valence.valence.approval_hierarchy import get_applicant_user, get_hr_users

	users = _users_with_roles(["Super HOD", "HR Manager"])
	applicant = get_applicant_user(doc.get("employee"))
	users = [u for u in users if u and u != applicant]
	# Ensure HR users (excluding applicant) are included
	for hr in get_hr_users(exclude_user=applicant):
		if hr not in users:
			users.append(hr)
	if not users:
		users = ["Administrator"]

	for user in users:
		if user in ("Guest",):
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
				title="Super HOD share failed",
				message=frappe.get_traceback(),
			)


def _notify_super_hod_approvers(doc):
	users = _users_with_roles(["Super HOD", "HR Manager"])
	if not users:
		return

	working = doc.get(WORKING_LEAVE_DAYS_FIELD) or doc.total_leave_days
	subject = _("Leave needs Super HOD approval: {0}").format(doc.name)
	message = _(
		"Leave Application {0} for {1} ({2} working days from {3} to {4}) needs Super HOD approval."
	).format(
		doc.name,
		doc.employee_name or doc.employee,
		working,
		formatdate(doc.from_date),
		formatdate(doc.to_date),
	)

	for user in users:
		if user in ("Administrator", "Guest"):
			continue
		existing = frappe.db.exists(
			"ToDo",
			{
				"reference_type": "Leave Application",
				"reference_name": doc.name,
				"allocated_to": user,
				"status": "Open",
			},
		)
		if existing:
			continue
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"description": message,
				"reference_type": "Leave Application",
				"reference_name": doc.name,
				"assigned_by": frappe.session.user,
				"priority": "High",
			}
		)
		todo.insert(ignore_permissions=True)

		if hasattr(frappe, "publish_realtime"):
			frappe.publish_realtime(
				event="notification",
				message={"type": "Alert", "message": subject},
				user=user,
			)


def finalize_system_leave_application(doc):
	"""
	Insert + submit a leave application created by background logic (e.g. short leave).
	When Leave Application workflow is active, force Approved/Submitted and run on_submit.
	"""
	doc.status = "Open"
	doc.insert(ignore_permissions=True)

	if not get_workflow_name("Leave Application"):
		doc.status = "Approved"
		doc.submit()
		return doc

	frappe.db.set_value(
		"Leave Application",
		doc.name,
		{
			"workflow_state": "Approved",
			"status": "Approved",
			"docstatus": 1,
		},
		update_modified=False,
	)
	doc.reload()
	doc.run_method("on_submit")
	return doc


def _users_with_roles(roles: list[str]) -> list[str]:
	if not roles:
		return []
	return frappe.get_all(
		"Has Role",
		filters={"role": ["in", roles], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)


def _is_hr_user():
	roles = set(frappe.get_roles())
	return bool(roles.intersection({"HR Manager", "HR User", "System Manager"}))
