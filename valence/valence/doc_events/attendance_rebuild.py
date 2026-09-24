import calendar

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, nowdate

PROTECTED_STATUSES = ("On Leave", "Work From Home", "On Duty", "Present With Short Leave")


@frappe.whitelist()
def rebuild_month(month, year, employee=None, department=None, missing_only=1):
	month = cint(month)
	year = cint(year)
	missing_only = cint(missing_only)

	validate_period(month, year)

	if not frappe.has_permission("Attendance", "write"):
		frappe.throw(_("You are not permitted to rebuild Attendance."))

	employees = resolve_employees(employee, department)
	start, end = month_range(month, year)

	summaries = []
	totals = {"created": 0, "updated": 0, "skipped": 0}

	for employee_doc in employees:
		summary = rebuild_employee_month(employee_doc, start, end, missing_only)
		summaries.append(summary)
		for key in totals:
			totals[key] += summary[key]
		frappe.db.commit()

	return {
		"month": month,
		"year": year,
		"missing_only": missing_only,
		"employee_count": len(employees),
		"created": totals["created"],
		"updated": totals["updated"],
		"skipped": totals["skipped"],
		"employees": summaries,
		"rows": summaries[0]["rows"] if len(summaries) == 1 else [],
	}


def rebuild_employee_month(employee_doc, start, end, missing_only):
	existing_dates = set()
	if missing_only:
		existing_dates = {
			getdate(value)
			for value in frappe.get_all(
				"Attendance",
				filters={
					"employee": employee_doc.name,
					"attendance_date": ["between", [start, end]],
					"docstatus": ["<", 2],
				},
				pluck="attendance_date",
			)
		}

	rows = []
	created = updated = skipped = 0

	date_obj = start
	while date_obj <= end:
		if missing_only and date_obj in existing_dates:
			result = result_row(str(date_obj), "skipped", None, _("Already recorded"))
		else:
			result = rebuild_date(employee_doc, date_obj)

		rows.append(result)

		if result["action"] == "created":
			created += 1
		elif result["action"] == "updated":
			updated += 1
		else:
			skipped += 1

		date_obj = add_days(date_obj, 1)

	return {
		"employee": employee_doc.name,
		"employee_name": employee_doc.employee_name,
		"created": created,
		"updated": updated,
		"skipped": skipped,
		"rows": rows,
	}


def validate_period(month, year):
	if not (1 <= month <= 12):
		frappe.throw(_("Please select a valid Month."))
	if not year:
		frappe.throw(_("Please select a valid Year."))


def month_range(month, year):
	start = getdate(f"{year}-{month:02d}-01")
	end = getdate(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
	return start, end


def resolve_employees(employee=None, department=None):
	fields = ["name", "employee_name", "company", "date_of_joining", "relieving_date"]

	if employee:
		employee_doc = frappe.db.get_value("Employee", employee, fields, as_dict=True)
		if not employee_doc:
			frappe.throw(_("Employee {0} not found.").format(employee))
		return [employee_doc]

	if not department:
		frappe.throw(_("Please select an Employee or a Department."))

	departments = department_with_descendants(department)
	rows = frappe.get_all(
		"Employee",
		filters={"department": ["in", departments], "status": "Active"},
		fields=fields,
		order_by="employee_name asc",
		limit_page_length=0,
	)
	if not rows:
		frappe.throw(_("No active employees found in {0}.").format(department))

	return rows


def department_with_descendants(department):
	doc = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not doc or doc.lft is None or doc.rgt is None:
		return [department]

	return frappe.get_all(
		"Department",
		filters={"lft": [">=", doc.lft], "rgt": ["<=", doc.rgt]},
		pluck="name",
	) or [department]


def rebuild_date(employee_doc, date_obj):
	from valence.api import get_applicable_shift, get_day_type

	date_str = str(date_obj)

	if not within_employment(employee_doc, date_obj):
		return result_row(date_str, "skipped", None, _("Outside employment period"))

	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee_doc.name, "attendance_date": date_obj, "docstatus": ["<", 2]},
		["name", "status", "leave_application", "attendance_request", "docstatus"],
		as_dict=True,
	)

	if existing and is_protected(existing):
		return result_row(date_str, "skipped", existing.status, _("Leave or request record kept as is"))

	shift = get_applicable_shift(employee_doc.name, date_obj)
	day_type = get_day_type(employee_doc.name, date_obj)
	in_time, out_time = get_punch_pair(employee_doc.name, date_obj, shift)

	if not shift and not day_type and not in_time and not out_time:
		if existing:
			return result_row(date_str, "skipped", existing.status, _("No shift assigned"))
		return result_row(date_str, "skipped", None, _("No shift assigned and no punches"))

	status, hours = resolve_status(employee_doc.name, date_obj, shift, day_type, in_time, out_time)

	if existing:
		return apply_to_existing(existing, shift, status, hours, in_time, out_time, date_str)

	return create_attendance(employee_doc, date_obj, shift, status, hours, in_time, out_time, date_str)


def within_employment(employee_doc, date_obj):
	joining = getdate(employee_doc.date_of_joining) if employee_doc.date_of_joining else None
	relieving = getdate(employee_doc.relieving_date) if employee_doc.relieving_date else None

	if joining and date_obj < joining:
		return False
	if relieving and date_obj > relieving:
		return False

	return True


def is_protected(existing):
	if existing.leave_application or existing.attendance_request:
		return True

	return existing.status in PROTECTED_STATUSES


def get_punch_pair(employee, date_obj, shift):
	from valence.api import get_attendance_punch_window

	window_start, window_end = get_attendance_punch_window(employee, date_obj, shift)

	times = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [window_start, window_end]],
			"skip_auto_attendance": 0,
		},
		pluck="time",
		order_by="time asc",
	)
	if not times:
		return None, None

	if len(times) == 1:
		return get_datetime(times[0]), None

	return get_datetime(times[0]), get_datetime(times[-1])


def resolve_status(employee, date_obj, shift, day_type, in_time, out_time):
	if in_time and out_time:
		hours = round(flt((out_time - in_time).total_seconds()) / 3600, 1)
	else:
		hours = 0.0

	if in_time and not out_time:
		if day_type:
			return day_type, 0.0
		return "Mispunch", 0.0

	if not in_time and not out_time:
		if day_type:
			return day_type, 0.0
		if date_obj >= getdate(nowdate()):
			return "No punch", 0.0
		return "Absent", 0.0

	if day_type:
		return "Present", hours

	return hours_status(shift, hours), hours


def hours_status(shift, hours):
	from valence.valence.doc_events.attendance import get_shift_duration_hours

	if not shift:
		return "Present" if hours > 0 else "Absent"

	thresholds = frappe.db.get_value(
		"Shift Type",
		shift,
		["working_hours_threshold_for_half_day", "working_hours_threshold_for_absent"],
		as_dict=True,
	) or frappe._dict()

	half_day = flt(thresholds.get("working_hours_threshold_for_half_day"))
	absent = flt(thresholds.get("working_hours_threshold_for_absent"))
	duration = flt(get_shift_duration_hours(shift))

	if duration:
		half_day = min(half_day, duration)
		absent = min(absent, duration)

	if hours <= 0 or hours < absent:
		return "Absent"
	if hours < half_day:
		return "Half Day"

	return "Present"


def apply_to_existing(existing, shift, status, hours, in_time, out_time, date_str):
	current = frappe.db.get_value(
		"Attendance",
		existing.name,
		["status", "working_hours", "in_time", "out_time", "shift"],
		as_dict=True,
	)

	unchanged = (
		current.status == status
		and flt(current.working_hours) == flt(hours)
		and current.in_time == in_time
		and current.out_time == out_time
		and (current.shift or None) == (shift or None)
	)
	if unchanged:
		return result_row(date_str, "skipped", status, _("Already correct"), existing.name)

	frappe.db.set_value(
		"Attendance",
		existing.name,
		{
			"status": status,
			"working_hours": hours,
			"in_time": in_time,
			"out_time": out_time,
			"shift": shift,
		},
		update_modified=False,
	)

	return result_row(date_str, "updated", status, _("Recalculated from check-ins"), existing.name)


def create_attendance(employee_doc, date_obj, shift, status, hours, in_time, out_time, date_str):
	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee_doc.name,
			"employee_name": employee_doc.employee_name,
			"attendance_date": date_obj,
			"company": employee_doc.company,
			"shift": shift,
			"status": status,
			"working_hours": hours,
			"in_time": in_time,
			"out_time": out_time,
		}
	)
	doc.flags.ignore_validate = True
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.db_set("docstatus", 1)

	return result_row(date_str, "created", status, _("Created from check-ins"), doc.name)


def result_row(date_str, action, status, note, attendance=None):
	return {
		"date": date_str,
		"action": action,
		"status": status,
		"note": note,
		"attendance": attendance,
	}


@frappe.whitelist()
def fetch_month_shifts(month, year, employee=None, department=None):
	from hrms.hr.doctype.employee_checkin.employee_checkin import bulk_fetch_shift

	month = cint(month)
	year = cint(year)

	validate_period(month, year)

	if not frappe.has_permission("Employee Checkin", "write"):
		frappe.throw(_("You are not permitted to update Employee Checkins."))

	employees = resolve_employees(employee, department)
	start, end = month_range(month, year)
	window_start = add_days(start, -1)
	window_end = add_days(end, 2)

	summaries = []
	totals = {"checkins": 0, "matched": 0, "unmatched": 0}

	for employee_doc in employees:
		names = frappe.get_all(
			"Employee Checkin",
			filters={
				"employee": employee_doc.name,
				"time": ["between", [window_start, window_end]],
			},
			pluck="name",
			order_by="time asc",
		)

		for index in range(0, len(names), 200):
			bulk_fetch_shift(names[index : index + 200])

		frappe.db.commit()

		matched = frappe.db.count(
			"Employee Checkin",
			{
				"employee": employee_doc.name,
				"time": ["between", [window_start, window_end]],
				"shift": ["is", "set"],
			},
		)

		summary = {
			"employee": employee_doc.name,
			"employee_name": employee_doc.employee_name,
			"checkins": len(names),
			"matched": matched,
			"unmatched": len(names) - matched,
		}
		summaries.append(summary)
		for key in totals:
			totals[key] += summary[key]

	return {
		"month": month,
		"year": year,
		"employee_count": len(employees),
		"checkins": totals["checkins"],
		"matched": totals["matched"],
		"unmatched": totals["unmatched"],
		"employees": summaries,
	}
