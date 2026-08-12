import frappe
from frappe import _
from frappe.utils import formatdate, get_datetime, now_datetime
from frappe.model.workflow import get_workflow_name

# Shared by Track A (#8) and Track B (#3, #4 extras, #10, #11).
# Keep each rule in its own function; coordinate before editing this file.

SUPER_HOD_STATE = "Pending Super HOD Approval"


def validate(doc, method=None):
	"""Leave Application validate — runs each rule in order."""
	validate_72_hour_window(doc, method)
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



def validate_72_hour_window(doc, method=None):
	"""
	#3 72-Hour Leave Application Window (Track B, Day 1)

	Employees must apply at least 72 hours before leave start (from_date at 00:00).
	HR roles and system-created applications (short-leave half-day) can bypass.
	"""
	if getattr(frappe.flags, "ignore_72_hour_leave_window", False):
		return

	if _is_hr_user():
		return

	if not doc.from_date:
		return

	leave_start = get_datetime(doc.from_date)
	hours_until_leave = (leave_start - now_datetime()).total_seconds() / 3600

	if hours_until_leave < 72:
		frappe.throw(
			_(
				"Leave must be applied at least 72 hours before the leave start date ({0}). "
				"Please choose a later start date or contact HR."
			).format(formatdate(doc.from_date)),
			title=_("72-Hour Notice Required"),
		)


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
	#4 Extended Leave Approval — when HOD sends leave (≥ 3 days) to Super HOD,
	create ToDos + optional desk notification for Super HOD / HR Manager.
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

	subject = _("Leave needs Super HOD approval: {0}").format(doc.name)
	message = _(
		"Leave Application {0} for {1} ({2} days from {3} to {4}) needs Super HOD approval."
	).format(
		doc.name,
		doc.employee_name or doc.employee,
		doc.total_leave_days,
		formatdate(doc.from_date),
		formatdate(doc.to_date),
	)

	for user in users:
		if user in ("Administrator", "Guest"):
			continue
		# Avoid duplicate open ToDos for same leave + user
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

	# Workflow path: set terminal approved state + docstatus without UI transitions
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
