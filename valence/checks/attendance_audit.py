"""
Attendance Audit Module (Valence)
---------------------------------
This module provides attendance auditing functionality for Frappe / ERPNext.

READ-ONLY GUARANTEE:
--------------------
This audit tool is strictly read-only and will never alter database state or document records.

Allowed Operations:
- frappe.db.get_all(...)
- frappe.db.get_list(...)
- frappe.db.get_value(...)
- frappe.db.exists(...)
- frappe.db.sql(...) -- SELECT statements ONLY
- frappe.get_doc(...) -- for inspection / reading attributes ONLY

Strictly Forbidden Operations:
- doc.insert(), doc.save(), doc.submit(), doc.cancel(), doc.delete()
- frappe.db.set_value(), frappe.db.set_single_value(), frappe.db.sql(...) (UPDATE/INSERT/DELETE/DROP)
- frappe.db.commit(), frappe.db.rollback()
"""

from typing import Any, Dict, List, Optional, Tuple
import frappe
from frappe.utils import add_days, flt, getdate, nowdate


def execute(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute attendance audit checks across Categories 1 to 6.

    :param from_date: Start date string (YYYY-MM-DD)
    :param to_date: End date string (YYYY-MM-DD)
    :param limit: Maximum record limit for query processing
    :return: Dictionary containing audit results under 'category_1' through 'category_6'
    """
    # Build date filters for tabAttendance query
    filters: Dict[str, Any] = {}
    if from_date and to_date:
        filters["attendance_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["attendance_date"] = [">=", from_date]
    elif to_date:
        filters["attendance_date"] = ["<=", to_date]

    # Fetch attendance records using frappe.db.get_all (READ-ONLY)
    attendances: List[Dict[str, Any]] = frappe.db.get_all(
        "Attendance",
        filters=filters,
        fields=[
            "name",
            "employee",
            "employee_name",
            "attendance_date",
            "status",
            "in_time",
            "out_time",
            "working_hours",
            "shift",
            "attendance_request",
            "leave_type",
            "leave_application",
            "custom_short_leave_count",
            "company",
            "docstatus",
        ],
        limit_page_length=limit if limit else 0,
        order_by="attendance_date desc",
    )

    # Pre-fetch Shift Types for threshold lookups (READ-ONLY)
    shift_types: Dict[str, Dict[str, Any]] = {}
    shift_records = frappe.db.get_all(
        "Shift Type",
        fields=[
            "name",
            "working_hours_threshold_for_half_day",
            "working_hours_threshold_for_absent",
        ],
    )
    for st in shift_records:
        shift_types[st["name"]] = st

    # Caches for Employee Holiday Lists, Holiday entries, and Shift Assignment lookups
    employee_holiday_lists: Dict[str, Optional[str]] = {}
    holiday_cache: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    shift_assignment_exists_cache: Dict[Tuple[str, str], bool] = {}

    def get_employee_holiday_list(emp_id: str, company: Optional[str] = None) -> Optional[str]:
        if emp_id not in employee_holiday_lists:
            h_list = frappe.db.get_value("Employee", emp_id, "holiday_list")
            if not h_list and company:
                h_list = frappe.db.get_value("Company", company, "default_holiday_list")
            employee_holiday_lists[emp_id] = h_list
        return employee_holiday_lists[emp_id]

    def get_holiday_record(h_list: str, att_date: Any) -> Optional[Dict[str, Any]]:
        key = (h_list, str(att_date))
        if key not in holiday_cache:
            res = frappe.db.sql(
                """
                SELECT weekly_off
                FROM `tabHoliday`
                WHERE parent = %s
                  AND holiday_date = %s
                LIMIT 1
                """,
                (h_list, att_date),
                as_dict=True,
            )
            holiday_cache[key] = res[0] if res else None
        return holiday_cache[key]

    def is_shift_weekly_off(emp_id: str, att_date: Any) -> bool:
        date_obj = getdate(att_date)
        weekday = date_obj.strftime("%A").strip().lower()

        assignments = frappe.db.sql(
            """
            SELECT custom_off_day
            FROM `tabShift Assignment`
            WHERE employee = %s
              AND start_date <= %s
              AND (end_date >= %s OR end_date IS NULL OR end_date = '')
              AND docstatus = 1
            ORDER BY start_date DESC
            """,
            (emp_id, att_date, att_date),
            as_dict=True,
        )
        for row in assignments:
            raw = (row.get("custom_off_day") or "").strip().lower()
            if raw:
                off_days = {d.strip() for d in raw.split(",") if d.strip()}
                if weekday in off_days:
                    return True
        return False

    def has_active_shift_assignment(emp_id: str, att_date: Any) -> bool:
        key = (emp_id, str(att_date))
        if key not in shift_assignment_exists_cache:
            exists = bool(
                frappe.db.sql(
                    """
                    SELECT name FROM `tabShift Assignment`
                    WHERE employee = %s
                      AND start_date <= %s
                      AND (end_date >= %s OR end_date IS NULL OR end_date = '')
                      AND docstatus = 1
                    LIMIT 1
                    """,
                    (emp_id, att_date, att_date),
                )
            )
            shift_assignment_exists_cache[key] = exists
        return shift_assignment_exists_cache[key]

    # Current date threshold for stale record check (Category 4)
    today_date = getdate(nowdate())
    stale_date_threshold = add_days(today_date, -1)

    # Initialize results containers for Category 1 through 6 rules
    cat1_r1_1: List[Dict[str, Any]] = []
    cat1_r1_2: List[Dict[str, Any]] = []
    cat1_r1_3: List[Dict[str, Any]] = []
    cat1_r1_4: List[Dict[str, Any]] = []

    cat2_r2_1: List[Dict[str, Any]] = []
    cat2_r2_2: List[Dict[str, Any]] = []
    cat2_r2_3: List[Dict[str, Any]] = []

    cat3_r3_1: List[Dict[str, Any]] = []
    cat3_r3_2: List[Dict[str, Any]] = []
    cat3_r3_3: List[Dict[str, Any]] = []

    cat4_r4_1: List[Dict[str, Any]] = []

    cat5_r5_1: List[Dict[str, Any]] = []

    cat6_r6_1: List[Dict[str, Any]] = []
    cat6_r6_2: List[Dict[str, Any]] = []

    # Grouping container for Category 5 (Duplicate Attendance Records)
    employee_date_records: Dict[Tuple[str, str], List[str]] = {}

    for att in attendances:
        att_name = att.get("name")
        employee = att.get("employee")
        att_date = att.get("attendance_date")
        status = att.get("status")
        in_time = att.get("in_time")
        out_time = att.get("out_time")
        working_hours = flt(att.get("working_hours"))
        shift_name = att.get("shift")
        attendance_request = att.get("attendance_request")
        leave_type = att.get("leave_type")
        leave_app = att.get("leave_application")
        short_leave_count = flt(att.get("custom_short_leave_count"))
        company = att.get("company")
        docstatus = att.get("docstatus")

        # ---------------------------------------------------------------------
        # CATEGORY 5 (Grouping phase): Track active attendance records
        # ---------------------------------------------------------------------
        if docstatus != 2:
            key = (employee, str(att_date))
            if key not in employee_date_records:
                employee_date_records[key] = []
            employee_date_records[key].append(att_name)

        # Lookup Shift Type thresholds
        shift_info = shift_types.get(shift_name) if shift_name else None
        half_day_threshold = (
            flt(shift_info.get("working_hours_threshold_for_half_day"))
            if shift_info
            else 0.0
        )

        # ---------------------------------------------------------------------
        # CATEGORY 1: Incorrect Punch/Status Combinations
        # ---------------------------------------------------------------------

        # Rule 1.1: Mispunch with complete punches
        if status == "Mispunch" and in_time and out_time:
            cat1_r1_1.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "in_time": str(in_time),
                    "out_time": str(out_time),
                }
            )

        # Rule 1.2: Present/Absent/Half Day status but only one punch set & no attendance_request
        if (
            status in ("Present", "Absent", "Half Day")
            and (bool(in_time) != bool(out_time))
            and not attendance_request
        ):
            cat1_r1_2.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "in_time": str(in_time) if in_time else None,
                    "out_time": str(out_time) if out_time else None,
                    "attendance_request": attendance_request,
                }
            )

        # Rule 1.3: status="Present" but in_time and out_time both null & no attendance_request
        if (
            status == "Present"
            and not in_time
            and not out_time
            and not attendance_request
        ):
            cat1_r1_3.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "in_time": None,
                    "out_time": None,
                    "attendance_request": attendance_request,
                }
            )

        # Rule 1.4: status="Present" but working_hours is below Shift Type's half day threshold
        if status == "Present" and half_day_threshold > 0 and working_hours < half_day_threshold:
            has_short_leave = bool(
                frappe.db.exists(
                    "Short Leave Application",
                    {
                        "employee": employee,
                        "date": att_date,
                        "docstatus": 1,
                        "workflow_state": "Approved",
                    },
                )
            )
            if not has_short_leave:
                cat1_r1_4.append(
                    {
                        "name": att_name,
                        "employee": employee,
                        "attendance_date": str(att_date),
                        "status": status,
                        "working_hours": working_hours,
                        "shift": shift_name,
                        "half_day_threshold": half_day_threshold,
                        "note": "Working hours below half-day threshold without short leave gap credit",
                    }
                )

        # ---------------------------------------------------------------------
        # CATEGORY 2: Leave & Half Day Inconsistencies
        # ---------------------------------------------------------------------

        # Rule 2.1 — status="On Leave" but leave_type is blank or no approved Leave Application exists for employee+date.
        # NOTE (BEST-EFFORT/INFERRED): This rule's check is marked as best-effort/inferred since leave validation
        # is not strictly enforced in Valence's custom code, but handled via HRMS base behavior.
        if status == "On Leave":
            has_approved_leave = False
            if leave_type or leave_app:
                has_approved_leave = bool(
                    frappe.db.sql(
                        """
                        SELECT name FROM `tabLeave Application`
                        WHERE employee = %s
                          AND %s BETWEEN from_date AND to_date
                          AND docstatus = 1
                          AND status = 'Approved'
                        LIMIT 1
                        """,
                        (employee, att_date),
                    )
                )
            if not leave_type or not has_approved_leave:
                cat2_r2_1.append(
                    {
                        "name": att_name,
                        "employee": employee,
                        "attendance_date": str(att_date),
                        "status": status,
                        "leave_type": leave_type,
                        "leave_application": leave_app,
                        "note": "Best-effort/inferred: On Leave status without valid leave_type or approved Leave Application",
                    }
                )

        # Rule 2.2 — status="Present" (or "Present With Short Leave") but an approved full-day Leave Application exists for employee+date
        if status in ("Present", "Present With Short Leave"):
            approved_full_day_leave = frappe.db.sql(
                """
                SELECT name FROM `tabLeave Application`
                WHERE employee = %s
                  AND %s BETWEEN from_date AND to_date
                  AND docstatus = 1
                  AND status = 'Approved'
                  AND (half_day = 0 OR half_day IS NULL)
                LIMIT 1
                """,
                (employee, att_date),
                as_dict=True,
            )
            if approved_full_day_leave:
                cat2_r2_2.append(
                    {
                        "name": att_name,
                        "employee": employee,
                        "attendance_date": str(att_date),
                        "status": status,
                        "leave_application": approved_full_day_leave[0]["name"],
                    }
                )

        # Rule 2.3 — status="Half Day" but working_hours above full-day threshold, no half-day leave linked, and short-leave count isn't zero
        if status == "Half Day" and half_day_threshold > 0:
            if working_hours >= half_day_threshold and short_leave_count != 0:
                has_half_day_leave = False
                if leave_app:
                    leave_doc_half_day = frappe.db.get_value(
                        "Leave Application", leave_app, "half_day"
                    )
                    if leave_doc_half_day:
                        has_half_day_leave = True

                if not has_half_day_leave:
                    cat2_r2_3.append(
                        {
                            "name": att_name,
                            "employee": employee,
                            "attendance_date": str(att_date),
                            "status": status,
                            "working_hours": working_hours,
                            "leave_application": leave_app,
                            "short_leave_count": short_leave_count,
                            "full_day_threshold": half_day_threshold,
                        }
                    )

        # ---------------------------------------------------------------------
        # CATEGORY 3: Weekly Off / Holiday Mismatches
        # ---------------------------------------------------------------------

        h_list = get_employee_holiday_list(employee, company)

        # Rule 3.1: status="Weekly Off" but date isn't actually a weekly off
        if status == "Weekly Off":
            is_weekly_off_in_list = False
            if h_list:
                h_rec = get_holiday_record(h_list, att_date)
                if h_rec and h_rec.get("weekly_off") == 1:
                    is_weekly_off_in_list = True

            is_weekly_off_in_shift = is_shift_weekly_off(employee, att_date)

            if not is_weekly_off_in_list and not is_weekly_off_in_shift:
                cat3_r3_1.append(
                    {
                        "name": att_name,
                        "employee": employee,
                        "attendance_date": str(att_date),
                        "status": status,
                        "holiday_list": h_list,
                        "shift": shift_name,
                    }
                )

        # Rule 3.2: status="Holiday" but no Holiday record exists in Holiday List with weekly_off=0
        if status == "Holiday":
            is_valid_holiday = False
            if h_list:
                h_rec = get_holiday_record(h_list, att_date)
                if h_rec and h_rec.get("weekly_off") == 0:
                    is_valid_holiday = True

            if not is_valid_holiday:
                cat3_r3_2.append(
                    {
                        "name": att_name,
                        "employee": employee,
                        "attendance_date": str(att_date),
                        "status": status,
                        "holiday_list": h_list,
                    }
                )

        # Rule 3.3: in_time and out_time both exist, but status is still "Weekly Off" or "Holiday"
        if status in ("Weekly Off", "Holiday") and in_time and out_time:
            cat3_r3_3.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "in_time": str(in_time),
                    "out_time": str(out_time),
                }
            )

        # ---------------------------------------------------------------------
        # CATEGORY 4: Old Unresolved No Punch
        # ---------------------------------------------------------------------

        # Rule 4.1: status="No punch" and attendance_date is more than 1 day before today
        if status == "No punch" and getdate(att_date) < stale_date_threshold:
            cat4_r4_1.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "note": "Stale unresolved No punch record",
                }
            )

        # ---------------------------------------------------------------------
        # CATEGORY 6: Missing Setup Assets (Rule 6.2: Missing Shift Assignment)
        # ---------------------------------------------------------------------

        # Rule 6.2: Attendance record missing active Shift Assignment for employee on attendance_date
        if not has_active_shift_assignment(employee, att_date):
            cat6_r6_2.append(
                {
                    "name": att_name,
                    "employee": employee,
                    "attendance_date": str(att_date),
                    "status": status,
                    "note": "No active Shift Assignment found for attendance date",
                }
            )

    # -------------------------------------------------------------------------
    # CATEGORY 5: Duplicate Attendance Records (Rule 5.1 evaluation)
    # -------------------------------------------------------------------------
    for (emp, att_date_str), names in employee_date_records.items():
        if len(names) > 1:
            cat5_r5_1.append(
                {
                    "employee": emp,
                    "attendance_date": att_date_str,
                    "record_count": len(names),
                    "records": names,
                }
            )

    # -------------------------------------------------------------------------
    # CATEGORY 6: Missing Setup Assets (Rule 6.1 evaluation)
    # -------------------------------------------------------------------------
    active_employees = frappe.db.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "company", "holiday_list"],
    )
    company_default_holiday_lists: Dict[str, Optional[str]] = {}
    for comp in frappe.db.get_all("Company", fields=["name", "default_holiday_list"]):
        company_default_holiday_lists[comp["name"]] = comp.get("default_holiday_list")

    for emp_doc in active_employees:
        emp_holiday_list = emp_doc.get("holiday_list")
        emp_company = emp_doc.get("company")
        comp_default_list = (
            company_default_holiday_lists.get(emp_company) if emp_company else None
        )

        if not emp_holiday_list and not comp_default_list:
            cat6_r6_1.append(
                {
                    "employee": emp_doc.get("name"),
                    "employee_name": emp_doc.get("employee_name"),
                    "company": emp_company,
                    "note": "Active employee has no holiday_list set and company has no default_holiday_list",
                }
            )

    results: Dict[str, Any] = {
        "category_1": {
            "rule_1_1": cat1_r1_1,
            "rule_1_2": cat1_r1_2,
            "rule_1_3": cat1_r1_3,
            "rule_1_4": cat1_r1_4,
        },
        "category_2": {
            "rule_2_1": cat2_r2_1,
            "rule_2_2": cat2_r2_2,
            "rule_2_3": cat2_r2_3,
        },
        "category_3": {
            "rule_3_1": cat3_r3_1,
            "rule_3_2": cat3_r3_2,
            "rule_3_3": cat3_r3_3,
        },
        "category_4": {
            "rule_4_1": cat4_r4_1,
        },
        "category_5": {
            "rule_5_1": cat5_r5_1,
        },
        "category_6": {
            "rule_6_1": cat6_r6_1,
            "rule_6_2": cat6_r6_2,
        },
    }

    return results


def print_report(results: Dict[str, Any]) -> None:
    """
    Format and print the attendance audit execute() results into a readable console report.

    :param results: The results dictionary returned by execute()
    """
    category_titles = {
        "category_1": "Category 1: Incorrect Punch/Status Combinations",
        "category_2": "Category 2: Leave & Half Day Inconsistencies",
        "category_3": "Category 3: Weekly Off / Holiday Mismatches",
        "category_4": "Category 4: Old Unresolved No Punch",
        "category_5": "Category 5: Duplicate Attendance Records",
        "category_6": "Category 6: Missing Setup Assets",
    }

    rule_descriptions = {
        "rule_1_1": "Rule 1.1: Mispunch with complete punches",
        "rule_1_2": "Rule 1.2: Present/Absent/Half Day status with single punch & no attendance request",
        "rule_1_3": "Rule 1.3: Present status with no punches & no attendance request",
        "rule_1_4": "Rule 1.4: Present status below half-day threshold without short leave gap credit",
        "rule_2_1": "Rule 2.1: On Leave status without valid leave type or approved Leave Application",
        "rule_2_2": "Rule 2.2: Present status with approved full-day Leave Application",
        "rule_2_3": "Rule 2.3: Half Day status with high working hours & no half-day leave linked",
        "rule_3_1": "Rule 3.1: Weekly Off status but date is not a weekly off",
        "rule_3_2": "Rule 3.2: Holiday status but no Holiday record in Holiday List",
        "rule_3_3": "Rule 3.3: Punches exist but status is still Weekly Off or Holiday",
        "rule_4_1": "Rule 4.1: Stale unresolved No punch record (> 1 day old)",
        "rule_5_1": "Rule 5.1: Duplicate Attendance records for employee + date",
        "rule_6_1": "Rule 6.1: Active employee missing Holiday List",
        "rule_6_2": "Rule 6.2: Attendance record missing active Shift Assignment",
    }

    total_issues = 0
    print("=" * 70)
    print("                      ATTENDANCE AUDIT REPORT                      ")
    print("=" * 70)

    for cat_key, cat_title in category_titles.items():
        cat_data = results.get(cat_key, {})
        cat_issue_count = sum(len(items) for items in cat_data.values())
        total_issues += cat_issue_count

        print(f"\n--- {cat_title} (Total Issues: {cat_issue_count}) ---")

        for rule_key, items in cat_data.items():
            rule_desc = rule_descriptions.get(rule_key, rule_key)
            rule_count = len(items)
            print(f"  [{rule_key}] {rule_desc}: {rule_count} issue(s)")

            # Show up to 2 sample records per rule
            samples = items[:2]
            for idx, item in enumerate(samples, 1):
                fields_str = ", ".join(f"{k}={v}" for k, v in item.items())
                print(f"    Sample {idx}: {fields_str}")

    print("\n" + "=" * 70)
    print(f"TOTAL ISSUES ACROSS ALL CATEGORIES: {total_issues}")
    print("=" * 70)
