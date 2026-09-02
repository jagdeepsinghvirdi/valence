import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from valence.api import get_day_type_map
from valence.valence.attendance_code import get_attendance_code
from valence.valence.attendance_summary import MISPUNCH_CODE, score_codes
from valence.valence.doc_events.attendance import (
	get_double_shift_factor,
	get_offday_full_day_hours,
	get_shift_duration_hours,
	get_shift_midpoint,
	get_worked_half,
)
from valence.valence.override.query import (
	_employee_for_user,
	_has_unrestricted_leave_access,
	_is_hod,
)

ABSENT_CODE = "A"
WEEKLY_OFF_CODE = "WO"
HOLIDAY_CODE = "H"

NON_REPORTABLE_CODES = {
	"No punch": ABSENT_CODE,
	"Mispunch": MISPUNCH_CODE,
}

ATTENDANCE_FIELDS = (
	"name",
	"employee",
	"attendance_date",
	"status",
	"leave_type",
	"working_hours",
	"in_time",
	"out_time",
	"shift",
	"half_day_status",
	"attendance_request",
)

EMPLOYEE_COLUMNS = (
	("sr_no", "S.No", "Int", None, 60),
	("employee", "E-Code", "Link", "Employee", 110),
	("employee_name", "Name", "Data", None, 180),
	("department_label", "Department", "Data", None, 140),
	("function_label", "Function", "Data", None, 140),
	("module_label", "Module", "Data", None, 140),
	("designation", "Designation", "Link", "Designation", 140),
	("date_of_joining", "Date of Joining", "Date", None, 110),
	("category", "Category", "Data", None, 110),
	("grade", "Grade", "Data", None, 90),
	("sort_key", "Sort", "Data", None, 90),
)

SUMMARY_COLUMNS = (
	("ab", "AB", 60),
	("wd", "WD", 60),
	("wo", "WO", 60),
	("nh", "NH", 60),
	("pday", "Pday", 70),
	("ot", "OT", 60),
	("dd", "DD", 60),
	("rot", "ROT", 60),
	("paid_leaves", "Paid Leaves", 100),
	("present_days", "Present Days", 110),
	("co", "CO", 60),
	("lwp", "LWP", 60),
	("leave_absent", "Leave + Absent", 120),
)

REMARK_COLUMNS = (
	("hold", "Hold", "Data", 130),
	("remarks", "Remarks", "Data", 180),
	("hr_remarks", "HR Remarks", "Data", 180),
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end, total_days = get_period(filters)

	employees = get_employees(filters, start, end)
	columns = build_columns(total_days)

	if not employees:
		return columns, []

	employee_names = [row.name for row in employees]

	day_types = get_day_type_map(employee_names, start, end)
	attendance_map = get_attendance_map(employee_names, start, end)
	shift_cache = build_shift_cache(attendance_map)
	request_reasons = get_request_reasons(attendance_map)
	remarks = get_remarks(employee_names, filters)
	full_day_hours = get_offday_full_day_hours()

	data = []
	for index, employee in enumerate(employees, start=1):
		row = build_employee_row(index, employee)
		codes = []

		for day in range(1, total_days + 1):
			date_obj = getdate(f"{start.year}-{start.month:02d}-{day:02d}")
			fieldname = f"d{day}"

			if not within_employment(employee, date_obj):
				row[fieldname] = ""
				continue

			record = attendance_map.get((employee.name, date_obj))
			day_type = day_types.get((employee.name, date_obj))
			code = resolve_code(
				record, day_type, shift_cache, request_reasons, full_day_hours
			)

			row[fieldname] = code
			row[f"{fieldname}_status"] = record.get("status") if record else None
			if code:
				codes.append(code)

		row.update(score_codes(codes))
		row.update(remarks.get(employee.name, {}))
		data.append(row)

	return columns, data


def get_period(filters):
	today = getdate()
	month = cint(filters.get("month")) or today.month
	year = cint(filters.get("year")) or today.year

	if month < 1 or month > 12:
		frappe.throw(_("Please select a valid month."))

	total_days = calendar.monthrange(year, month)[1]
	start = getdate(f"{year}-{month:02d}-01")
	end = getdate(f"{year}-{month:02d}-{total_days:02d}")

	return start, end, total_days


def build_columns(total_days):
	columns = []

	for fieldname, label, fieldtype, options, width in EMPLOYEE_COLUMNS:
		column = {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": fieldtype,
			"width": width,
		}
		if options:
			column["options"] = options
		columns.append(column)

	for day in range(1, total_days + 1):
		columns.append(
			{
				"fieldname": f"d{day}",
				"label": str(day),
				"fieldtype": "Data",
				"width": 60,
			}
		)

	for fieldname, label, width in SUMMARY_COLUMNS:
		columns.append(
			{
				"fieldname": fieldname,
				"label": _(label),
				"fieldtype": "Float",
				"precision": 2,
				"width": width,
			}
		)

	for fieldname, label, fieldtype, width in REMARK_COLUMNS:
		columns.append(
			{
				"fieldname": fieldname,
				"label": _(label),
				"fieldtype": fieldtype,
				"width": width,
			}
		)

	return columns


def get_employees(filters, start, end):
	conditions = {
		"date_of_joining": ["<=", end],
	}

	if filters.get("company"):
		conditions["company"] = filters.get("company")
	if filters.get("employee"):
		conditions["name"] = filters.get("employee")
	if filters.get("department"):
		conditions["department"] = filters.get("department")
	if filters.get("status"):
		conditions["status"] = filters.get("status")

	scope = get_permitted_employees(filters)
	if scope is not None:
		if not scope:
			return []
		conditions["name"] = ["in", scope]

	rows = frappe.get_list(
		"Employee",
		filters=conditions,
		or_filters=[
			["relieving_date", ">=", start],
			["relieving_date", "is", "not set"],
		],
		fields=[
			"name",
			"employee_name",
			"employee_number",
			"department",
			"designation",
			"date_of_joining",
			"relieving_date",
			"status",
			"company",
		],
		order_by="employee_name asc",
		limit_page_length=0,
	)

	attach_optional_fields(rows)
	attach_hierarchy(rows)

	function_filter = filters.get("function")
	module_filter = filters.get("module")
	if function_filter:
		rows = [
			r
			for r in rows
			if function_filter in (r.get("function_dept"), r.get("function_label"))
		]
	if module_filter:
		rows = [
			r
			for r in rows
			if module_filter in (r.get("module_dept"), r.get("module_label"))
		]

	rows.sort(key=lambda r: (r.get("sort_key") or "", r.get("employee_name") or ""))
	return rows


def get_permitted_employees(filters):
	user = frappe.session.user

	if _has_unrestricted_leave_access(user):
		return None

	employee = _employee_for_user(user)

	if _is_hod(user) and employee and employee.get("department"):
		departments = get_department_descendants(employee.department)
		rows = frappe.get_all(
			"Employee",
			filters={"department": ["in", departments]},
			pluck="name",
		)
		if employee.get("name") and employee.name not in rows:
			rows.append(employee.name)
		return rows

	return [employee.name] if employee and employee.get("name") else []


def get_department_descendants(department):
	bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return [department]

	rows = frappe.get_all(
		"Department",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
	)
	return rows or [department]


def attach_optional_fields(rows):
	optional = {
		"grade": frappe.db.has_column("Employee", "grade"),
		"employment_type": frappe.db.has_column("Employee", "employment_type"),
	}

	available = [field for field, exists in optional.items() if exists]
	if not available or not rows:
		for row in rows:
			row["grade"] = None
			row["category"] = None
		return

	names = [row.name for row in rows]
	extra = {
		item.name: item
		for item in frappe.get_all(
			"Employee",
			filters={"name": ["in", names]},
			fields=["name"] + available,
		)
	}

	for row in rows:
		item = extra.get(row.name) or {}
		row["grade"] = item.get("grade")
		row["category"] = item.get("employment_type")


def attach_hierarchy(rows):
	departments = {row.get("department") for row in rows if row.get("department")}
	tree = get_department_tree(departments)

	for row in rows:
		chain = department_chain(row.get("department"), tree)
		labels = [node[1] for node in chain]
		names = [node[0] for node in chain]

		row["department_label"] = labels[0] if len(labels) >= 1 else None
		row["function_label"] = labels[1] if len(labels) >= 2 else None
		row["module_label"] = labels[-1] if len(labels) >= 3 else None
		row["department_dept"] = names[0] if len(names) >= 1 else None
		row["function_dept"] = names[1] if len(names) >= 2 else None
		row["module_dept"] = names[-1] if len(names) >= 3 else None
		row["sort_key"] = " / ".join(labels) if labels else ""


def get_department_tree(departments):
	if not departments:
		return {}

	tree = {
		row.name: row
		for row in frappe.get_all(
			"Department",
			fields=["name", "department_name", "parent_department", "is_group"],
			limit_page_length=0,
		)
	}
	return tree


def department_chain(department, tree):
	chain = []
	seen = set()
	current = department

	while current and current in tree and current not in seen:
		seen.add(current)
		chain.append(tree[current])
		current = tree[current].get("parent_department")

	chain.reverse()

	if chain and not chain[0].get("parent_department") and cint(chain[0].get("is_group")) and len(chain) > 1:
		chain = chain[1:]

	return [(node.get("name"), node.get("department_name") or node.get("name")) for node in chain]


def within_employment(employee, date_obj):
	joining = employee.get("date_of_joining")
	if joining and date_obj < getdate(joining):
		return False

	relieving = employee.get("relieving_date")
	if relieving and date_obj > getdate(relieving):
		return False

	return True


def get_attendance_map(employees, start, end):
	rows = frappe.get_all(
		"Attendance",
		filters={
			"employee": ["in", employees],
			"attendance_date": ["between", [start, end]],
			"docstatus": ["<", 2],
		},
		fields=list(ATTENDANCE_FIELDS),
		limit_page_length=0,
	)

	return {(row.employee, getdate(row.attendance_date)): row for row in rows}


def build_shift_cache(attendance_map):
	shifts = {row.get("shift") for row in attendance_map.values() if row.get("shift")}

	cache = {}
	for shift in shifts:
		cache[shift] = {
			"duration": get_shift_duration_hours(shift),
			"midpoint": get_shift_midpoint(shift),
		}
	return cache


def get_request_reasons(attendance_map):
	requests = {
		row.get("attendance_request")
		for row in attendance_map.values()
		if row.get("attendance_request")
	}
	if not requests:
		return {}

	return {
		row.name: row.reason
		for row in frappe.get_all(
			"Attendance Request",
			filters={"name": ["in", sorted(requests)]},
			fields=["name", "reason"],
		)
	}


def resolve_code(record, day_type, shift_cache, request_reasons, full_day_hours):
	if not record:
		if day_type == "Weekly Off":
			return WEEKLY_OFF_CODE
		if day_type == "Holiday":
			return HOLIDAY_CODE
		return ""

	status = record.get("status")
	if status in NON_REPORTABLE_CODES:
		return NON_REPORTABLE_CODES[status]

	shift = shift_cache.get(record.get("shift")) or {}
	hours = flt(record.get("working_hours"))

	context = {
		"day_type": day_type,
		"full_day_hours": full_day_hours,
		"double_factor": get_double_shift_factor(
			record.get("shift"), hours, shift_len=shift.get("duration")
		),
		"worked_half": get_worked_half(
			record.get("shift"),
			record.get("in_time"),
			record.get("out_time"),
			midpoint=shift.get("midpoint"),
		),
		"request_reason": request_reasons.get(record.get("attendance_request")),
	}

	return get_attendance_code(record, context) or ""


def get_remarks(employees, filters):
	month = cint(filters.get("month")) or getdate().month
	year = cint(filters.get("year")) or getdate().year

	rows = frappe.get_all(
		"Attendance Month Remark",
		filters={
			"employee": ["in", employees],
			"month": month,
			"year": year,
		},
		fields=["employee", "hold", "remarks", "hr_remarks"],
		limit_page_length=0,
	)

	return {
		row.employee: {
			"hold": row.hold,
			"remarks": row.remarks,
			"hr_remarks": row.hr_remarks,
		}
		for row in rows
	}


def build_employee_row(index, employee):
	return {
		"sr_no": index,
		"employee": employee.name,
		"employee_name": employee.get("employee_name"),
		"department_label": employee.get("department_label"),
		"function_label": employee.get("function_label"),
		"module_label": employee.get("module_label"),
		"designation": employee.get("designation"),
		"date_of_joining": employee.get("date_of_joining"),
		"category": employee.get("category"),
		"grade": employee.get("grade"),
		"sort_key": employee.get("sort_key"),
		"hold": None,
		"remarks": None,
		"hr_remarks": None,
	}


@frappe.whitelist()
def save_month_remark(employee, month, year, hold=None, remarks=None, hr_remarks=None):
	frappe.only_for(("HR Manager", "HR User"))

	if not frappe.has_permission("Attendance Month Remark", "write"):
		frappe.throw(_("Not permitted to update attendance remarks."), frappe.PermissionError)

	if not employee or not frappe.db.exists("Employee", employee):
		frappe.throw(_("Invalid Employee."))

	permitted = get_permitted_employees(frappe._dict())
	if permitted is not None and employee not in permitted:
		frappe.throw(_("Not permitted for this employee."), frappe.PermissionError)

	month = cint(month)
	year = cint(year)

	name = frappe.db.get_value(
		"Attendance Month Remark",
		{"employee": employee, "month": month, "year": year},
		"name",
	)

	if name:
		doc = frappe.get_doc("Attendance Month Remark", name)
	else:
		doc = frappe.new_doc("Attendance Month Remark")
		doc.employee = employee
		doc.month = month
		doc.year = year

	doc.hold = hold or None
	doc.remarks = remarks or None
	doc.hr_remarks = hr_remarks or None
	doc.save()

	return {
		"employee": doc.employee,
		"hold": doc.hold,
		"remarks": doc.remarks,
		"hr_remarks": doc.hr_remarks,
	}
