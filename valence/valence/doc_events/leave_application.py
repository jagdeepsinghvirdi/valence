import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate
from frappe.model.workflow import get_workflow_name

# Shared by Track A (#8) and Track B (#3, #4 extras, #10, #11).
# Keep each rule in its own function; coordinate before editing this file.

SUPER_HOD_STATE = "Pending Super HOD Approval"
WORKING_LEAVE_DAYS_FIELD = "custom_working_leave_days"
# ≤ 3 working days → normal HOD approval; > 3 → Super HOD also required
SUPER_HOD_WORKING_DAYS_THRESHOLD = 3


def validate(doc, method=None):
	"""Leave Application validate — runs each rule in order."""
	set_working_leave_days(doc, method)
	validate_no_leave_on_present_day(doc, method)
	validate_resigned_employee_leave_type(doc, method)
	sync_leave_status_from_workflow(doc, method)


def before_submit(doc, method=None):
	"""Ensure HRMS status matches terminal workflow states before submit."""
	sync_leave_status_from_workflow(doc, method)


def on_update(doc, method=None):
	"""Side-effects after save (workflow notifications, etc.)."""
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
	#3 Backdated / normal leave length for approval routing.

	Counts working days between from_date and to_date, excluding:
	- Holidays (Holiday List)
	- Weekly offs (Holiday List weekly_off + Shift Assignment custom_off_day)

	Backdated leave is allowed (no advance-notice block). Workflow uses this
	field: ≤ 3 working days → HOD only; > 3 → Super HOD also.
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


def needs_super_hod_approval(working_days) -> bool:
	"""True when working leave days exceed the normal HOD-only threshold."""
	return flt(working_days) > SUPER_HOD_WORKING_DAYS_THRESHOLD


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


def validate_resigned_employee_leave_type(doc, method=None):
	"""
	#11 Resignation Option (Track B)

	Resigned / relieved employees may only apply LWP or Sick Leave.
	HR roles can override.
	"""
	if getattr(frappe.flags, "ignore_resigned_leave_type_check", False):
		return

	if _is_hr_user():
		return

	if not doc.employee or not doc.leave_type:
		return

	emp = frappe.db.get_value(
		"Employee", doc.employee, ["status", "relieving_date"], as_dict=True
	)
	if not emp:
		return

	is_resigned = emp.status == "Left" or bool(emp.relieving_date)
	if not is_resigned:
		return

	if doc.leave_type not in ALLOWED_RESIGNED_LEAVE_TYPES:
		frappe.throw(
			_(
				"Resigned employees can only apply for Leave Without Pay or Sick Leave. "
				"Selected leave type: {0}."
			).format(frappe.bold(doc.leave_type)),
			title=_("Leave Type Not Allowed"),
		)


def notify_super_hod_if_needed(doc, method=None):
	"""
	#4 Extended Leave Approval — when HOD sends leave (> 3 working days) to Super HOD,
	create ToDos for Super HOD / HR Manager.
	"""
	if doc.get("workflow_state") != SUPER_HOD_STATE:
		return

	# Only when the state just changed into Super HOD pending
	before = doc.get_doc_before_save()
	if before and before.get("workflow_state") == SUPER_HOD_STATE:
		return

	_notify_super_hod_approvers(doc)


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
