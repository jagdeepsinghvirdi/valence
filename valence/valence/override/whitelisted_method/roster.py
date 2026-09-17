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

    apply_left_events(events, month_start, month_end)

    return events


def apply_left_events(events, month_start, month_end):
    """
    Roster cells for employees with status 'Left' in Shift Assignment
    must display 'Left' as a blocked cell for the applicable dates.
    """
    if not events:
        return

    from datetime import timedelta

    m_start = getdate(month_start)
    m_end = getdate(month_end)

    target_employees = list(events.keys())
    if not target_employees:
        return

    filters = {
        "docstatus": 1,
        "status": "Left",
        "start_date": ["<=", m_end],
        "employee": ["in", target_employees],
    }

    left_assignments = frappe.get_all(
        "Shift Assignment",
        filters=filters,
        or_filters=[["end_date", ">=", m_start], ["end_date", "is", "not set"]],
        fields=["name", "employee", "start_date", "end_date"],
        order_by="start_date asc",
    )

    for assign in left_assignments:
        emp = assign.employee
        cur = max(getdate(assign.start_date), m_start)
        assign_end = getdate(assign.end_date) if assign.end_date else m_end
        end = min(assign_end, m_end)

        left_dates = set()
        while cur <= end:
            left_dates.add(str(cur))
            cur += timedelta(days=1)

        if not left_dates:
            continue

        # Strip regular shifts and weekly offs on Left dates
        existing = events.get(emp, [])
        filtered = [
            ev for ev in existing
            if not _is_date_in_left_dates(ev, left_dates)
        ]

        # Inject Left blocked event for each date
        for d_str in sorted(left_dates):
            filtered.append(
                {
                    "holiday": f"left-{emp}-{d_str}",
                    "holiday_date": d_str,
                    "description": "Left",
                }
            )

        events[emp] = filtered


def _is_date_in_left_dates(event, left_dates):
    # Holiday / weekly off date
    if "holiday_date" in event and str(event["holiday_date"]) in left_dates:
        return True
    # Shift start date
    if "start_date" in event:
        start_dt = str(getdate(event["start_date"]))
        if start_dt in left_dates:
            return True
    return False


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
