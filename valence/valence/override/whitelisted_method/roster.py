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
    Same source of truth as valence.api.get_offday_status:
    Holiday List's weekly_off flag, then Shift Assignment.weekly_off_days.
    Keeps Roster, Attendance, and the classic calendar all in agreement.
    """
    Employee = frappe.qb.DocType("Employee")
    query = frappe.qb.get_query("Employee", fields=["name", "holiday_list"], filters={"status": "Active"})
    for f in employee_filters:
        query = query.where(Employee[f] == employee_filters[f])
    employees = query.run(as_dict=True)

    start, end = getdate(month_start), getdate(month_end)
    weekly_offs = {}

    from valence.api import get_shift_weekly_off_days

    for emp in employees:
        off_weekdays = get_shift_weekly_off_days(emp.name, end)

        holiday_weekly_off_dates = set()
        if emp.holiday_list:
            for h in frappe.get_all(
                "Holiday",
                filters={"parent": emp.holiday_list, "holiday_date": ["between", [start, end]], "weekly_off": 1},
                pluck="holiday_date",
            ):
                holiday_weekly_off_dates.add(getdate(h))

        date = start
        while date <= end:
            if date in holiday_weekly_off_dates or date.strftime("%A").lower() in off_weekdays:
                weekly_offs.setdefault(emp.name, []).append({
                    "holiday": f"weekly-off-{emp.name}-{date}",
                    "holiday_date": str(date),
                    "description": "Weekly Off",
                    "weekly_off": 1,
                })
            date = add_days(date, 1)

    return weekly_offs