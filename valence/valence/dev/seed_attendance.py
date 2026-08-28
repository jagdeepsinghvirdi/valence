"""
Valence Attendance Test Data Seeder

Usage from a Frappe bench:

    bench --site valence.localhost execute valence.dev.seed_attendance.run
    bench --site valence.localhost execute valence.dev.seed_attendance.verify
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

# Stable base date — does NOT change between runs.
# 2026-09-01 is a Tuesday; WEEKLY_OFF_DATE resolves to 2026-09-06 (Sunday).
BASE_DATE = getdate("2026-09-01")

WEEKLY_OFF_DATE = getdate("2026-09-06")   # First Sunday on/after BASE_DATE
HALF_DAY_DATE = add_days(BASE_DATE, 6)    # 2026-09-07 (Monday - working day)
HOLIDAY_DATE = add_days(BASE_DATE, 11)   # 2026-09-12
DOUBLE_SHIFT_DATE = add_days(BASE_DATE, 12)  # 2026-09-13
OD_HALF_DAY_DATE = add_days(BASE_DATE, 13)   # 2026-09-14


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

    # Delete any linked ToDo records referencing this document
    for todo in frappe.get_all(
        "ToDo",
        filters={"reference_type": doctype, "reference_name": name},
        pluck="name",
    ):
        frappe.delete_doc("ToDo", todo, force=True, ignore_permissions=True)

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


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------


def _get_active_workflow(doctype):
    """Return the active Frappe Workflow document for the given doctype, or None."""
    workflow_name = frappe.db.get_value(
        "Workflow",
        {"document_type": doctype, "is_active": 1},
        "name",
    )
    if not workflow_name:
        return None
    return frappe.get_doc("Workflow", workflow_name)


def _apply_workflow_action(doc, action):
    """
    Apply a named workflow action to *doc* using the real Frappe workflow engine.

    Uses ``frappe.model.workflow.apply_workflow`` which honours permission
    checks, conditions, and transitions defined in the Workflow doctype.
    Ignores ``allow_self_approval`` and role restrictions by running as
    Administrator so that the seeder can always push records to Approved.
    """
    try:
        from frappe.model.workflow import apply_workflow
        apply_workflow(doc, action)
    except Exception as exc:
        frappe.log_error(
            title=f"{MARKER} workflow error",
            message=f"{MARKER}: apply_workflow({doc.doctype}, {action!r}) failed: {exc}",
        )
        raise


def _approve_doc_via_workflow(doc, doctype):
    """
    Drive *doc* through the installed approval workflow (Draft -> Apply -> Approve)
    so that the record reaches docstatus=1 / Approved state without bypassing
    the real workflow engine.

    Falls back to a direct submit when no workflow is active for the doctype.
    """
    workflow = _get_active_workflow(doctype)

    if not workflow:
        # No workflow — ensure status is Approved if field exists, then submit directly.
        _ensure_field_value(doc, "status", "Approved")
        _submit_if_draft(doc)
        return

    state_field = workflow.workflow_state_field or "workflow_state"
    current_state = doc.get(state_field) or "Draft"

    # Walk: Draft -> Pending HOD Approval (action: "Apply")
    if current_state == "Draft":
        _apply_workflow_action(doc, "Apply")
        doc.reload()
        current_state = doc.get(state_field) or ""

    # Walk: Pending HOD Approval -> Approved (action: "Approve")
    if "Pending" in current_state:
        _apply_workflow_action(doc, "Approve")
        doc.reload()
        current_state = doc.get(state_field) or ""

    # If still in an intermediate Pending state (e.g., Pending Super HOD Approval),
    # apply Approve one more time.
    if "Pending" in current_state:
        _apply_workflow_action(doc, "Approve")
        doc.reload()


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

    # Also ensure the weekly-off Sunday is marked as weekly off.
    existing_weekly_off = next(
        (
            row
            for row in holiday_list.get("holidays", [])
            if str(row.holiday_date) == str(WEEKLY_OFF_DATE) and row.weekly_off
        ),
        None,
    )
    if not existing_weekly_off:
        holiday_list.append(
            "holidays",
            {
                "holiday_date": WEEKLY_OFF_DATE,
                "description": f"{MARKER} Weekly Off (Sunday)",
                "weekly_off": 1,
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
            "date_of_birth": add_days(BASE_DATE, -25 * 365),
            "date_of_joining": add_days(BASE_DATE, -30),
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


def _is_seeder_shift_assignment(doc_or_name):
    if isinstance(doc_or_name, str):
        fields = ["name", "shift_type"]
        if _has_field("Shift Assignment", "description"):
            fields.append("description")
        data = frappe.db.get_value("Shift Assignment", doc_or_name, fields, as_dict=True)
        if not data:
            return False
        if data.shift_type in SHIFT_NAMES.values():
            return True
        if data.get("description") and str(data.description).startswith(MARKER):
            return True
        return False
    else:
        if doc_or_name.shift_type in SHIFT_NAMES.values():
            return True
        if doc_or_name.get("description") and str(doc_or_name.description).startswith(MARKER):
            return True
        return False


def create_shift_assignment(
    employee,
    shift_type,
    start_date,
    *,
    off_day=None,
):
    existing_exact = frappe.db.exists(
        "Shift Assignment",
        {
            "employee": employee,
            "shift_type": shift_type,
            "start_date": start_date,
            "docstatus": ["<", 2],
        },
    )

    if existing_exact:
        assignment = frappe.get_doc("Shift Assignment", existing_exact)
        if _has_field("Shift Assignment", "description") and assignment.description != MARKER:
            frappe.db.set_value(
                "Shift Assignment", existing_exact, "description", MARKER, update_modified=False
            )
        if off_day and _has_field("Shift Assignment", "custom_off_day"):
            if assignment.get("custom_off_day") != off_day:
                frappe.db.set_value(
                    "Shift Assignment", existing_exact, "custom_off_day", off_day, update_modified=False
                )
        if assignment.docstatus == 0:
            _submit_if_draft(assignment)
        return assignment.name

    # Check for any existing active/draft shift assignments for this employee
    existing_assignments = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "docstatus": ["<", 2],
        },
        fields=["name", "shift_type", "start_date", "docstatus"],
    )

    for sa in existing_assignments:
        if _is_seeder_shift_assignment(sa.name):
            # Prior seeder-generated assignment with a different date or shift;
            # cancel and delete it so the new target assignment can be created without overlap
            _delete_if_exists("Shift Assignment", sa.name)
        else:
            # Unrelated user/system assignment. Do NOT delete or modify.
            frappe.log_error(
                title=f"{MARKER} Unrelated Shift Assignment",
                message=f"Employee {employee} has unrelated Shift Assignment {sa.name} ({sa.shift_type}) on {sa.start_date}.",
            )

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
    half_day=False,
    half_day_date=None,
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
        if status and attendance.status != status:
            frappe.db.set_value("Attendance", existing, "status", status, update_modified=False)
        if in_time and str(attendance.in_time) != str(in_time):
            frappe.db.set_value("Attendance", existing, "in_time", in_time, update_modified=False)
        if out_time and str(attendance.out_time) != str(out_time):
            frappe.db.set_value("Attendance", existing, "out_time", out_time, update_modified=False)
        if shift and attendance.shift != shift:
            frappe.db.set_value("Attendance", existing, "shift", shift, update_modified=False)
        if half_day:
            if _has_field("Attendance", "half_day") and not attendance.get("half_day"):
                frappe.db.set_value("Attendance", existing, "half_day", 1, update_modified=False)
            if _has_field("Attendance", "half_day_date") and not attendance.get("half_day_date"):
                frappe.db.set_value("Attendance", existing, "half_day_date", half_day_date or attendance_date, update_modified=False)
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

    if half_day:
        if _has_field("Attendance", "half_day"):
            values["half_day"] = 1
        if _has_field("Attendance", "half_day_date"):
            values["half_day_date"] = half_day_date or attendance_date

    attendance = frappe.get_doc(values)
    _ensure_field_value(attendance, "remarks", f"{MARKER} attendance test record")
    attendance.insert(ignore_permissions=True)
    _submit_if_draft(attendance)

    # If status was overridden during validate hook (e.g. by set_status doc_event),
    # ensure the explicit requested test status is preserved.
    if status and frappe.db.get_value("Attendance", attendance.name, "status") != status:
        frappe.db.set_value("Attendance", attendance.name, "status", status, update_modified=False)

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
            _approve_doc_via_workflow(request, "Attendance Request")
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
    _approve_doc_via_workflow(request, "Attendance Request")

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
            _approve_doc_via_workflow(leave, "Leave Application")

        return leave.name

    values = {
        "doctype": "Leave Application",
        "employee": employee,
        "company": _get_company(),
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
    _ensure_field_value(
        leave,
        "description",
        f"{MARKER} leave test record",
    )

    leave.insert(ignore_permissions=True)
    _approve_doc_via_workflow(leave, "Leave Application")

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
    """
    Seed a Half Day attendance record.

    The employee works 4 hours (09:00 to 13:00) on a normal working day (HALF_DAY_DATE),
    which falls below the full-day shift duration and within the half-day threshold.
    """
    attendance_date = HALF_DAY_DATE
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
        half_day=True,
        half_day_date=attendance_date,
    )


def seed_weekly_off(employee, shift):
    """
    Seed a Weekly Off attendance record with actual punches.

    The employee works on their Sunday weekly-off day. Punches are recorded so
    the scenario demonstrates a worked-on-weekly-off situation rather than a
    plain absence.
    """
    in_time = add_to_date(WEEKLY_OFF_DATE, hours=9)
    out_time = add_to_date(WEEKLY_OFF_DATE, hours=13)

    create_checkin(employee, in_time, "IN")
    create_checkin(employee, out_time, "OUT")

    return create_attendance(
        employee,
        WEEKLY_OFF_DATE,
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
    """
    Seed a Holiday attendance record with actual punches.

    The employee works on a public holiday. Punches are recorded to demonstrate
    a worked-on-holiday scenario.
    """
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
    """
    Seed a double-shift day: two complete IN/OUT punch pairs on the same date.

    The Double Shift type spans 09:00–21:00 (12 hours). Two punch pairs are
    recorded — first session 09:00–13:00 and second session 14:00–21:00 — to
    demonstrate paired-punch double-shift processing. The Attendance record
    spans first_in -> second_out so the full working hours are captured.
    """
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

    # Employee 06 - Weekly Off with punches (Sunday 2026-09-06)
    seed_weekly_off(employees[5], shifts["day"])

    # Employee 07 - Half Day (punches + half_day=1 flag)
    seed_half_day(employees[6], shifts["day"])

    # Employee 08 - Leave (full day, via workflow)
    seed_leave(employees[7])

    # Additional scenarios
    seed_half_day_leave(employees[0])           # half-day leave via workflow
    seed_wfh(employees[1])                      # WFH attendance request via workflow
    seed_od_half_day(employees[2])              # OD half-day attendance request via workflow
    seed_holiday(employees[3], shifts["day"])   # Holiday with punches
    seed_double_shift(employees[7], shifts["double"])  # Double shift two punch pairs

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: SEED COMPLETE")
    print("==============================================")
    print(f"Employees:         {len(employees)}")
    print(f"Shift Types:       {len(shifts)}")
    print("Shift Assignments:  submitted/created/reused")
    print("Attendance:         submitted/core scenarios")
    print("Leave:              submitted via workflow (full + half day)")
    print("Attendance Req:     submitted via workflow (WFH + OD half-day)")
    print("Holiday:            created/assigned/tested with punches")
    print("Weekly Off:         Sunday with punches")
    print("Double Shift:       two punch pairs (09:00-13:00 + 14:00-21:00)")
    print("==============================================")


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify():
    """
    Validate all important seeded scenarios and report results.

    Checks for:
      - Employees (8)
      - Shift Types (4)
      - Shift Assignments (8, submitted with expected shift types)
      - Holiday List with test holiday and weekly-off entries
      - Attendance records per scenario
      - Half Day flags on Attendance
      - Double Shift punch pairs
      - Weekly Off with punches
      - Holiday with punches
      - Leave Applications (submitted/approved, full + half day)
      - Attendance Requests (submitted/approved, WFH + OD half-day)
      - Employee Checkins with MARKER device_id

    Prints a human-readable report to stdout.
    """
    frappe.set_user("Administrator")

    ok_count = 0
    fail_count = 0

    def _ok(label):
        nonlocal ok_count
        ok_count += 1
        print(f"  [OK]   {label}")

    def _fail(label):
        nonlocal fail_count
        fail_count += 1
        print(f"  [FAIL] {label}")

    def _check(condition, label):
        if condition:
            _ok(label)
        else:
            _fail(label)

    print("")
    print("==============================================")
    print(f"{MARKER}: VERIFY")
    print("==============================================")
    print(f"BASE_DATE        : {BASE_DATE}")
    print(f"WEEKLY_OFF_DATE  : {WEEKLY_OFF_DATE}")
    print(f"HALF_DAY_DATE    : {HALF_DAY_DATE}")
    print(f"HOLIDAY_DATE     : {HOLIDAY_DATE}")
    print(f"DOUBLE_SHIFT_DATE: {DOUBLE_SHIFT_DATE}")
    print(f"OD_HALF_DAY_DATE : {OD_HALF_DAY_DATE}")
    print("")

    emp1 = _get_employee(1)
    emp2 = _get_employee(2)
    emp3 = _get_employee(3)
    emp4 = _get_employee(4)
    emp5 = _get_employee(5)
    emp6 = _get_employee(6)
    emp7 = _get_employee(7)
    emp8 = _get_employee(8)

    all_emps = [emp1, emp2, emp3, emp4, emp5, emp6, emp7, emp8]
    existing_emp_ids = [e for e in all_emps if e]

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    print("--- Employees ---")
    for index, emp in enumerate(all_emps, start=1):
        _check(bool(emp), f"Employee {index:02d} ({_employee_name(index)})")

    # ------------------------------------------------------------------
    # Shift Types
    # ------------------------------------------------------------------
    print("--- Shift Types ---")
    for key, name in SHIFT_NAMES.items():
        exists = frappe.db.exists("Shift Type", name)
        _check(bool(exists), f"Shift Type '{name}'")

    # ------------------------------------------------------------------
    # Shift Assignments
    # ------------------------------------------------------------------
    print("--- Shift Assignments ---")
    expected_shifts = [
        (emp1, SHIFT_NAMES["day"], "Emp01 Day Shift"),
        (emp2, SHIFT_NAMES["day"], "Emp02 Day Shift"),
        (emp3, SHIFT_NAMES["day"], "Emp03 Day Shift"),
        (emp4, SHIFT_NAMES["overnight"], "Emp04 Overnight Shift"),
        (emp5, SHIFT_NAMES["twelve_hour"], "Emp05 12-Hour Shift"),
        (emp6, SHIFT_NAMES["day"], "Emp06 Day Shift (Sunday Off)"),
        (emp7, SHIFT_NAMES["day"], "Emp07 Day Shift"),
        (emp8, SHIFT_NAMES["double"], "Emp08 Double Shift"),
    ]
    for emp, shift_name, label in expected_shifts:
        if not emp:
            _fail(f"Shift Assignment for {label} — employee not found")
            continue
        assignment = frappe.db.get_value(
            "Shift Assignment",
            {
                "employee": emp,
                "shift_type": shift_name,
                "start_date": BASE_DATE,
                "docstatus": 1,
            },
            "name",
        )
        _check(bool(assignment), f"Shift Assignment for {label} (submitted)")

    # ------------------------------------------------------------------
    # Holiday List
    # ------------------------------------------------------------------
    print("--- Holiday List ---")
    hl_name = f"{MARKER} Holiday List"
    hl_exists = frappe.db.exists("Holiday List", hl_name)
    _check(bool(hl_exists), f"Holiday List '{hl_name}'")

    if hl_exists:
        hl = frappe.get_doc("Holiday List", hl_name)
        holiday_dates = [str(r.holiday_date) for r in hl.get("holidays", [])]
        _check(
            str(HOLIDAY_DATE) in holiday_dates,
            f"Holiday entry on {HOLIDAY_DATE}",
        )
        weekly_off_entries = [
            r for r in hl.get("holidays", [])
            if str(r.holiday_date) == str(WEEKLY_OFF_DATE) and r.weekly_off
        ]
        _check(bool(weekly_off_entries), f"Weekly Off entry on {WEEKLY_OFF_DATE}")

    # ------------------------------------------------------------------
    # Attendance records
    # ------------------------------------------------------------------
    print("--- Attendance ---")

    def _check_attendance(employee, date, expected_status, label, extra_checks=None):
        if not employee:
            _fail(f"{label} — employee not found")
            return

        fields = ["name", "status", "docstatus"]
        if _has_field("Attendance", "in_time"):
            fields.append("in_time")
        if _has_field("Attendance", "out_time"):
            fields.append("out_time")
        if _has_field("Attendance", "working_hours"):
            fields.append("working_hours")
        if _has_field("Attendance", "half_day"):
            fields.append("half_day")

        att = frappe.db.get_value(
            "Attendance",
            {"employee": employee, "attendance_date": date, "docstatus": ["!=", 2]},
            fields,
            as_dict=True,
        )
        if not att:
            _fail(f"{label} — no Attendance record on {date}")
            return

        status_ok = att.status == expected_status
        _check(status_ok, f"{label} — status={att.status!r} (expected {expected_status!r})")
        _check(att.docstatus == 1, f"{label} — docstatus=1 (submitted)")

        if extra_checks:
            extra_checks(att)

    _check_attendance(emp1, BASE_DATE, "Present", "Emp01 Present")
    _check_attendance(emp2, add_days(BASE_DATE, 1), "Mispunch", "Emp02 Mispunch")
    _check_attendance(emp3, add_days(BASE_DATE, 2), "No punch", "Emp03 No Punch")
    _check_attendance(emp4, add_days(BASE_DATE, 3), "Present", "Emp04 Overnight")
    _check_attendance(emp5, add_days(BASE_DATE, 4), "Present", "Emp05 12-Hour")

    # Weekly Off with punches
    def _check_weekly_off_punches(att):
        has_in = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp6, "time": add_to_date(WEEKLY_OFF_DATE, hours=9), "log_type": "IN"},
            "name",
        ))
        has_out = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp6, "time": add_to_date(WEEKLY_OFF_DATE, hours=13), "log_type": "OUT"},
            "name",
        ))
        _check(has_in, "Emp06 Weekly Off — IN checkin exists")
        _check(has_out, "Emp06 Weekly Off — OUT checkin exists")

    _check_attendance(emp6, WEEKLY_OFF_DATE, "Weekly Off", "Emp06 Weekly Off", _check_weekly_off_punches)

    # Half Day — verified via status + punches + schema-aware half_day flag
    def _check_half_day_details(att):
        has_in = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp7, "time": add_to_date(HALF_DAY_DATE, hours=9), "log_type": "IN"},
            "name",
        ))
        has_out = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp7, "time": add_to_date(HALF_DAY_DATE, hours=13), "log_type": "OUT"},
            "name",
        ))
        _check(has_in, "Emp07 Half Day — IN checkin (09:00) exists")
        _check(has_out, "Emp07 Half Day — OUT checkin (13:00) exists")

        if _has_field("Attendance", "half_day"):
            _check(att.get("half_day") == 1, f"Emp07 Half Day — half_day flag=1 (got {att.get('half_day')})")

    _check_attendance(emp7, HALF_DAY_DATE, "Half Day", "Emp07 Half Day", _check_half_day_details)

    # Holiday with punches
    def _check_holiday_punches(att):
        has_in = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp4, "time": add_to_date(HOLIDAY_DATE, hours=9), "log_type": "IN"},
            "name",
        ))
        has_out = bool(frappe.db.get_value(
            "Employee Checkin",
            {"employee": emp4, "time": add_to_date(HOLIDAY_DATE, hours=13), "log_type": "OUT"},
            "name",
        ))
        _check(has_in, "Emp04 Holiday — IN checkin exists")
        _check(has_out, "Emp04 Holiday — OUT checkin exists")

    _check_attendance(emp4, HOLIDAY_DATE, "Holiday", "Emp04 Holiday with punches", _check_holiday_punches)

    # Double Shift — two punch pairs
    def _check_double_shift_punches(att):
        punches = frappe.get_all(
            "Employee Checkin",
            filters={"employee": emp8, "time": ["between", [
                add_to_date(DOUBLE_SHIFT_DATE, hours=8),
                add_to_date(DOUBLE_SHIFT_DATE, hours=22),
            ]]},
            fields=["name", "log_type", "time"],
        )
        in_count = sum(1 for p in punches if p.log_type == "IN")
        out_count = sum(1 for p in punches if p.log_type == "OUT")
        _check(in_count >= 2, f"Emp08 Double Shift — >=2 IN punches (got {in_count})")
        _check(out_count >= 2, f"Emp08 Double Shift — >=2 OUT punches (got {out_count})")

    _check_attendance(emp8, DOUBLE_SHIFT_DATE, "Present", "Emp08 Double Shift", _check_double_shift_punches)

    # ------------------------------------------------------------------
    # Leave Applications
    # ------------------------------------------------------------------
    print("--- Leave Applications ---")
    leave_full_date = add_days(BASE_DATE, 7)
    leave_half_date = add_days(BASE_DATE, 8)

    if emp8:
        leave_full = frappe.db.get_value(
            "Leave Application",
            {"employee": emp8, "from_date": leave_full_date, "docstatus": ["!=", 2]},
            ["name", "docstatus", "status"],
            as_dict=True,
        )
        _check(bool(leave_full), f"Emp08 Leave Application on {leave_full_date}")
        if leave_full:
            _check(leave_full.docstatus == 1, "Emp08 Leave Application — submitted (docstatus=1)")
            _check(
                leave_full.status == "Approved",
                f"Emp08 Leave Application — status='Approved' (got {leave_full.status!r})",
            )
    else:
        _fail(f"Emp08 Leave Application on {leave_full_date} — employee not found")

    if emp1:
        fields = ["name", "docstatus", "status"]
        if _has_field("Leave Application", "half_day"):
            fields.append("half_day")
        leave_half = frappe.db.get_value(
            "Leave Application",
            {"employee": emp1, "from_date": leave_half_date, "docstatus": ["!=", 2]},
            fields,
            as_dict=True,
        )
        _check(bool(leave_half), f"Emp01 Half-Day Leave Application on {leave_half_date}")
        if leave_half:
            _check(leave_half.docstatus == 1, "Emp01 Half-Day Leave — submitted (docstatus=1)")
            _check(
                leave_half.status == "Approved",
                f"Emp01 Half-Day Leave — status='Approved' (got {leave_half.status!r})",
            )
            if _has_field("Leave Application", "half_day"):
                _check(leave_half.get("half_day") == 1, "Emp01 Half-Day Leave — half_day=1")
    else:
        _fail(f"Emp01 Half-Day Leave Application on {leave_half_date} — employee not found")

    # ------------------------------------------------------------------
    # Attendance Requests
    # ------------------------------------------------------------------
    print("--- Attendance Requests ---")
    wfh_date = add_days(BASE_DATE, 9)

    if emp2:
        wfh_req = frappe.db.get_value(
            "Attendance Request",
            {"employee": emp2, "reason": "Work From Home", "from_date": wfh_date},
            ["name", "docstatus"],
            as_dict=True,
        )
        _check(bool(wfh_req), f"Emp02 WFH Request on {wfh_date}")
        if wfh_req:
            _check(wfh_req.docstatus == 1, "Emp02 WFH Request — submitted (docstatus=1)")
    else:
        _fail(f"Emp02 WFH Request on {wfh_date} — employee not found")

    if emp3:
        fields = ["name", "docstatus"]
        if _has_field("Attendance Request", "half_day"):
            fields.append("half_day")
        od_req = frappe.db.get_value(
            "Attendance Request",
            {"employee": emp3, "reason": "On Duty", "from_date": OD_HALF_DAY_DATE},
            fields,
            as_dict=True,
        )
        _check(bool(od_req), f"Emp03 OD half-day Request on {OD_HALF_DAY_DATE}")
        if od_req:
            _check(od_req.docstatus == 1, "Emp03 OD Request — submitted (docstatus=1)")
            if _has_field("Attendance Request", "half_day"):
                _check(od_req.get("half_day") == 1, "Emp03 OD Request — half_day=1")
    else:
        _fail(f"Emp03 OD half-day Request on {OD_HALF_DAY_DATE} — employee not found")

    # ------------------------------------------------------------------
    # Employee Checkins with MARKER device_id
    # ------------------------------------------------------------------
    print("--- Employee Checkins (MARKER scope) ---")
    if _has_field("Employee Checkin", "device_id") and existing_emp_ids:
        total_checkins = frappe.db.count(
            "Employee Checkin",
            filters={
                "employee": ["in", existing_emp_ids],
                "device_id": MARKER,
            },
        )
        _check(total_checkins > 0, f"Checkins with device_id={MARKER!r}: {total_checkins}")
    else:
        print("  [SKIP] device_id field absent or employees not found — checkin scoping unavailable")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = ok_count + fail_count
    print("")
    print("==============================================")
    print(f"VERIFY SUMMARY: {ok_count}/{total} checks passed")
    if fail_count:
        print(f"  *** {fail_count} check(s) FAILED — see [FAIL] lines above ***")
    else:
        print("  All checks passed.")
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

    Also removes Attendance records auto-created by Leave Applications and
    Attendance Requests submitted by this seeder.
    """
    frappe.set_user("Administrator")
    deleted = 0

    if _has_field("Employee", "employee_number"):
        employee_names = frappe.get_all(
            "Employee",
            filters={"employee_number": ["in", list(EMPLOYEE_NUMBERS.values())]},
            pluck="name",
        )
        legacy_names = frappe.get_all(
            "Employee",
            filters={"employee_name": ["in", EMPLOYEE_NAMES]},
            pluck="name",
        )
        employee_names = list(set(employee_names + legacy_names))
    else:
        employee_names = frappe.get_all(
            "Employee",
            filters={"employee_name": ["in", EMPLOYEE_NAMES]},
            pluck="name",
        )

    # -------------------------------------------------------------------
    # Deterministic attendance records (directly seeded)
    # -------------------------------------------------------------------
    attendance_dates = {
        BASE_DATE,
        add_days(BASE_DATE, 1),
        add_days(BASE_DATE, 2),
        add_days(BASE_DATE, 3),
        add_days(BASE_DATE, 4),
        add_days(BASE_DATE, 5),
        WEEKLY_OFF_DATE,
        HALF_DAY_DATE,
        HOLIDAY_DATE,
        DOUBLE_SHIFT_DATE,
    }

    # Attendance records auto-created by Leave Applications / Attendance Requests.
    # These are also scoped strictly to seeder employees and seeder-created dates.
    leave_and_request_dates = {
        add_days(BASE_DATE, 7),   # seed_leave
        add_days(BASE_DATE, 8),   # seed_half_day_leave
        add_days(BASE_DATE, 9),   # seed_wfh
        OD_HALF_DAY_DATE,         # seed_od_half_day
    }

    all_attendance_dates = attendance_dates | leave_and_request_dates

    for employee in employee_names:
        # Use date-only scope (employee + date) so both directly-seeded Attendance
        # records AND Attendance auto-created by Leave Applications / Attendance
        # Requests are captured. The narrow employee+date filter keeps cleanup
        # strictly scoped to seeder-created data.
        attendance_filters = {
            "employee": employee,
            "attendance_date": ["in", list(all_attendance_dates)],
        }

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

        # Shift Assignments: only assignments to our named seeder shift types.
        assignment_filters = {
            "employee": employee,
            "shift_type": ["in", list(SHIFT_NAMES.values())],
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
    # ------------------------------------------------------------------
    for employee in employee_names:
        if _delete_if_exists("Employee", employee):
            deleted += 1

    # -------------------------------------------------------------------
    # Dangling ToDos referencing deleted seeder documents
    # -------------------------------------------------------------------
    for doctype in ("Leave Application", "Attendance Request"):
        for todo in frappe.get_all("ToDo", filters={"reference_type": doctype}, fields=["name", "reference_name"]):
            if not frappe.db.exists(doctype, todo.reference_name):
                frappe.delete_doc("ToDo", todo.name, force=True, ignore_permissions=True)
                deleted += 1

    frappe.db.commit()

    print("")
    print("==============================================")
    print(f"{MARKER}: CLEANUP COMPLETE")
    print("==============================================")
    print(f"Deleted records: {deleted}")
    print("==============================================")
