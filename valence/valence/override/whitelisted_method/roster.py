import frappe
from frappe.utils import cint, getdate

from hrms.api.roster import get_events as hrms_get_events


@frappe.whitelist()
def get_events(month_start, month_end, employee_filters, shift_filters):
    events = hrms_get_events(month_start, month_end, employee_filters, shift_filters)
    day_types = get_day_types(month_start, month_end, employee_filters)
    covered = {employee for employee, _ in day_types}

    for employee in list(events):
        if employee not in covered:
            continue
        events[employee] = [
            event for event in events[employee] if not _is_weekly_off_holiday(event)
        ]

    for employee, off_days in build_weekly_offs(day_types).items():
        events.setdefault(employee, []).extend(off_days)

    return events


def _is_weekly_off_holiday(event):
    return "holiday" in event and cint(event.get("weekly_off"))


def get_day_types(month_start, month_end, employee_filters):
    from valence.api import get_day_type_map

    Employee = frappe.qb.DocType("Employee")
    query = frappe.qb.get_query("Employee", fields=["name"], filters={"status": "Active"})
    for f in employee_filters:
        query = query.where(Employee[f] == employee_filters[f])
    employees = [row.name for row in query.run(as_dict=True)]

    if not employees:
        return {}

    return get_day_type_map(employees, getdate(month_start), getdate(month_end))


def build_weekly_offs(day_types):
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


def get_weekly_offs(month_start, month_end, employee_filters):
    return build_weekly_offs(get_day_types(month_start, month_end, employee_filters))
