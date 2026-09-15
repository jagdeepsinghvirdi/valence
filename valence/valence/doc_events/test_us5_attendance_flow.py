from __future__ import annotations

from datetime import datetime, timedelta
import frappe
from frappe.utils import add_days, getdate, nowdate, flt

from valence.api import (
    get_day_type,
    get_day_type_map,
    get_employee_checkin_entries,
    get_employee_checkin_entries_multiple,
    get_holiday_list_for_employee_safe,
    get_shift_weekly_off_days,
    _is_overnight_shift,
    _get_shift_punch_window,
)
from valence.valence.attendance_code import get_attendance_code
from valence.valence.doc_events.attendance import (
    _apply_hours_status,
    get_double_shift_factor,
    get_shift_duration_hours,
    get_shift_midpoint,
    get_worked_half,
    set_status,
)
from valence.valence.override.whitelisted_method.roster import get_weekly_offs


class _StubAttendance:
    def __init__(self, **kwargs):
        self.name = kwargs.get("name", "ATT-TEST-001")
        self.employee = kwargs.get("employee", "EMP-TEST-001")
        self.attendance_date = kwargs.get("attendance_date", "2026-09-08")
        self.in_time = kwargs.get("in_time")
        self.out_time = kwargs.get("out_time")
        self.status = kwargs.get("status")
        self.working_hours = kwargs.get("working_hours", 0)
        self.shift = kwargs.get("shift")
        self.leave_application = kwargs.get("leave_application")
        self.leave_type = kwargs.get("leave_type")
        self.attendance_request = kwargs.get("attendance_request")
        self.docstatus = kwargs.get("docstatus", 1)
        self.values = {}

    def db_set(self, field, value):
        self.values[field] = value
        setattr(self, field, value)

    def reload(self):
        pass

    def as_dict(self):
        return {
            "name": self.name,
            "employee": self.employee,
            "attendance_date": self.attendance_date,
            "in_time": self.in_time,
            "out_time": self.out_time,
            "status": self.status,
            "working_hours": self.working_hours,
            "shift": self.shift,
            "leave_application": self.leave_application,
            "leave_type": self.leave_type,
            "attendance_request": self.attendance_request,
            "docstatus": self.docstatus,
        }


def run():
    frappe.flags.in_test = True
    results = []

    def ok(name, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        results.append((status, name, detail))
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))

    frappe.set_user("Administrator")

    print("")
    print("=" * 76)
    print("USER STORY 5 - INTEGRATION & DATA FLOW SUITE (ADARSH SCOPE)")
    print("=" * 76)

    # ------------------------------------------------------------------------
    # 1. Blank Shift Status Behavior & Absent Thresholds
    # ------------------------------------------------------------------------
    print("\n-- 1. Blank Shift Status & Thresholds " + "-" * 40)
    stub_blank = _StubAttendance(shift=None)
    _apply_hours_status(stub_blank, 7.5, None)
    ok(
        "Blank shift with positive hours sets status to Present",
        stub_blank.values.get("status") == "Present",
        f"got {stub_blank.values.get('status')}",
    )
    ok(
        "Blank shift with positive hours sets working_hours",
        stub_blank.values.get("working_hours") == 7.5,
        f"got {stub_blank.values.get('working_hours')}",
    )

    stub_blank_zero = _StubAttendance(shift=None)
    _apply_hours_status(stub_blank_zero, 0, None)
    ok(
        "Blank shift with zero hours sets status to Absent",
        stub_blank_zero.values.get("status") == "Absent",
        f"got {stub_blank_zero.values.get('status')}",
    )

    shift_name = "US5-Test-Day-Shift"
    if not frappe.db.exists("Shift Type", shift_name):
        st = frappe.new_doc("Shift Type")
        st.name = shift_name
        st.start_time = "09:00:00"
        st.end_time = "17:00:00"
        st.working_hours_threshold_for_half_day = 4.0
        st.working_hours_threshold_for_absent = 1.0
        st.flags.ignore_permissions = True
        st.flags.ignore_validate = True
        st.flags.ignore_mandatory = True
        st.insert()
    else:
        frappe.db.set_value(
            "Shift Type",
            shift_name,
            {
                "working_hours_threshold_for_half_day": 4.0,
                "working_hours_threshold_for_absent": 1.0,
            },
        )

    # Positive hours below non-zero absent threshold -> Absent
    stub_below_absent = _StubAttendance(shift=shift_name)
    _apply_hours_status(stub_below_absent, 0.5, shift_name)
    ok(
        "Positive hours (0.5h) below absent threshold (1.0h) marks Absent",
        stub_below_absent.values.get("status") == "Absent",
        f"got {stub_below_absent.values.get('status')}",
    )

    # ------------------------------------------------------------------------
    # 2. Legitimate Double-Shift Working Hours & 2P / 2P/A
    # ------------------------------------------------------------------------
    print("\n-- 2. Double Shift Working Hours " + "-" * 45)
    test_date = "2026-09-02"
    next_date = "2026-09-03"
    stub_double = _StubAttendance(
        shift=shift_name,
        attendance_date=test_date,
        in_time=f"{test_date} 09:00:00",
        out_time=f"{next_date} 01:00:00",  # 16 hours
    )
    set_status(stub_double, "validate")
    ok(
        "Double shift (16h on 8h shift) working_hours is not capped to 8h",
        stub_double.values.get("working_hours") == 16.0,
        f"got {stub_double.values.get('working_hours')}",
    )
    factor_double = get_double_shift_factor(shift_name, stub_double.values.get("working_hours"))
    ok(
        "Double shift factor is 2.0",
        factor_double == 2.0,
        f"got {factor_double}",
    )
    code_double = get_attendance_code(
        stub_double.as_dict(),
        {"double_factor": factor_double, "day_type": None},
    )
    ok(
        "Double shift generates code 2P on normal day",
        code_double == "2P",
        f"got {code_double}",
    )

    stub_double_half = _StubAttendance(
        shift=shift_name,
        attendance_date=test_date,
        in_time=f"{test_date} 09:00:00",
        out_time=f"{test_date} 21:00:00",  # 12 hours
    )
    set_status(stub_double_half, "validate")
    factor_half = get_double_shift_factor(shift_name, stub_double_half.values.get("working_hours"))
    ok(
        "Double shift 1.5x (12h on 8h shift) factor is 1.5",
        factor_half == 1.5,
        f"got {factor_half}",
    )
    code_half = get_attendance_code(
        stub_double_half.as_dict(),
        {"double_factor": factor_half, "day_type": None},
    )
    ok(
        "Double shift 1.5x generates code 2P/A on normal day",
        code_half == "2P/A",
        f"got {code_half}",
    )

    stub_single = _StubAttendance(
        shift=shift_name,
        attendance_date=test_date,
        in_time=f"{test_date} 09:00:00",
        out_time=f"{test_date} 17:00:00",  # 8 hours
    )
    set_status(stub_single, "validate")
    factor_single = get_double_shift_factor(shift_name, stub_single.values.get("working_hours"))
    ok(
        "Normal single shift (8h) factor is 1.0",
        factor_single == 1.0,
        f"got {factor_single}",
    )
    code_single = get_attendance_code(
        stub_single.as_dict(),
        {"double_factor": factor_single, "day_type": None},
    )
    ok(
        "Normal single shift generates code P",
        code_single == "P",
        f"got {code_single}",
    )

    # ------------------------------------------------------------------------
    # 3. Overnight Shift Duration, Midpoint & Window Calculation
    # ------------------------------------------------------------------------
    print("\n-- 3. Overnight Shift Duration, Midpoint & Window " + "-" * 26)
    overnight_name = "US5-Test-Overnight-Shift"
    if not frappe.db.exists("Shift Type", overnight_name):
        st_over = frappe.new_doc("Shift Type")
        st_over.name = overnight_name
        st_over.start_time = "22:00:00"
        st_over.end_time = "06:00:00"
        st_over.begin_check_in_before_shift_start_time = 60
        st_over.allow_check_out_after_shift_end_time = 120
        st_over.flags.ignore_permissions = True
        st_over.flags.ignore_validate = True
        st_over.flags.ignore_mandatory = True
        st_over.insert()
    else:
        frappe.db.set_value(
            "Shift Type",
            overnight_name,
            {
                "start_time": "22:00:00",
                "end_time": "06:00:00",
                "begin_check_in_before_shift_start_time": 60,
                "allow_check_out_after_shift_end_time": 120,
            },
        )

    ok(
        "Day shift is not detected as overnight",
        not _is_overnight_shift(shift_name),
    )
    ok(
        "Night shift 22:00-06:00 is detected as overnight",
        _is_overnight_shift(overnight_name),
    )

    # Duration & Midpoint calculations on overnight shift
    over_duration = get_shift_duration_hours(overnight_name)
    ok(
        "Overnight shift duration is 8.0 hours",
        over_duration == 8.0,
        f"got {over_duration}",
    )
    over_midpoint = get_shift_midpoint(overnight_name)
    # 22:00 + 4 hours = 26:00 (02:00 AM next day)
    ok(
        "Overnight shift midpoint is 26 hours (02:00 AM wrapped)",
        over_midpoint == timedelta(hours=26),
        f"got {over_midpoint}",
    )
    half_first = get_worked_half(overnight_name, "2026-09-12 22:00:00", "2026-09-13 02:00:00")
    ok(
        "Overnight worked 22:00-02:00 detected as First Half",
        half_first == "First Half",
        f"got {half_first}",
    )
    half_second = get_worked_half(overnight_name, "2026-09-13 02:00:00", "2026-09-13 06:00:00")
    ok(
        "Overnight worked 02:00-06:00 detected as Second Half",
        half_second == "Second Half",
        f"got {half_second}",
    )
    half_both = get_worked_half(overnight_name, "2026-09-12 22:00:00", "2026-09-13 06:00:00")
    ok(
        "Overnight worked full 22:00-06:00 detected as Both",
        half_both == "Both",
        f"got {half_both}",
    )

    # 3B. Multiple Overnight Shift Timings (Generic Midpoint & Worked Half)
    # Test 1: 18:00 to 02:00 (midpoint 22:00, before midnight)
    over_early = "US5-Test-Overnight-18-02"
    if not frappe.db.exists("Shift Type", over_early):
        frappe.get_doc({
            "doctype": "Shift Type",
            "name": over_early,
            "start_time": "18:00:00",
            "end_time": "02:00:00",
            "begin_check_in_before_shift_start_time": 60,
            "allow_check_out_after_shift_end_time": 60,
        }).insert(ignore_permissions=True)
    ok("Night shift 18:00-02:00 detected as overnight", _is_overnight_shift(over_early))
    ok("18:00-02:00 duration is 8.0h", get_shift_duration_hours(over_early) == 8.0)
    ok("18:00-02:00 midpoint is 22:00 (before midnight)", get_shift_midpoint(over_early) == timedelta(hours=22))
    ok(
        "18:00-02:00 worked 18:00-22:00 detected as First Half",
        get_worked_half(over_early, "2026-09-12 18:00:00", "2026-09-12 22:00:00") == "First Half",
    )
    ok(
        "18:00-02:00 worked 22:00-02:00 detected as Second Half",
        get_worked_half(over_early, "2026-09-12 22:00:00", "2026-09-13 02:00:00") == "Second Half",
    )
    ok(
        "18:00-02:00 worked 23:00-02:00 detected as Second Half",
        get_worked_half(over_early, "2026-09-12 23:00:00", "2026-09-13 02:00:00") == "Second Half",
    )
    ok(
        "18:00-02:00 worked 18:00-02:00 detected as Both",
        get_worked_half(over_early, "2026-09-12 18:00:00", "2026-09-13 02:00:00") == "Both",
    )

    # Test 2: 20:00 to 04:00 (midpoint 24:00, exactly at midnight)
    over_mid = "US5-Test-Overnight-20-04"
    if not frappe.db.exists("Shift Type", over_mid):
        frappe.get_doc({
            "doctype": "Shift Type",
            "name": over_mid,
            "start_time": "20:00:00",
            "end_time": "04:00:00",
            "begin_check_in_before_shift_start_time": 60,
            "allow_check_out_after_shift_end_time": 60,
        }).insert(ignore_permissions=True)
    ok("Night shift 20:00-04:00 detected as overnight", _is_overnight_shift(over_mid))
    ok("20:00-04:00 midpoint is 24:00 (midnight)", get_shift_midpoint(over_mid) == timedelta(hours=24))
    ok(
        "20:00-04:00 worked 20:00-24:00 detected as First Half",
        get_worked_half(over_mid, "2026-09-12 20:00:00", "2026-09-13 00:00:00") == "First Half",
    )
    ok(
        "20:00-04:00 worked 00:00-04:00 detected as Second Half",
        get_worked_half(over_mid, "2026-09-13 00:00:00", "2026-09-13 04:00:00") == "Second Half",
    )
    ok(
        "20:00-04:00 worked 20:00-04:00 detected as Both",
        get_worked_half(over_mid, "2026-09-12 20:00:00", "2026-09-13 04:00:00") == "Both",
    )

    # Test 3: 19:00 to 07:00 (12-hour shift, midpoint 25:00, 01:00 AM)
    over_12h = "US5-Test-Overnight-19-07"
    if not frappe.db.exists("Shift Type", over_12h):
        frappe.get_doc({
            "doctype": "Shift Type",
            "name": over_12h,
            "start_time": "19:00:00",
            "end_time": "07:00:00",
            "begin_check_in_before_shift_start_time": 60,
            "allow_check_out_after_shift_end_time": 60,
        }).insert(ignore_permissions=True)
    ok("12h night shift 19:00-07:00 detected as overnight", _is_overnight_shift(over_12h))
    ok("19:00-07:00 duration is 12.0h", get_shift_duration_hours(over_12h) == 12.0)
    ok("19:00-07:00 midpoint is 25:00 (01:00 AM next day)", get_shift_midpoint(over_12h) == timedelta(hours=25))
    ok(
        "19:00-07:00 worked 19:00-01:00 detected as First Half",
        get_worked_half(over_12h, "2026-09-12 19:00:00", "2026-09-13 01:00:00") == "First Half",
    )
    ok(
        "19:00-07:00 worked 01:00-07:00 detected as Second Half",
        get_worked_half(over_12h, "2026-09-13 01:00:00", "2026-09-13 07:00:00") == "Second Half",
    )
    ok(
        "19:00-07:00 worked 19:00-07:00 detected as Both",
        get_worked_half(over_12h, "2026-09-12 19:00:00", "2026-09-13 07:00:00") == "Both",
    )

    # Shift-aware punch window calculation
    w_start, w_end = _get_shift_punch_window(overnight_name, "2026-09-12")
    # Window start: 2026-09-12 22:00 - 60min = 2026-09-12 21:00:00
    # Window end: 2026-09-13 06:00 + 120min = 2026-09-13 08:00:00
    ok(
        "Overnight window start anchors to shift start minus 60min buffer",
        w_start == datetime(2026, 9, 12, 21, 0, 0),
        f"got {w_start}",
    )
    ok(
        "Overnight window end anchors to shift end plus 120min buffer (08:00 AM, not 12:00 PM)",
        w_end == datetime(2026, 9, 13, 8, 0, 0),
        f"got {w_end}",
    )

    # ------------------------------------------------------------------------
    # 4. Live Check-ins & Fetch Time (Single, Multiple, Overnight & Recalculation)
    # ------------------------------------------------------------------------
    print("\n-- 4. Live Check-in & Fetch Time Flow " + "-" * 37)
    company_name = frappe.db.get_value("Company", {}, "name")
    orig_company_hl = frappe.db.get_value("Company", company_name, "default_holiday_list")

    emp = frappe.new_doc("Employee")
    emp.first_name = "Test"
    emp.last_name = "US5"
    emp.company = company_name
    emp.status = "Active"
    emp.gender = "Female"
    emp.date_of_birth = "1995-01-01"
    emp.date_of_joining = "2026-01-01"
    emp.insert(ignore_permissions=True)
    emp_id = emp.name

    att_date = "2026-09-08"

    leave_type = frappe.db.get_value("Leave Type", {}, "name")
    if not leave_type:
        lt = frappe.new_doc("Leave Type")
        lt.leave_type_name = "US5-Test-Leave"
        lt.insert(ignore_permissions=True)
        leave_type = lt.name

    # Single Fetch Time on On Leave
    att_leave = frappe.new_doc("Attendance")
    att_leave.employee = emp_id
    att_leave.attendance_date = att_date
    att_leave.status = "Present"
    att_leave.insert(ignore_permissions=True)
    att_leave.db_set("status", "On Leave")
    att_leave.db_set("leave_type", leave_type)
    att_leave.reload()

    res_single_leave = get_employee_checkin_entries(emp_id, att_date, att_leave.name)
    ok(
        "Single Fetch Time skips and protects On Leave record",
        "Skipped" in res_single_leave.get("message", ""),
        f"got {res_single_leave}",
    )
    att_leave.reload()
    ok(
        "On Leave status remained unchanged after single Fetch Time",
        att_leave.status == "On Leave",
        f"got {att_leave.status}",
    )

    # Single Fetch Time on Work From Home with no punches
    att_wfh = frappe.new_doc("Attendance")
    att_wfh.employee = emp_id
    att_wfh.attendance_date = "2026-09-09"
    att_wfh.status = "Work From Home"
    att_wfh.insert(ignore_permissions=True)

    res_single_wfh = get_employee_checkin_entries(emp_id, "2026-09-09", att_wfh.name)
    att_wfh.reload()
    ok(
        "Single Fetch Time with no punches preserves Work From Home status",
        att_wfh.status == "Work From Home",
        f"got {att_wfh.status}",
    )

    # Single Fetch Time on On Duty with no punches
    att_od = frappe.new_doc("Attendance")
    att_od.employee = emp_id
    att_od.attendance_date = "2026-09-10"
    att_od.status = "On Duty"
    att_od.insert(ignore_permissions=True)

    res_single_od = get_employee_checkin_entries(emp_id, "2026-09-10", att_od.name)
    att_od.reload()
    ok(
        "Single Fetch Time with no punches preserves On Duty status",
        att_od.status == "On Duty",
        f"got {att_od.status}",
    )

    # Multiple Fetch Time protection on Leave and Request
    res_multi_leave = get_employee_checkin_entries_multiple(emp_id, att_date, att_leave.name)
    ok(
        "Multiple Fetch Time skips On Leave record",
        "Skipped" in res_multi_leave.get("message", ""),
        f"got {res_multi_leave}",
    )

    res_multi_wfh = get_employee_checkin_entries_multiple(emp_id, "2026-09-09", att_wfh.name)
    ok(
        "Multiple Fetch Time skips approved WFH record when no punches",
        "Skipped" in res_multi_wfh.get("message", ""),
        f"got {res_multi_wfh}",
    )

    res_multi_od = get_employee_checkin_entries_multiple(emp_id, "2026-09-10", att_od.name)
    ok(
        "Multiple Fetch Time skips approved On Duty record when no punches",
        "Skipped" in res_multi_od.get("message", ""),
        f"got {res_multi_od}",
    )

    # Normal working day with no punches -> Absent
    att_norm = frappe.new_doc("Attendance")
    att_norm.employee = emp_id
    att_norm.attendance_date = "2026-09-11"
    att_norm.status = "No punch"
    att_norm.insert(ignore_permissions=True)

    res_multi_norm = get_employee_checkin_entries_multiple(emp_id, "2026-09-11", att_norm.name)
    att_norm.reload()
    ok(
        "No punch on normal working day resolves to Absent",
        att_norm.status == "Absent",
        f"got {att_norm.status}",
    )

    # 4A. LIVE PUNCH EXTRACTION & MULTIPLE PUNCHES TEST (Earliest / Latest Selection)
    chk1 = frappe.new_doc("Employee Checkin")
    chk1.employee = emp_id
    chk1.time = "2026-09-05 08:50:00"
    chk1.log_type = "IN"
    chk1.insert(ignore_permissions=True)

    chk2 = frappe.new_doc("Employee Checkin")
    chk2.employee = emp_id
    chk2.time = "2026-09-05 13:00:00"
    chk2.log_type = "OUT"
    chk2.insert(ignore_permissions=True)

    chk3 = frappe.new_doc("Employee Checkin")
    chk3.employee = emp_id
    chk3.time = "2026-09-05 17:10:00"
    chk3.log_type = "OUT"
    chk3.insert(ignore_permissions=True)

    att_punched = frappe.new_doc("Attendance")
    att_punched.employee = emp_id
    att_punched.attendance_date = "2026-09-05"
    att_punched.status = "No punch"
    att_punched.shift = shift_name
    att_punched.insert(ignore_permissions=True)

    get_employee_checkin_entries(emp_id, "2026-09-05", att_punched.name)
    att_punched.reload()

    ok(
        "Fetch Time selects EARLIEST punch as in_time (08:50:00)",
        str(att_punched.in_time) == "2026-09-05 08:50:00",
        f"got {att_punched.in_time}",
    )
    ok(
        "Fetch Time selects LATEST punch as out_time (17:10:00)",
        str(att_punched.out_time) == "2026-09-05 17:10:00",
        f"got {att_punched.out_time}",
    )
    ok(
        "Intermediate punch 13:00:00 is not selected as in_time or out_time",
        att_punched.in_time != "2026-09-05 13:00:00" and att_punched.out_time != "2026-09-05 13:00:00",
    )
    ok(
        "Fetch Time recalculates working_hours end-to-end (8.3h)",
        att_punched.working_hours == 8.3,
        f"got {att_punched.working_hours}",
    )
    ok(
        "Fetch Time recalculates status end-to-end to Present",
        att_punched.status == "Present",
        f"got {att_punched.status}",
    )

    # 4B. LIVE OVERNIGHT PUNCHES WITH UNRELATED NEXT-DAY PUNCH TEST
    chk_over_in = frappe.new_doc("Employee Checkin")
    chk_over_in.employee = emp_id
    chk_over_in.time = "2026-09-12 21:55:00"  # Before midnight
    chk_over_in.log_type = "IN"
    chk_over_in.insert(ignore_permissions=True)

    chk_over_out = frappe.new_doc("Employee Checkin")
    chk_over_out.employee = emp_id
    chk_over_out.time = "2026-09-13 06:15:00"  # Legit overnight checkout
    chk_over_out.log_type = "OUT"
    chk_over_out.insert(ignore_permissions=True)

    chk_over_unrelated = frappe.new_doc("Employee Checkin")
    chk_over_unrelated.employee = emp_id
    chk_over_unrelated.time = "2026-09-13 11:00:00"  # Unrelated punch next day
    chk_over_unrelated.log_type = "IN"
    chk_over_unrelated.insert(ignore_permissions=True)

    att_over_live = frappe.new_doc("Attendance")
    att_over_live.employee = emp_id
    att_over_live.attendance_date = "2026-09-12"
    att_over_live.status = "No punch"
    att_over_live.shift = overnight_name
    att_over_live.insert(ignore_permissions=True)

    get_employee_checkin_entries(emp_id, "2026-09-12", att_over_live.name)
    att_over_live.reload()

    ok(
        "Overnight Fetch Time selects in_time before midnight (21:55:00)",
        str(att_over_live.in_time) == "2026-09-12 21:55:00",
        f"got {att_over_live.in_time}",
    )
    ok(
        "Overnight Fetch Time selects legitimate checkout after midnight (06:15:00)",
        str(att_over_live.out_time) == "2026-09-13 06:15:00",
        f"got {att_over_live.out_time}",
    )
    ok(
        "Overnight Fetch Time EXCLUDES later unrelated next-day punch (11:00:00)",
        str(att_over_live.out_time) != "2026-09-13 11:00:00",
        f"got {att_over_live.out_time}",
    )
    ok(
        "Overnight working_hours correctly bounded (8.3h, not 13h+)",
        att_over_live.working_hours == 8.3,
        f"got {att_over_live.working_hours}",
    )
    ok(
        "Overnight attendance status set to Present",
        att_over_live.status == "Present",
        f"got {att_over_live.status}",
    )

    # Clean up attendance docs & checkins
    for d in (att_leave, att_wfh, att_od, att_norm, att_punched, att_over_live):
        frappe.db.delete("Attendance", {"name": d.name})
    for c in (chk1, chk2, chk3, chk_over_in, chk_over_out, chk_over_unrelated):
        frappe.db.delete("Employee Checkin", {"name": c.name})

    # ------------------------------------------------------------------------
    # 5. Shift Assignment Resolution & Edge Cases
    # ------------------------------------------------------------------------
    print("\n-- 5. Shift Assignment & Off-Day Resolution " + "-" * 33)
    hl_company = "US5-Company-Holiday-List-2026"
    if not frappe.db.exists("Holiday List", hl_company):
        hl1 = frappe.new_doc("Holiday List")
        hl1.holiday_list_name = hl_company
        hl1.from_date = "2026-01-01"
        hl1.to_date = "2026-12-31"
        hl1.append("holidays", {
            "holiday_date": "2026-09-06",  # Sunday
            "description": "Sunday Weekly Off",
            "weekly_off": 1,
        })
        hl1.append("holidays", {
            "holiday_date": "2026-09-15",  # Tuesday
            "description": "Public Holiday",
            "weekly_off": 0,
        })
        hl1.insert(ignore_permissions=True)

    frappe.db.set_value("Company", company_name, "default_holiday_list", hl_company)
    frappe.db.set_value("Employee", emp_id, "holiday_list", None)

    resolved_hl = get_holiday_list_for_employee_safe(emp_id)
    ok(
        "Employee with no holiday list falls back to Company default Holiday List",
        resolved_hl == hl_company,
        f"got {resolved_hl}",
    )

    day_type_sun = get_day_type(emp_id, "2026-09-06")
    ok(
        "Sunday resolves to Weekly Off from Company Holiday List fallback",
        day_type_sun == "Weekly Off",
        f"got {day_type_sun}",
    )

    day_type_pub = get_day_type(emp_id, "2026-09-15")
    ok(
        "Public holiday resolves to Holiday from Company Holiday List fallback",
        day_type_pub == "Holiday",
        f"got {day_type_pub}",
    )

    day_type_work = get_day_type(emp_id, "2026-09-07")
    ok(
        "Normal working day resolves to None",
        day_type_work is None,
        f"got {day_type_work}",
    )

    # Shift Assignment with custom_off_day = "Tuesday"
    sa1 = frappe.new_doc("Shift Assignment")
    sa1.employee = emp_id
    sa1.shift_type = shift_name
    sa1.start_date = "2026-09-01"
    sa1.end_date = "2026-09-30"
    sa1.custom_off_day = "Tuesday"
    sa1.status = "Active"
    sa1.flags.ignore_permissions = True
    sa1.flags.ignore_validate = True
    sa1.flags.ignore_mandatory = True
    sa1.insert()
    sa1.db_set("docstatus", 1)

    day_type_sun_shift = get_day_type(emp_id, "2026-09-06")
    ok(
        "Shift weekly off (Tuesday) overrides Holiday List weekly off (Sunday -> None)",
        day_type_sun_shift is None,
        f"got {day_type_sun_shift}",
    )

    day_type_tue_shift = get_day_type(emp_id, "2026-09-08")
    ok(
        "Shift weekly off day (Tuesday) resolves to Weekly Off",
        day_type_tue_shift == "Weekly Off",
        f"got {day_type_tue_shift}",
    )

    day_type_pub_shift = get_day_type(emp_id, "2026-09-15")
    ok(
        "Public holiday on shift weekly off day remains Holiday",
        day_type_pub_shift == "Holiday",
        f"got {day_type_pub_shift}",
    )

    # Bulk map conflict verification (Shift Assignment weekly off vs Holiday List weekly off)
    map_conflict = get_day_type_map([emp_id], "2026-09-01", "2026-09-15")
    ok(
        "Bulk map: Sunday resolves to None when Shift weekly off is Tuesday (override)",
        map_conflict.get((emp_id, getdate("2026-09-06"))) is None,
        f"got {map_conflict.get((emp_id, getdate('2026-09-06')))}",
    )
    ok(
        "Bulk map: Shift weekly off (Tuesday) resolves to Weekly Off",
        map_conflict.get((emp_id, getdate("2026-09-08"))) == "Weekly Off",
        f"got {map_conflict.get((emp_id, getdate('2026-09-08')))}",
    )
    ok(
        "Bulk map: Public holiday on shift weekly off day resolves to Holiday (public holiday precedence)",
        map_conflict.get((emp_id, getdate("2026-09-15"))) == "Holiday",
        f"got {map_conflict.get((emp_id, getdate('2026-09-15')))}",
    )

    # Newer assignment with BLANK custom_off_day does NOT leak older assignment's off-day
    sa2 = frappe.new_doc("Shift Assignment")
    sa2.employee = emp_id
    sa2.shift_type = shift_name
    sa2.start_date = "2026-09-20"
    sa2.end_date = "2026-09-30"
    sa2.custom_off_day = None  # BLANK
    sa2.status = "Active"
    sa2.flags.ignore_permissions = True
    sa2.flags.ignore_validate = True
    sa2.flags.ignore_mandatory = True
    sa2.insert()
    sa2.db_set("docstatus", 1)

    off_days_sa2 = get_shift_weekly_off_days(emp_id, getdate("2026-09-22"))
    ok(
        "Active Shift Assignment with blank custom_off_day does not inherit older Tuesday off-day",
        off_days_sa2 == set(),
        f"got {off_days_sa2}",
    )

    # Draft assignment ignored
    sa_draft = frappe.new_doc("Shift Assignment")
    sa_draft.employee = emp_id
    sa_draft.shift_type = shift_name
    sa_draft.start_date = "2026-09-25"
    sa_draft.end_date = "2026-09-30"
    sa_draft.custom_off_day = "Friday"
    sa_draft.docstatus = 0
    sa_draft.flags.ignore_permissions = True
    sa_draft.flags.ignore_validate = True
    sa_draft.flags.ignore_mandatory = True
    sa_draft.insert()

    off_days_draft = get_shift_weekly_off_days(emp_id, getdate("2026-09-26"))
    ok(
        "Draft Shift Assignment (docstatus=0) is ignored",
        "friday" not in off_days_draft,
        f"got {off_days_draft}",
    )

    # Cancelled assignment ignored
    sa_canc = frappe.new_doc("Shift Assignment")
    sa_canc.employee = emp_id
    sa_canc.shift_type = shift_name
    sa_canc.start_date = "2026-09-25"
    sa_canc.end_date = "2026-09-30"
    sa_canc.custom_off_day = "Thursday"
    sa_canc.flags.ignore_permissions = True
    sa_canc.flags.ignore_validate = True
    sa_canc.flags.ignore_mandatory = True
    sa_canc.insert()
    sa_canc.db_set("docstatus", 2)

    off_days_canc = get_shift_weekly_off_days(emp_id, getdate("2026-09-26"))
    ok(
        "Cancelled Shift Assignment (docstatus=2) is ignored",
        "thursday" not in off_days_canc,
        f"got {off_days_canc}",
    )

    # Ended assignment ignored
    off_days_ended = get_shift_weekly_off_days(emp_id, getdate("2026-10-05"))
    ok(
        "Ended Shift Assignment is ignored for future dates",
        off_days_ended == set(),
        f"got {off_days_ended}",
    )

    # Overlapping assignments with identical start_date: creation tie-break
    sa_tie1 = frappe.new_doc("Shift Assignment")
    sa_tie1.employee = emp_id
    sa_tie1.shift_type = shift_name
    sa_tie1.start_date = "2026-10-01"
    sa_tie1.end_date = "2026-10-31"
    sa_tie1.custom_off_day = "Monday"
    sa_tie1.status = "Active"
    sa_tie1.flags.ignore_permissions = True
    sa_tie1.flags.ignore_validate = True
    sa_tie1.flags.ignore_mandatory = True
    sa_tie1.insert()
    sa_tie1.db_set("docstatus", 1)
    sa_tie1.db_set("creation", "2026-09-01 10:00:00")

    sa_tie2 = frappe.new_doc("Shift Assignment")
    sa_tie2.employee = emp_id
    sa_tie2.shift_type = shift_name
    sa_tie2.start_date = "2026-10-01"
    sa_tie2.end_date = "2026-10-31"
    sa_tie2.custom_off_day = "Wednesday"
    sa_tie2.status = "Active"
    sa_tie2.flags.ignore_permissions = True
    sa_tie2.flags.ignore_validate = True
    sa_tie2.flags.ignore_mandatory = True
    sa_tie2.insert()
    sa_tie2.db_set("docstatus", 1)
    sa_tie2.db_set("creation", "2026-09-01 12:00:00")  # Later creation

    off_days_tie = get_shift_weekly_off_days(emp_id, getdate("2026-10-02"))
    ok(
        "Overlapping assignments with identical start_date orders by creation desc (Wednesday wins)",
        off_days_tie == {"wednesday"},
        f"got {off_days_tie}",
    )

    # Clean up shift assignments
    for s in (sa1, sa2, sa_draft, sa_canc, sa_tie1, sa_tie2):
        frappe.db.delete("Shift Assignment", {"name": s.name})

    # ------------------------------------------------------------------------
    # 6. get_day_type vs get_day_type_map Full Multi-Day Consistency & Roster
    # ------------------------------------------------------------------------
    print("\n-- 6. get_day_type vs get_day_type_map Consistency " + "-" * 26)

    # Re-setup sa1 for September
    sa1 = frappe.new_doc("Shift Assignment")
    sa1.employee = emp_id
    sa1.shift_type = shift_name
    sa1.start_date = "2026-09-01"
    sa1.end_date = "2026-09-30"
    sa1.custom_off_day = "Tuesday"
    sa1.status = "Active"
    sa1.flags.ignore_permissions = True
    sa1.flags.ignore_validate = True
    sa1.flags.ignore_mandatory = True
    sa1.insert()
    sa1.db_set("docstatus", 1)

    start_sep = "2026-09-01"
    end_sep = "2026-09-30"
    day_type_map_result = get_day_type_map([emp_id], start_sep, end_sep)

    cur_d = getdate(start_sep)
    end_d = getdate(end_sep)
    mismatches = []
    days_checked = 0

    while cur_d <= end_d:
        d_str = str(cur_d)
        single_type = get_day_type(emp_id, d_str)
        map_type = day_type_map_result.get((emp_id, cur_d))
        if single_type != map_type:
            mismatches.append((d_str, single_type, map_type))
        days_checked += 1
        cur_d = add_days(cur_d, 1)

    ok(
        f"get_day_type and get_day_type_map exact equality across all {days_checked} days of September",
        len(mismatches) == 0,
        f"Mismatches: {mismatches}" if mismatches else "100% agreement",
    )

    # Roster consistency check
    roster_offs = get_weekly_offs("2026-09-01", "2026-09-07", {"name": emp_id})
    emp_roster_dates = {o["holiday_date"] for o in roster_offs.get(emp_id, [])}
    ok(
        "Roster detects Tuesday 2026-09-01 as shift weekly off",
        "2026-09-01" in emp_roster_dates,
        f"got {emp_roster_dates}",
    )
    ok(
        "Roster does not mark Sunday 2026-09-06 as weekly off when shift off-day is Tuesday",
        "2026-09-06" not in emp_roster_dates,
        f"got {emp_roster_dates}",
    )

    # Clean up test employee, shift assignments, and restore company default holiday list
    frappe.db.delete("Shift Assignment", {"employee": emp_id})
    frappe.db.delete("Employee", {"name": emp_id})
    frappe.db.set_value("Company", company_name, "default_holiday_list", orig_company_hl)
    frappe.db.delete("Holiday List", {"name": hl_company})
    frappe.db.delete("Shift Type", {"name": ["in", [shift_name, overnight_name, over_early, over_mid, over_12h]]})

    # ------------------------------------------------------------------------
    # 7. Regression Suites
    # ------------------------------------------------------------------------
    print("\n-- 7. Existing Test Regressions " + "-" * 42)
    from valence.valence.doc_events.test_us1_feedback import run as run_us1
    from valence.valence.report.monthly_attendance_dashboard.test_monthly_attendance_dashboard import run as run_dashboard

    us1_fails = run_us1()
    ok(
        "US1 Feedback suite passes without regression",
        us1_fails == 0,
        f"{us1_fails} failures",
    )

    dash_fails = run_dashboard()
    ok(
        "Monthly Attendance Dashboard suite passes without regression",
        dash_fails == 0,
        f"{dash_fails} failures",
    )

    failures = [r for r in results if r[0] == "FAIL"]

    print("")
    print("=" * 76)
    print(
        f"TOTAL {len(results)}    PASSED {len(results) - len(failures)}    FAILED {len(failures)}"
    )
    print("=" * 76)

    if failures:
        print("\nFAILURES:")
        for _, name, detail in failures:
            print(f"  {name}" + (f" - {detail}" if detail else ""))

    return len(failures)
