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
    "Valence Attendance Test 01",
    "Valence Attendance Test 02",
    "Valence Attendance Test 03",
    "Valence Attendance Test 04",
    "Valence Attendance Test 05",
    "Valence Attendance Test 06",
    "Valence Attendance Test 07",
    "Valence Attendance Test 08",
]

SHIFT_NAMES = {
    "day": f"{MARKER} Day Shift",
    "overnight": f"{MARKER} Overnight Shift",
    "twelve_hour": f"{MARKER} 12 Hour Shift",
}

BASE_DATE = add_days(getdate(), 2)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _get_company():
    company = frappe.db.get_single_value(
        "Global Defaults",
        "default_company",
    )

    if not company:
        company = frappe.db.get_value(
            "Company",
            {},
            "name",
        )

    if not company:
        frappe.throw("No Company found.")

    return company


def _get_department():
    return frappe.db.get_value(
        "Department",
        {},
        "name",
    )


def _get_designation():
    return frappe.db.get_value(
        "Designation",
        {},
        "name",
    )


def _get_branch():
    return frappe.db.get_value(
        "Branch",
        {},
        "name",
    )


def _employee_name(index):
    return f"{MARKER} Employee {index:02d}"


def _get_employee(index):
    return frappe.db.get_value(
        "Employee",
        {
            "employee_name": _employee_name(index),
        },
        "name",
    )


def _delete_if_exists(doctype, name):
    if name and frappe.db.exists(doctype, name):
        frappe.delete_doc(
            doctype,
            name,
            force=True,
            ignore_permissions=True,
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

        existing = _get_employee(index)

        if existing:
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


def _get_or_create_shift(key, start_time, end_time):
    shift_name = SHIFT_NAMES[key]

    existing = frappe.db.exists(
        "Shift Type",
        shift_name,
    )

    if existing:
        return existing

    shift = frappe.get_doc(
        {
            "doctype": "Shift Type",
            "name": shift_name,
            "start_time": start_time,
            "end_time": end_time,
        }
    )

    shift.insert(ignore_permissions=True)

    return shift.name


def create_shift_types():
    return {
        "day": _get_or_create_shift(
            "day",
            "09:00:00",
            "18:00:00",
        ),
        "overnight": _get_or_create_shift(
            "overnight",
            "20:00:00",
            "05:00:00",
        ),
        "twelve_hour": _get_or_create_shift(
            "twelve_hour",
            "08:00:00",
            "20:00:00",
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
        return existing

    values = {
        "doctype": "Shift Assignment",
        "employee": employee,
        "shift_type": shift_type,
        "start_date": start_date,
        "status": "Active",
    }

    assignment = frappe.get_doc(values)

    if off_day:
        assignment.custom_off_day = off_day

    assignment.insert(ignore_permissions=True)

    return assignment.name


def create_shift_assignments(employees, shifts):
    assignments = []

    # Employee 01 - normal day shift
    assignments.append(
        create_shift_assignment(
            employees[0],
            shifts["day"],
            BASE_DATE,
        )
    )

    # Employee 02 - normal day shift
    assignments.append(
        create_shift_assignment(
            employees[1],
            shifts["day"],
            BASE_DATE,
        )
    )

    # Employee 03 - normal day shift
    assignments.append(
        create_shift_assignment(
            employees[2],
            shifts["day"],
            BASE_DATE,
        )
    )

    # Employee 04 - overnight
    assignments.append(
        create_shift_assignment(
            employees[3],
            shifts["overnight"],
            BASE_DATE,
        )
    )

    # Employee 05 - 12 hour
    assignments.append(
        create_shift_assignment(
            employees[4],
            shifts["twelve_hour"],
            BASE_DATE,
        )
    )

    # Employee 06 - weekly off Sunday
    assignments.append(
        create_shift_assignment(
            employees[5],
            shifts["day"],
            BASE_DATE,
            off_day="Sunday",
        )
    )

    # Employee 07 - day shift
    assignments.append(
        create_shift_assignment(
            employees[6],
            shifts["day"],
            BASE_DATE,
        )
    )

    # Employee 08 - day shift
    assignments.append(
        create_shift_assignment(
            employees[7],
            shifts["day"],
            BASE_DATE,
        )
    )

    return assignments


# ---------------------------------------------------------------------------
# Employee Checkin
# ---------------------------------------------------------------------------


def create_checkin(
    employee,
    timestamp,
    log_type,
):
    existing = frappe.db.exists(
        "Employee Checkin",
        {
            "employee": employee,
            "time": timestamp,
            "log_type": log_type,
        },
    )

    if existing:
        return existing

    checkin = frappe.get_doc(
        {
            "doctype": "Employee Checkin",
            "employee": employee,
            "time": timestamp,
            "log_type": log_type,
        }
    )

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
        return existing

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

    attendance.insert(
        ignore_permissions=True,
    )

    return attendance.name


# ---------------------------------------------------------------------------
# Attendance Request
# ---------------------------------------------------------------------------


def create_attendance_request(
    employee,
    request_date,
    reason,
    explanation,
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
        return existing

    request = frappe.get_doc(
        {
            "doctype": "Attendance Request",
            "employee": employee,
            "reason": reason,
            "explanation": explanation,
            "from_date": request_date,
            "to_date": request_date,
        }
    )

    request.insert(
        ignore_permissions=True,
    )

    return request.name


# ---------------------------------------------------------------------------
# Leave Application
# ---------------------------------------------------------------------------


def create_leave_application(
    employee,
    leave_date,
    *,
    half_day=False,
):
    leave_type = (
        frappe.db.get_value(
            "Leave Type",
            {},
            "name",
        )
        or "Leave Without Pay"
    )

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
        return existing

    values = {
        "doctype": "Leave Application",
        "employee": employee,
        "leave_type": leave_type,
        "from_date": leave_date,
        "to_date": leave_date,
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

    leave.insert(
        ignore_permissions=True,
    )

    return leave.name


# ---------------------------------------------------------------------------
# Core attendance scenarios
# ---------------------------------------------------------------------------


def seed_present(
    employee,
    shift,
):
    attendance_date = BASE_DATE

    in_time = add_to_date(
        attendance_date,
        hours=9,
    )

    out_time = add_to_date(
        attendance_date,
        hours=18,
    )

    create_checkin(
        employee,
        in_time,
        "IN",
    )

    create_checkin(
        employee,
        out_time,
        "OUT",
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_mispunch(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        1,
    )

    in_time = add_to_date(
        attendance_date,
        hours=9,
    )

    create_checkin(
        employee,
        in_time,
        "IN",
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Mispunch",
        in_time=in_time,
        shift=shift,
    )


def seed_no_punch(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        2,
    )

    return create_attendance(
        employee,
        attendance_date,
        status="No punch",
        shift=shift,
    )


def seed_overnight(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        3,
    )

    in_time = add_to_date(
        attendance_date,
        hours=20,
    )

    out_time = add_to_date(
        attendance_date,
        days=1,
        hours=5,
    )

    create_checkin(
        employee,
        in_time,
        "IN",
    )

    create_checkin(
        employee,
        out_time,
        "OUT",
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_twelve_hour(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        4,
    )

    in_time = add_to_date(
        attendance_date,
        hours=8,
    )

    out_time = add_to_date(
        attendance_date,
        hours=20,
    )

    create_checkin(
        employee,
        in_time,
        "IN",
    )

    create_checkin(
        employee,
        out_time,
        "OUT",
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Present",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_half_day(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        5,
    )

    in_time = add_to_date(
        attendance_date,
        hours=9,
    )

    out_time = add_to_date(
        attendance_date,
        hours=13,
    )

    create_checkin(
        employee,
        in_time,
        "IN",
    )

    create_checkin(
        employee,
        out_time,
        "OUT",
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Half Day",
        in_time=in_time,
        out_time=out_time,
        shift=shift,
    )


def seed_weekly_off(
    employee,
    shift,
):
    attendance_date = add_days(
        BASE_DATE,
        6,
    )

    return create_attendance(
        employee,
        attendance_date,
        status="Weekly Off",
        shift=shift,
    )


def seed_leave(
    employee,
):
    leave_date = add_days(
        BASE_DATE,
        7,
    )

    return create_leave_application(
        employee,
        leave_date,
        half_day=False,
    )


def seed_half_day_leave(
    employee,
):
    leave_date = add_days(
        BASE_DATE,
        8,
    )

    return create_leave_application(
        employee,
        leave_date,
        half_day=True,
    )


def seed_wfh(
    employee,
):
    request_date = add_days(
        BASE_DATE,
        9,
    )

    return create_attendance_request(
        employee,
        request_date,
        "Work From Home",
        f"{MARKER} WFH test request",
    )


def seed_od(
    employee,
):
    request_date = add_days(
        BASE_DATE,
        10,
    )

    return create_attendance_request(
        employee,
        request_date,
        "On Duty",
        f"{MARKER} OD test request",
    )


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------


def run():
    """
    Create/reuse Attendance test data.

    The function is designed to be safely re-runnable:
    existing employees, shifts, assignments, checkins, attendance,
    leave applications and attendance requests are reused.
    """

    frappe.set_user("Administrator")

    employees = create_employees()
    shifts = create_shift_types()

    create_shift_assignments(
        employees,
        shifts,
    )

    # ---------------------------------------------------------------
    # Employee 01 - Present
    # ---------------------------------------------------------------

    seed_present(
        employees[0],
        shifts["day"],
    )

    # ---------------------------------------------------------------
    # Employee 02 - Mispunch
    # ---------------------------------------------------------------

    seed_mispunch(
        employees[1],
        shifts["day"],
    )

    # ---------------------------------------------------------------
    # Employee 03 - No Punch
    # ---------------------------------------------------------------

    seed_no_punch(
        employees[2],
        shifts["day"],
    )

    # ---------------------------------------------------------------
    # Employee 04 - Overnight
    # ---------------------------------------------------------------

    seed_overnight(
        employees[3],
        shifts["overnight"],
    )

    # ---------------------------------------------------------------
    # Employee 05 - 12 Hour
    # ---------------------------------------------------------------

    seed_twelve_hour(
        employees[4],
        shifts["twelve_hour"],
    )

    # ---------------------------------------------------------------
    # Employee 06 - Weekly Off
    # ---------------------------------------------------------------

    seed_weekly_off(
        employees[5],
        shifts["day"],
    )

    # ---------------------------------------------------------------
    # Employee 07 - Half Day
    # ---------------------------------------------------------------

    seed_half_day(
        employees[6],
        shifts["day"],
    )

    # ---------------------------------------------------------------
    # Employee 08 - Leave
    # ---------------------------------------------------------------

    seed_leave(
        employees[7],
    )

    # ---------------------------------------------------------------
    # Additional leave / request scenarios
    # ---------------------------------------------------------------

    seed_half_day_leave(
        employees[0],
    )

    seed_wfh(
        employees[1],
    )

    seed_od(
        employees[2],
    )

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: SEED COMPLETE")
    print("==============================================")
    print(f"Employees:        {len(employees)}")
    print(f"Shift Types:      {len(shifts)}")
    print("Shift Assignments: created/reused")
    print("Attendance:       core scenarios created/reused")
    print("Leave:            full + half day")
    print("Attendance Req:   WFH + OD")
    print("==============================================")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup():
    """
    Remove only records associated with the uniquely named seed employees
    and uniquely named seed shifts.

    This intentionally does not delete records belonging to normal employees.
    """

    deleted = 0

    employee_names = frappe.get_all(
        "Employee",
        filters={
            "employee_name": [
                "in",
                EMPLOYEE_NAMES,
            ],
        },
        pluck="name",
    )

    # ---------------------------------------------------------------
    # Child / dependent records first
    # ---------------------------------------------------------------

    for employee in employee_names:

        # Attendance
        attendance_names = frappe.get_all(
            "Attendance",
            filters={
                "employee": employee,
            },
            pluck="name",
        )

        for name in attendance_names:
            _delete_if_exists(
                "Attendance",
                name,
            )
            deleted += 1

        # Employee Checkins
        checkin_names = frappe.get_all(
            "Employee Checkin",
            filters={
                "employee": employee,
            },
            pluck="name",
        )

        for name in checkin_names:
            _delete_if_exists(
                "Employee Checkin",
                name,
            )
            deleted += 1

        # Attendance Requests
        request_names = frappe.get_all(
            "Attendance Request",
            filters={
                "employee": employee,
                "explanation": [
                    "like",
                    f"{MARKER}%",
                ],
            },
            pluck="name",
        )

        for name in request_names:
            _delete_if_exists(
                "Attendance Request",
                name,
            )
            deleted += 1

        # Leave Applications
        leave_names = frappe.get_all(
            "Leave Application",
            filters={
                "employee": employee,
            },
            pluck="name",
        )

        for name in leave_names:
            _delete_if_exists(
                "Leave Application",
                name,
            )
            deleted += 1

        # Shift Assignments
        assignment_names = frappe.get_all(
            "Shift Assignment",
            filters={
                "employee": employee,
            },
            pluck="name",
        )

        for name in assignment_names:
            _delete_if_exists(
                "Shift Assignment",
                name,
            )
            deleted += 1

    # ---------------------------------------------------------------
    # Seed Shift Types
    # ---------------------------------------------------------------

    for shift_name in SHIFT_NAMES.values():
        if frappe.db.exists(
            "Shift Type",
            shift_name,
        ):
            _delete_if_exists(
                "Shift Type",
                shift_name,
            )
            deleted += 1

    # ---------------------------------------------------------------
    # Seed Employees
    # ---------------------------------------------------------------

    for employee in employee_names:
        _delete_if_exists(
            "Employee",
            employee,
        )
        deleted += 1

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: CLEANUP COMPLETE")
    print("==============================================")
    print(f"Deleted records: {deleted}")
    print("==============================================")