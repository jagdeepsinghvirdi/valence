"""
Valence Attendance Test Data Seeder

Usage from a Frappe bench:

    bench --site valence.localhost execute valence.dev.seed_attendance.run
    bench --site valence.localhost execute valence.dev.seed_attendance.cleanup
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, getdate


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MARKER = "VALENCE_ATTENDANCE_SEED"

EMPLOYEE_NAMES = [
    f"Valence Attendance {index:02d}"
    for index in range(1, 9)
]

EMPLOYEE_NUMBERS = {
    index: f"{MARKER}-{index:02d}"
    for index in range(1, 9)
}

SHIFT_NAMES = {
    "day": f"{MARKER} Day Shift",
    "overnight": f"{MARKER} Overnight Shift",
    "twelve_hour": f"{MARKER} 12 Hour Shift",
    "double": f"{MARKER} Double Shift",
}

BASE_DATE = add_days(getdate(), 2)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


def _get_company():
    company = frappe.db.get_single_value("Global Defaults", "default_company")

    if not company:
        company = frappe.db.get_value("Company", {}, "name")

    if not company:
        frappe.throw("No Company found.")

    return company


def _get_department():
    return frappe.db.get_value("Department", {}, "name")


def _get_designation():
    return frappe.db.get_value("Designation", {}, "name")


def _get_branch():
    return frappe.db.get_value("Branch", {}, "name")


def _employee_name(index):
    return EMPLOYEE_NAMES[index - 1]


def _employee_number(index):
    return EMPLOYEE_NUMBERS[index]


def _get_employee(index):
    employee_number = _employee_number(index)
    employee_name = _employee_name(index)

    # Prefer the stable seeder-specific identifier.
    if _has_field("Employee", "employee_number"):
        existing = frappe.db.get_value(
            "Employee",
            {"employee_number": employee_number},
            "name",
        )
        if existing:
            return existing

    # Backward-compatible lookup for the employees created by the earlier
    # version of this seeder.
    return frappe.db.get_value(
        "Employee",
        {"employee_name": employee_name},
        "name",
    )


def _delete_if_exists(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        return False

    doc = frappe.get_doc(doctype, name)

    if doc.docstatus == 1:
        doc.cancel()

    frappe.delete_doc(
        doctype,
        name,
        force=True,
        ignore_permissions=True,
    )

    return True


def _submit_if_draft(doc):
    if doc.docstatus == 0:
        doc.submit()
    return doc


def _ensure_field_value(doc, fieldname, value):
    if _has_field(doc.doctype, fieldname):
        setattr(doc, fieldname, value)


def _weekly_off_date():
    """Return the first Sunday on or after BASE_DATE."""
    days_to_sunday = (6 - getdate(BASE_DATE).weekday()) % 7
    return add_days(BASE_DATE, days_to_sunday)


WEEKLY_OFF_DATE = _weekly_off_date()
HOLIDAY_DATE = add_days(BASE_DATE, 11)
DOUBLE_SHIFT_DATE = add_days(BASE_DATE, 12)
OD_HALF_DAY_DATE = add_days(BASE_DATE, 13)


# ---------------------------------------------------------------------------
# Holiday List
# ---------------------------------------------------------------------------


def create_holiday_list():
    """Create or reuse the seeder Holiday List and its test holiday."""
    holiday_list_name = f"{MARKER} Holiday List"

    if frappe.db.exists("Holiday List", {"name": holiday_list_name}):
        holiday_list = frappe.get_doc("Holiday List", holiday_list_name)
    else:
        holiday_list = frappe.new_doc("Holiday List")
        holiday_list.name = holiday_list_name
        holiday_list.holiday_list_name = holiday_list_name
        holiday_list.from_date = BASE_DATE
        holiday_list.to_date = add_days(BASE_DATE, 30)

    existing_holiday = next(
        (
            row
            for row in holiday_list.get("holidays", [])
            if str(row.holiday_date) == str(HOLIDAY_DATE)
        ),
        None,
    )

    if not existing_holiday:
        holiday_list.append(
            "holidays",
            {
                "holiday_date": HOLIDAY_DATE,
                "description": f"{MARKER} Test Holiday",
                "weekly_off": 0,
            },
        )

    if holiday_list.is_new():
        holiday_list.insert(ignore_permissions=True)
    else:
        holiday_list.save(ignore_permissions=True)

    return holiday_list.name




def assign_holiday_list_to_employees(employees, holiday_list):
    """Assign the seeder Holiday List to seeded employees."""
    if not _has_field("Employee", "holiday_list"):
        return

    for employee in employees:
        current = frappe.db.get_value(
            "Employee",
            employee,
            "holiday_list",
        )

        if current != holiday_list:
            frappe.db.set_value(
                "Employee",
                employee,
                "holiday_list",
                holiday_list,
                update_modified=False,
            )







# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


def create_employees():
    company = _get_company()
    department = _get_department()
    designation = _get_designation()
    branch = _get_branch()

    employees = []

    for index in range(1, 9):
        employee_name = _employee_name(index)
        employee_number = _employee_number(index)
        existing = _get_employee(index)

        if existing:
            if _has_field("Employee", "employee_number"):
                current_number = frappe.db.get_value(
                    "Employee", existing, "employee_number"
                )
                if current_number != employee_number:
                    frappe.db.set_value(
                        "Employee",
                        existing,
                        "employee_number",
                        employee_number,
                        update_modified=False,
                    )
            employees.append(existing)
            continue

        values = {
            "doctype": "Employee",
            "employee_name": employee_name,
            "first_name": f"Valence Attendance {index:02d}",
            "gender": "Prefer not to say",
            "date_of_birth": add_days(getdate(), -25 * 365),
            "date_of_joining": add_days(getdate(), -30),
            "status": "Active",
            "company": company,
        }

        if _has_field("Employee", "employee_number"):
            values["employee_number"] = employee_number
        if department:
            values["department"] = department
        if designation:
            values["designation"] = designation
        if branch:
            values["branch"] = branch

        employee = frappe.get_doc(values)
        employee.insert(ignore_permissions=True)
        employees.append(employee.name)

    return employees


# ---------------------------------------------------------------------------
# Shift Types
# ---------------------------------------------------------------------------


def _get_or_create_shift(
    key,
    start_time,
    end_time,
    holiday_list=None,
    half_day_threshold=4,
    absent_threshold=0,
):
    shift_name = SHIFT_NAMES[key]

    if frappe.db.exists("Shift Type", {"name": shift_name}):
        shift = frappe.get_doc("Shift Type", shift_name)
    else:
        shift = frappe.new_doc("Shift Type")
        shift.name = shift_name
        shift.start_time = start_time
        shift.end_time = end_time

    shift.start_time = start_time
    shift.end_time = end_time

    if holiday_list:
        _ensure_field_value(shift, "holiday_list", holiday_list)

    _ensure_field_value(
        shift,
        "working_hours_threshold_for_half_day",
        half_day_threshold,
    )
    _ensure_field_value(
        shift,
        "working_hours_threshold_for_absent",
        absent_threshold,
    )
    _ensure_field_value(
        shift,
        "begin_check_in_before_shift_start_time",
        60,
    )
    _ensure_field_value(
        shift,
        "allow_check_out_after_shift_end_time",
        60,
    )
    _ensure_field_value(
        shift,
        "mark_auto_attendance_on_holidays",
        0,
    )

    if shift.is_new():
        shift.insert(ignore_permissions=True)
    else:
        shift.save(ignore_permissions=True)

    return shift.name


def create_shift_types(holiday_list):
    return {
        "day": _get_or_create_shift(
            "day",
            "09:00:00",
            "18:00:00",
            holiday_list,
            half_day_threshold=4,
            absent_threshold=0,
        ),
        "overnight": _get_or_create_shift(
            "overnight",
            "20:00:00",
            "05:00:00",
            holiday_list,
            half_day_threshold=4,
            absent_threshold=0,
        ),
        "twelve_hour": _get_or_create_shift(
            "twelve_hour",
            "08:00:00",
            "20:00:00",
            holiday_list,
            half_day_threshold=6,
            absent_threshold=0,
        ),
        "double": _get_or_create_shift(
            "double",
            "09:00:00",
            "21:00:00",
            holiday_list,
            half_day_threshold=6,
            absent_threshold=0,
        ),
    }


# ---------------------------------------------------------------------------
# Shift Assignment
# ---------------------------------------------------------------------------


def create_shift_assignment(
    employee,
    shift_type,
    start_date,
    *,
    off_day=None,
):
    existing = frappe.db.exists(
        "Shift Assignment",
        {
            "employee": employee,
            "shift_type": shift_type,
            "start_date": start_date,
            "docstatus": ["<", 2],
        },
    )

    if existing:
        assignment = frappe.get_doc("Shift Assignment", existing)
        if _has_field("Shift Assignment", "description"):
            frappe.db.set_value(
                "Shift Assignment", existing, "description", MARKER, update_modified=False
            )
        if assignment.docstatus == 0:
            _submit_if_draft(assignment)
        return assignment.name

    values = {
        "doctype": "Shift Assignment",
        "employee": employee,
        "shift_type": shift_type,
        "start_date": start_date,
        "status": "Active",
    }

    assignment = frappe.get_doc(values)
    _ensure_field_value(assignment, "description", MARKER)

    if off_day:
        _ensure_field_value(assignment, "custom_off_day", off_day)

    assignment.insert(ignore_permissions=True)
    _submit_if_draft(assignment)

    return assignment.name


def create_shift_assignments(employees, shifts):
    assignments = []

    assignments.append(
        create_shift_assignment(employees[0], shifts["day"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(employees[1], shifts["day"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(employees[2], shifts["day"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(employees[3], shifts["overnight"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(employees[4], shifts["twelve_hour"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(
            employees[5],
            shifts["day"],
            BASE_DATE,
            off_day="Sunday",
        )
    )
    assignments.append(
        create_shift_assignment(employees[6], shifts["day"], BASE_DATE)
    )
    assignments.append(
        create_shift_assignment(employees[7], shifts["double"], BASE_DATE)
    )

    return assignments


# ---------------------------------------------------------------------------
# Employee Checkin
# ---------------------------------------------------------------------------


def create_checkin(employee, timestamp, log_type):
    existing = frappe.db.exists(
        "Employee Checkin",
        {
            "employee": employee,
            "time": timestamp,
            "log_type": log_type,
        },
    )

    if existing:
        if _has_field("Employee Checkin", "device_id"):
            frappe.db.set_value(
                "Employee Checkin", existing, "device_id", MARKER, update_modified=False
            )
        return existing

    checkin = frappe.get_doc(
        {
            "doctype": "Employee Checkin",
            "employee": employee,
            "time": timestamp,
            "log_type": log_type,
        }
    )

    _ensure_field_value(checkin, "device_id", MARKER)
    checkin.insert(ignore_permissions=True)
    return checkin.name


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


def create_attendance(
    employee,
    attendance_date,
    *,
    status=None,
    in_time=None,
    out_time=None,
    shift=None,
):
    existing = frappe.db.exists(
        "Attendance",
        {
            "employee": employee,
            "attendance_date": attendance_date,
            "docstatus": ["!=", 2],
        },
    )

    if existing:
        attendance = frappe.get_doc("Attendance", existing)
        if _has_field("Attendance", "remarks"):
            frappe.db.set_value(
                "Attendance", existing, "remarks", f"{MARKER} attendance test record", update_modified=False
            )
        if attendance.docstatus == 0:
            _submit_if_draft(attendance)
        return attendance.name

    values = {
        "doctype": "Attendance",
        "employee": employee,
        "company": _get_company(),
        "attendance_date": attendance_date,
    }

    if status:
        values["status"] = status
    if in_time:
        values["in_time"] = in_time
    if out_time:
        values["out_time"] = out_time
    if shift:
        values["shift"] = shift

    attendance = frappe.get_doc(values)
    _ensure_field_value(attendance, "remarks", f"{MARKER} attendance test record")
    attendance.insert(ignore_permissions=True)
    _submit_if_draft(attendance)

    return attendance.name


# ---------------------------------------------------------------------------
# Attendance Request
# ---------------------------------------------------------------------------


def create_attendance_request(
    employee,
    request_date,
    reason,
    explanation,
    *,
    half_day=False,
):
    existing = frappe.db.exists(
        "Attendance Request",
        {
            "employee": employee,
            "reason": reason,
            "from_date": request_date,
            "to_date": request_date,
        },
    )

    if existing:
        request = frappe.get_doc("Attendance Request", existing)
        if request.docstatus == 0:
            _submit_if_draft(request)
        return request.name

    values = {
        "doctype": "Attendance Request",
        "employee": employee,
        "reason": reason,
        "explanation": explanation,
        "from_date": request_date,
        "to_date": request_date,
    }

    if half_day:
        values["half_day"] = 1
        if _has_field("Attendance Request", "half_day_date"):
            values["half_day_date"] = request_date

    request = frappe.get_doc(values)
    request.insert(ignore_permissions=True)
    _submit_if_draft(request)

    return request.name


# ---------------------------------------------------------------------------
# Leave Application
# ---------------------------------------------------------------------------


def ensure_leave_type():
    """Ensure a Leave Without Pay type exists for deterministic test data."""
    leave_type = frappe.db.get_value(
        "Leave Type",
        {"is_lwp": 1},
        "name",
    )
    if leave_type:
        return leave_type

    leave_type_name = "Leave Without Pay"
    if frappe.db.exists("Leave Type", leave_type_name):
        return leave_type_name

    leave_type = frappe.get_doc(
        {
            "doctype": "Leave Type",
            "leave_type_name": leave_type_name,
            "is_lwp": 1,
        }
    )
    leave_type.insert(ignore_permissions=True)
    return leave_type.name


def create_leave_application(
    employee,
    leave_date,
    *,
    half_day=False,
):
    leave_type = ensure_leave_type()

    existing = frappe.db.exists(
        "Leave Application",
        {
            "employee": employee,
            "from_date": leave_date,
            "to_date": leave_date,
            "docstatus": ["<", 2],
        },
    )

    if existing:
        leave = frappe.get_doc("Leave Application", existing)

        if _has_field("Leave Application", "description"):
            frappe.db.set_value(
                "Leave Application",
                existing,
                "description",
                f"{MARKER} leave test record",
                update_modified=False,
            )

        if leave.docstatus == 0:
            _ensure_field_value(leave, "status", "Approved")
            _submit_if_draft(leave)

        return leave.name

    values = {
        "doctype": "Leave Application",
        "employee": employee,
        "company": _get_company(),
        "leave_type": leave_type,
        "from_date": leave_date,
        "to_date": leave_date,
        "status": "Approved",
    }

    if half_day:
        values.update(
            {
                "half_day": 1,
                "half_day_date": leave_date,
                "total_leave_days": 0.5,
            }
        )

    leave = frappe.get_doc(values)
    _ensure_field_value(
        leave,
        "description",
        f"{MARKER} leave test record",
    )

    leave.insert(ignore_permissions=True)
    _submit_if_draft(leave)

    return leave.name

# ---------------------------------------------------------------------------
# Core attendance scenarios
# ---------------------------------------------------------------------------


def seed_present(employee, shift):
    attendance_date = BASE_DATE
    in_time = add_to_date(attendance_date, hours=9)
    out_time = add_to_date(attendance_date, hours=18)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_mispunch(employee, shift):
    attendance_date = add_days(BASE_DATE, 1)
    in_time = add_to_date(attendance_date, hours=9)

    create_checkin(employee, in_time, "IN")

    return create_attendance(
        employee,
        attendance_date,
        status="Mispunch",
        in_time=in_time,
        shift=shift,
    )


def seed_no_punch(employee, shift):
    attendance_date = add_days(BASE_DATE, 2)

    return create_attendance(
        employee,
        attendance_date,
        status="No punch",
        shift=shift,
    )


def seed_overnight(employee, shift):
    attendance_date = add_days(BASE_DATE, 3)
    in_time = add_to_date(attendance_date, hours=20)
    out_time = add_to_date(attendance_date, days=1, hours=5)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_twelve_hour(employee, shift):
    attendance_date = add_days(BASE_DATE, 4)
    in_time = add_to_date(attendance_date, hours=8)
    out_time = add_to_date(attendance_date, hours=20)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_half_day(employee, shift):
    attendance_date = add_days(BASE_DATE, 5)
    in_time = add_to_date(attendance_date, hours=9)
    out_time = add_to_date(attendance_date, hours=13)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        attendance_date,
        status="Half Day",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_weekly_off(employee, shift):
    """Seed a Sunday weekly-off attendance with actual punches."""
    attendance_date = WEEKLY_OFF_DATE
    in_time = add_to_date(attendance_date, hours=9)
    out_time = add_to_date(attendance_date, hours=13)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        attendance_date,
        status="Weekly Off",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_leave(employee):
    leave_date = add_days(BASE_DATE, 7)
    return create_leave_application(employee, leave_date, half_day=False)


def seed_half_day_leave(employee):
    leave_date = add_days(BASE_DATE, 8)
    return create_leave_application(employee, leave_date, half_day=True)


def seed_wfh(employee):
    request_date = add_days(BASE_DATE, 9)
    return create_attendance_request(
        employee,
        request_date,
        "Work From Home",
        f"{MARKER} WFH test request",
    )


def seed_od_half_day(employee):
    return create_attendance_request(
        employee,
        OD_HALF_DAY_DATE,
        "On Duty",
        f"{MARKER} OD half-day test request",
        half_day=True,
    )


def seed_holiday(employee, shift):
    in_time = add_to_date(HOLIDAY_DATE, hours=9)
    out_time = add_to_date(HOLIDAY_DATE, hours=13)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        HOLIDAY_DATE,
        status="Holiday",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_double_shift(employee, shift):
    """Seed two punch pairs on one day to represent a double shift."""
    first_in = add_to_date(DOUBLE_SHIFT_DATE, hours=9)
    first_out = add_to_date(DOUBLE_SHIFT_DATE, hours=13)
    second_in = add_to_date(DOUBLE_SHIFT_DATE, hours=14)
    second_out = add_to_date(DOUBLE_SHIFT_DATE, hours=21)

    create_checkin(employee, first_in, "IN")
    create_checkin(employee, first_out, "OUT")
    create_checkin(employee, second_in, "IN")
    create_checkin(employee, second_out, "OUT")

    return create_attendance(
        employee,
        DOUBLE_SHIFT_DATE,
        status="Present",
        in_time=first_in,
        out_time=second_out,
        shift=shift,
    )


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------


def run():
    """
    Create/reuse Attendance test data.

    The function is safely re-runnable. Seeder employees are identified by a
    stable employee number, and all generated records use deterministic dates,
    timestamps, shift names and request explanations so the same run reuses
    existing records instead of creating duplicates.
    """
    frappe.set_user("Administrator")

    employees = create_employees()
    holiday_list = create_holiday_list()
    assign_holiday_list_to_employees(employees, holiday_list)

    ensure_leave_type()
    shifts = create_shift_types(holiday_list)
    create_shift_assignments(employees, shifts)

    # Employee 01 - Present
    seed_present(employees[0], shifts["day"])

    # Employee 02 - Mispunch
    seed_mispunch(employees[1], shifts["day"])

    # Employee 03 - No Punch
    seed_no_punch(employees[2], shifts["day"])

    # Employee 04 - Overnight
    seed_overnight(employees[3], shifts["overnight"])

    # Employee 05 - 12 Hour
    seed_twelve_hour(employees[4], shifts["twelve_hour"])

    # Employee 06 - Weekly Off with punches
    seed_weekly_off(employees[5], shifts["day"])

    # Employee 07 - Half Day
    seed_half_day(employees[6], shifts["day"])

    # Employee 08 - Leave
    seed_leave(employees[7])

    # Additional scenarios
    seed_half_day_leave(employees[0])
    seed_wfh(employees[1])
    seed_od_half_day(employees[2])
    seed_holiday(employees[3], shifts["day"])
    seed_double_shift(employees[7], shifts["double"])

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: SEED COMPLETE")
    print("==============================================")
    print(f"Employees:        {len(employees)}")
    print(f"Shift Types:      {len(shifts)}")
    print("Shift Assignments: submitted/created/reused")
    print("Attendance:       submitted/core scenarios")
    print("Leave:            submitted/full + half day")
    print("Attendance Req:   submitted/WFH + OD half-day")
    print("Holiday:          created/assigned/tested")
    print("Double Shift:     two punch pairs")
    print("==============================================")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup():
    """
    Remove only records belonging to this attendance seeder.

    Employees are identified by the stable VALENCE_ATTENDANCE_SEED employee
    number. Dependent records are restricted to the deterministic dates and
    values created by this seeder; unrelated records for the same employee are
    therefore left untouched.
    """
    frappe.set_user("Administrator")
    deleted = 0

    employee_filters = {"employee_name": ["in", EMPLOYEE_NAMES]}
    if _has_field("Employee", "employee_number"):
        employee_filters = [
            ["employee_number", "in", list(EMPLOYEE_NUMBERS.values())],
            ["employee_name", "in", EMPLOYEE_NAMES],
            ["name", "is", "set"],
        ]

    employee_names = frappe.get_all(
        "Employee",
        filters=employee_filters,
        pluck="name",
    )

    # -------------------------------------------------------------------
    # Deterministic attendance records
    # -------------------------------------------------------------------
    attendance_dates = {
        BASE_DATE,
        add_days(BASE_DATE, 1),
        add_days(BASE_DATE, 2),
        add_days(BASE_DATE, 3),
        add_days(BASE_DATE, 4),
        add_days(BASE_DATE, 5),
        WEEKLY_OFF_DATE,
        HOLIDAY_DATE,
        DOUBLE_SHIFT_DATE,
    }

    for employee in employee_names:
        attendance_filters = {
            "employee": employee,
            "attendance_date": ["in", list(attendance_dates)],
        }
        if _has_field("Attendance", "remarks"):
            attendance_filters["remarks"] = ["like", f"{MARKER}%"]

        attendance_names = frappe.get_all(
            "Attendance",
            filters=attendance_filters,
            pluck="name",
        )
        for name in attendance_names:
            if _delete_if_exists("Attendance", name):
                deleted += 1

        # Checkins are identified by the seeder marker when the field exists.
        checkin_filters = {
            "employee": employee,
        }
        if _has_field("Employee Checkin", "device_id"):
            checkin_filters["device_id"] = MARKER

        checkin_names = frappe.get_all(
            "Employee Checkin",
            filters=checkin_filters,
            pluck="name",
        )

        for name in checkin_names:
            if _delete_if_exists("Employee Checkin", name):
                deleted += 1

        # Attendance Requests: only the two deterministic seeder requests.
        request_names = frappe.get_all(
            "Attendance Request",
            filters={
                "employee": employee,
                "explanation": ["like", f"{MARKER}%"],
            },
            pluck="name",
        )
        for name in request_names:
            if _delete_if_exists("Attendance Request", name):
                deleted += 1

        # Leave Applications: only the two deterministic seeder dates.
        leave_dates = [add_days(BASE_DATE, 7), add_days(BASE_DATE, 8)]
        leave_filters = {
            "employee": employee,
            "from_date": ["in", leave_dates],
            "to_date": ["in", leave_dates],
        }
        if _has_field("Leave Application", "description"):
            leave_filters["description"] = ["like", f"{MARKER}%"]

        leave_names = frappe.get_all(
            "Leave Application",
            filters=leave_filters,
            pluck="name",
        )
        for name in leave_names:
            if _delete_if_exists("Leave Application", name):
                deleted += 1

        # Shift Assignments: only assignments to our named shift types and
        # deterministic start date.
        assignment_filters = {
            "employee": employee,
            "shift_type": ["in", list(SHIFT_NAMES.values())],
            "start_date": BASE_DATE,
        }


        assignment_names = frappe.get_all(
            "Shift Assignment",
            filters=assignment_filters,
            pluck="name",
        )
        for name in assignment_names:
            if _delete_if_exists("Shift Assignment", name):
                deleted += 1

    # -------------------------------------------------------------------
    # Seeder Shift Types
    # -------------------------------------------------------------------
    for shift_name in SHIFT_NAMES.values():
        if _delete_if_exists("Shift Type", shift_name):
            deleted += 1

    # -------------------------------------------------------------------
    # Seeder Holiday List
    # -------------------------------------------------------------------
    holiday_list_name = f"{MARKER} Holiday List"
    if frappe.db.exists("Holiday List", holiday_list_name):
        if _delete_if_exists("Holiday List", holiday_list_name):
            deleted += 1

    # -------------------------------------------------------------------
    # Seeder Employees
    # -------------------------------------------------------------------
    for employee in employee_names:
        if _delete_if_exists("Employee", employee):
            deleted += 1

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: CLEANUP COMPLETE")
    print("==============================================")
    print(f"Deleted records: {deleted}")
    print("==============================================")
