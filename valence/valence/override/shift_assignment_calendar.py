import frappe
import json
from frappe.utils import getdate, add_days, cstr
from datetime import timedelta

@frappe.whitelist()
def get_events(start, end, filters=None):
    employee = frappe.db.get_value(
        "Employee", {"user_id": frappe.session.user}, ["name", "company"], as_dict=True
    )
    if employee:
        employee = employee.name
    else:
        employee = ""

    assignments = get_shift_assignments(start, end, filters)
    return get_shift_events(assignments)


def get_shift_assignments(start: str, end: str, filters: str | list | None = None) -> list[dict]:
    if isinstance(filters, str):
        filters = json.loads(filters)
    if not filters:
        filters = []

    filters.extend([["start_date", "<=", end], ["docstatus", "=", 1]])
    or_filters = [["end_date", ">=", start], ["end_date", "is", "not set"]]

    return frappe.get_list(
        "Shift Assignment",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "start_date",
            "end_date",
            "employee_name",
            "employee",
            "shift_type",
            "custom_off_day",  # Added to fetch custom off days
            "docstatus",
        ],
    )

def get_holidays(company=None):
    """Fetch holidays from the Holiday List Doctype and its child table (holidays)."""

    # Fetch relevant Holiday Lists based on company (or global ones)
    holiday_lists = frappe.get_all(
        "Holiday List",
        filters={"company": company} if company else {},  # Filter by company if provided
        fields=["name", "from_date", "to_date"]
    )

    if not holiday_lists:
        return {}

    holidays = {}

    # Iterate through each Holiday List and extract child table entries
    for holiday_list in holiday_lists:
        holiday_dates = frappe.get_all(
            "Holiday",
            filters={"parent": holiday_list["name"], "parenttype": "Holiday List"},
            fields=["holiday_date", "description"]
        )

        for h in holiday_dates:
            holidays[getdate(h["holiday_date"])] = h["description"]

    return holidays


def get_shift_events(assignments: list[dict], company=None) -> list[dict]:
    events = []
    shift_timing_map = get_shift_type_timing([d.shift_type for d in assignments])
    holidays = get_holidays(company)  # Fetch holidays

    for d in assignments:
        daily_event_start = getdate(d.start_date)
        daily_event_end = getdate(d.end_date) if d.end_date else getdate()
        shift_start = shift_timing_map[d.shift_type]["start_time"]
        shift_end = shift_timing_map[d.shift_type]["end_time"]
        delta = timedelta(days=1)

        # Convert `custom_off_day` to a list
        off_days = []
        if d.custom_off_day:
            off_days = [day.strip().lower() for day in d.custom_off_day.split(",")]

        while daily_event_start <= daily_event_end:
            start_timing = frappe.utils.get_datetime(daily_event_start) + shift_start
            if shift_start > shift_end:
                end_timing = frappe.utils.get_datetime(daily_event_start) + shift_end + delta
            else:
                end_timing = frappe.utils.get_datetime(daily_event_start) + shift_end

            # Default event color
            event_color = "blue"  # Blue
            event_title = f"{cstr(d.employee_name)}: {cstr(d.shift_type)}"

            # If it's an off day, change color to orange
            if daily_event_start.strftime("%A").lower() in off_days:
                event_color = "#ffd1b3"

            # If it's a holiday, change color to green and show holiday description
            if daily_event_start in holidays:
                event_color = "#99ff99"
                holiday_description = holidays[daily_event_start]  # Get holiday description
                event_title += f" ({holiday_description})" 

            event = {
                "name": d.name,
                "doctype": "Shift Assignment",
                "start_date": start_timing,
                "end_date": end_timing,
                "title": event_title,  # Updated title with holiday name
                "docstatus": d.docstatus,
                "allDay": 0,
                "convertToUserTz": 0,
                "color": event_color,  # Background color
            }
            if event not in events:
                events.append(event)

            daily_event_start += delta

    return events

def get_shift_type_timing(shift_types):
    shift_timing_map = {}
    data = frappe.get_all(
        "Shift Type",
        filters={"name": ("IN", shift_types)},
        fields=["name", "start_time", "end_time"],
    )

    for d in data:
        shift_timing_map[d.name] = d

    return shift_timing_map
