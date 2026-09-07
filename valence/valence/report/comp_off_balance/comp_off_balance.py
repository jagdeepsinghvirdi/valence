import frappe
from frappe import _
from frappe.utils import flt, get_year_start, getdate, nowdate

from valence.valence.doc_events.comp_off_usage import (
	get_comp_off_balance,
	get_comp_off_statement,
)
from valence.valence.override.query import (
	_employee_for_user,
	_has_unrestricted_leave_access,
	_is_hod,
)


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 140,
		},
		{
			"label": _("Earned"),
			"fieldname": "earned",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Consumed"),
			"fieldname": "consumed",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Balance"),
			"fieldname": "balance",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("As-on Date"),
			"fieldname": "as_on_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("OT"),
			"fieldname": "ot",
			"fieldtype": "Float",
			"width": 100,
		},
	]


def get_data(filters):
	to_date = filters.get("to_date") or filters.get("as_on_date") or nowdate()
	from_date = filters.get("from_date") or get_year_start(to_date)
	as_on_date = to_date

	employees = get_employees(filters)
	data = []

	for emp in employees:
		statement = get_comp_off_statement(emp.name, from_date, to_date)
		earned = sum(flt(entry.get("earned")) for entry in statement)
		consumed = sum(flt(entry.get("consumed")) for entry in statement)
		balance = flt(get_comp_off_balance(emp.name, on_date=to_date))
		ot = flt(earned - consumed, 2)

		data.append({
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"department": emp.department,
			"earned": earned,
			"consumed": consumed,
			"balance": balance,
			"as_on_date": as_on_date,
			"ot": ot,
		})

	return data


def get_employees(filters):
	conditions = {}

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
		if "name" in conditions:
			if conditions["name"] not in scope:
				return []
		else:
			conditions["name"] = ["in", scope]

	return frappe.get_list(
		"Employee",
		filters=conditions,
		fields=["name", "employee_name", "department"],
		order_by="employee_name asc",
		limit_page_length=0,
	)


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