import frappe

ALL_DAYS = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"}


def set_weekly_off_from_schedule(doc, method=None):
    if doc.custom_off_day:
        return
    if not doc.shift_schedule_assignment:
        return
    shift_schedule = frappe.db.get_value("Shift Schedule Assignment", doc.shift_schedule_assignment, "shift_schedule")
    if not shift_schedule:
        return

    repeat_on_days = {d.lower() for d in frappe.get_all("Assignment Rule Day", filters={"parent": shift_schedule}, pluck="day")}
    off_days = ALL_DAYS - repeat_on_days

    if len(off_days) == 1:
        doc.custom_off_day = list(off_days)[0].capitalize()
    elif len(off_days) > 1:
        # Field only supports one off day — flag rather than silently pick one
        frappe.throw(f"Shift Schedule has {len(off_days)} off days, but Shift Assignment only supports one weekly off day. Please select exactly one day off in Repeat On Days.")