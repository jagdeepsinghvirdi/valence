import frappe
from frappe.utils import getdate

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
    Weekly offs for the Roster, resolved per date by the canonical day-type map so
    Roster, Attendance and the Dashboard cannot disagree.
    """
    from valence.api import get_day_type_map

    Employee = frappe.qb.DocType("Employee")
    query = frappe.qb.get_query("Employee", fields=["name"], filters={"status": "Active"})
    for f in employee_filters:
        query = query.where(Employee[f] == employee_filters[f])
    employees = [row.name for row in query.run(as_dict=True)]

    if not employees:
        return {}

    start, end = getdate(month_start), getdate(month_end)
    day_types = get_day_type_map(employees, start, end)

    weekly_offs = {}
    for (employee, date), day_type in day_types.items():
        if day_type != "Weekly Off":
            continue
        weekly_offs.setdefault(employee, []).append(
            {
                "holiday": f"weekly-off-{employee}-{date}",
                "holiday_date": str(date),
                "description": "Weekly Off",
                "weekly_off": 1,
            }
        )

    return weekly_offs
