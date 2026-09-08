import frappe
from frappe.utils import getdate, add_days

from hrms.api.roster import get_events as hrms_get_events


@frappe.whitelist()
def get_events(month_start, month_end, employee_filters, shift_filters):
    events = hrms_get_events(month_start, month_end, employee_filters, shift_filters)
    weekly_offs = get_weekly_offs(month_start, month_end, employee_filters)
    for employee, off_days in weekly_offs.items():
        events.setdefault(employee, []).extend(off_days)
    return events


def get_weekly_offs(month_start, month_end, employee_filters):
    """
    Same source of truth as valence.api.get_day_type / get_day_type_map:
    Holiday List's weekly_off flag, then Shift Assignment.custom_off_day.
    Keeps Roster, Attendance, and the classic calendar all in agreement.
    """
    Employee = frappe.qb.DocType("Employee")
    query = frappe.qb.get_query("Employee", fields=["name", "holiday_list"], filters={"status": "Active"})
    for f in employee_filters:
        query = query.where(Employee[f] == employee_filters[f])
    employees = query.run(as_dict=True)

    start, end = getdate(month_start), getdate(month_end)
    weekly_offs = {}

    from valence.api import get_day_type_map

    emp_names = [emp.name for emp in employees if emp.get("name")]
    day_types = get_day_type_map(emp_names, start, end)

    for emp in employees:
        emp_name = emp.name
        date = start
        while date <= end:
            if day_types.get((emp_name, date)) == "Weekly Off":
                weekly_offs.setdefault(emp_name, []).append({
                    "holiday": f"weekly-off-{emp_name}-{date}",
                    "holiday_date": str(date),
                    "description": "Weekly Off",
                    "weekly_off": 1,
                })
            date = add_days(date, 1)

    return weekly_offs