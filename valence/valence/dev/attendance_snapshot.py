from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def validate_output_path(output_path: str) -> Path:
    repo_root = get_repo_root().resolve()
    resolved_out = Path(output_path).resolve()

    is_inside_repo = False
    try:
        resolved_out.relative_to(repo_root)
        is_inside_repo = True
    except ValueError:
        is_inside_repo = False

    if is_inside_repo or resolved_out == repo_root:
        raise ValueError(
            f"Security Error: Output path '{resolved_out}' is inside the repository ({repo_root}). "
            "Snapshot files must remain strictly outside the repository."
        )

    return resolved_out


def _to_iso_date(val: Any) -> Optional[str]:
    if val is None or val == "":
        return None
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            return getdate(val).strftime("%Y-%m-%d")
        except Exception:
            return val
    try:
        return getdate(val).strftime("%Y-%m-%d")
    except Exception:
        return str(val)


def _to_iso_datetime(val: Any) -> Optional[str]:
    if val is None or val == "":
        return None
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            return get_datetime(val).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return val
    try:
        return get_datetime(val).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)


def _to_rounded_float(val: Any, decimals: int = 2) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return round(float(flt(val)), decimals)
    except Exception:
        return None


def _to_int_or_none(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except Exception:
        return None


def _as_timedelta(value: Any) -> Optional[timedelta]:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if hasattr(value, "hour"):
        return timedelta(hours=value.hour, minutes=value.minute, seconds=getattr(value, "second", 0) or 0)
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) >= 2:
            try:
                h = int(parts[0])
                m = int(parts[1])
                s = int(parts[2]) if len(parts) > 2 else 0
                return timedelta(hours=h, minutes=m, seconds=s)
            except Exception:
                return None
    return None


def _get_company_default_holiday_list() -> Optional[str]:
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")
    if company:
        return frappe.db.get_value("Company", company, "default_holiday_list")
    return None


def _get_applicable_shift_assignment(employee: str, date_str: str) -> Optional[Dict[str, Any]]:
    if not employee or not date_str:
        return None

    has_custom_off_day = frappe.get_meta("Shift Assignment").has_field("custom_off_day")
    has_status = frappe.get_meta("Shift Assignment").has_field("status")

    fields = [
        "name",
        "employee",
        "employee_name",
        "shift_type",
        "start_date",
        "end_date",
        "company",
        "department",
        "docstatus",
    ]
    if has_custom_off_day:
        fields.append("custom_off_day")
    if has_status:
        fields.append("status")

    filters: List[Any] = [
        ["employee", "=", employee],
        ["start_date", "<=", date_str],
        ["docstatus", "=", 1],
    ]
    if has_status:
        filters.append(["status", "=", "Active"])

    or_filters = [
        ["end_date", ">=", date_str],
        ["end_date", "is", "not set"],
    ]

    assignments = frappe.get_all(
        "Shift Assignment",
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        order_by="start_date desc, creation desc, name desc",
        limit_page_length=1,
    )

    if not assignments:
        return None

    row = assignments[0]
    return {
        "name": row.get("name"),
        "employee": row.get("employee"),
        "employee_name": row.get("employee_name"),
        "shift_type": row.get("shift_type"),
        "start_date": _to_iso_date(row.get("start_date")),
        "end_date": _to_iso_date(row.get("end_date")),
        "custom_off_day": row.get("custom_off_day"),
        "status": row.get("status") if has_status else "Active",
        "company": row.get("company"),
        "department": row.get("department"),
        "docstatus": _to_int_or_none(row.get("docstatus")),
    }


def _is_overnight_shift(shift_type: Optional[str]) -> bool:
    if not shift_type or not frappe.db.exists("Shift Type", shift_type):
        return False
    times = frappe.db.get_value("Shift Type", shift_type, ["start_time", "end_time"], as_dict=True)
    if not times or times.get("start_time") is None or times.get("end_time") is None:
        return False
    st = _as_timedelta(times["start_time"])
    et = _as_timedelta(times["end_time"])
    if not st or not et:
        return False
    return st > et


def fetch_attendance_records(
    from_date: str, to_date: str, employee: Optional[str] = None
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {
        "attendance_date": ["between", [from_date, to_date]],
        "docstatus": ["in", [0, 1, 2]],
    }
    if employee:
        filters["employee"] = employee

    has_short_leave_type = frappe.get_meta("Attendance").has_field("custom_short_leave_type")
    has_short_leave_count = frappe.get_meta("Attendance").has_field("custom_short_leave_count")
    has_half_day_status = frappe.get_meta("Attendance").has_field("half_day_status")

    fields = [
        "name",
        "employee",
        "employee_name",
        "attendance_date",
        "status",
        "working_hours",
        "in_time",
        "out_time",
        "shift",
        "leave_type",
        "leave_application",
        "attendance_request",
        "late_entry",
        "early_exit",
        "amended_from",
        "company",
        "department",
        "docstatus",
    ]
    if has_short_leave_type:
        fields.append("custom_short_leave_type")
    if has_short_leave_count:
        fields.append("custom_short_leave_count")
    if has_half_day_status:
        fields.append("half_day_status")

    raw_records = frappe.get_all("Attendance", filters=filters, fields=fields)

    normalized = []
    for row in raw_records:
        rec = {
            "name": row.get("name"),
            "employee": row.get("employee"),
            "employee_name": row.get("employee_name"),
            "attendance_date": _to_iso_date(row.get("attendance_date")),
            "status": row.get("status"),
            "working_hours": _to_rounded_float(row.get("working_hours")),
            "in_time": _to_iso_datetime(row.get("in_time")),
            "out_time": _to_iso_datetime(row.get("out_time")),
            "shift": row.get("shift"),
            "leave_type": row.get("leave_type"),
            "leave_application": row.get("leave_application"),
            "attendance_request": row.get("attendance_request"),
            "half_day_status": row.get("half_day_status"),
            "late_entry": _to_int_or_none(row.get("late_entry")),
            "early_exit": _to_int_or_none(row.get("early_exit")),
            "amended_from": row.get("amended_from"),
            "company": row.get("company"),
            "department": row.get("department"),
            "custom_short_leave_type": row.get("custom_short_leave_type"),
            "custom_short_leave_count": _to_rounded_float(row.get("custom_short_leave_count")),
            "docstatus": _to_int_or_none(row.get("docstatus")),
        }
        normalized.append(rec)

    normalized.sort(
        key=lambda x: (
            x.get("employee") or "",
            str(x.get("attendance_date") or ""),
            x.get("name") or "",
        )
    )
    return normalized


def fetch_employee_checkins(
    from_date: str, to_date: str, employee: Optional[str] = None
) -> List[Dict[str, Any]]:
    start_dt = f"{from_date} 00:00:00"
    end_dt = f"{add_days(to_date, 2)} 00:00:00"

    filters: List[Any] = [
        ["time", ">=", start_dt],
        ["time", "<", end_dt],
        ["docstatus", "in", [0, 1, 2]],
    ]
    if employee:
        filters.append(["employee", "=", employee])

    fields = [
        "name",
        "employee",
        "employee_name",
        "time",
        "log_type",
        "device_id",
        "shift",
        "skip_auto_attendance",
        "attendance",
        "docstatus",
    ]

    raw_records = frappe.get_all("Employee Checkin", filters=filters, fields=fields)

    normalized = []
    for row in raw_records:
        t_str = _to_iso_datetime(row.get("time"))
        if not t_str:
            continue

        punch_date = t_str[:10]
        if punch_date > to_date:
            emp = row.get("employee")
            sa_prev = _get_applicable_shift_assignment(emp, to_date)
            shift_type = row.get("shift") or (sa_prev.get("shift_type") if sa_prev else None)
            if not _is_overnight_shift(shift_type):
                continue
            if t_str >= f"{add_days(to_date, 1)} 14:00:00":
                continue

        rec = {
            "name": row.get("name"),
            "employee": row.get("employee"),
            "employee_name": row.get("employee_name"),
            "time": t_str,
            "log_type": row.get("log_type"),
            "device_id": row.get("device_id"),
            "shift": row.get("shift"),
            "skip_auto_attendance": _to_int_or_none(row.get("skip_auto_attendance")),
            "attendance": row.get("attendance"),
            "docstatus": _to_int_or_none(row.get("docstatus")),
        }
        normalized.append(rec)

    normalized.sort(
        key=lambda x: (
            x.get("employee") or "",
            str(x.get("time") or ""),
            x.get("name") or "",
        )
    )
    return normalized


def fetch_holiday_lists(
    from_date: str,
    to_date: str,
    employee: Optional[str] = None,
    discovered_employees: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    target_employees: Set[str] = set()
    if employee:
        target_employees.add(employee)
    elif discovered_employees:
        target_employees.update(discovered_employees)

    company_default_hl = _get_company_default_holiday_list()
    hl_names: Set[str] = set()

    for emp in target_employees:
        emp_hl = frappe.db.get_value("Employee", emp, "holiday_list")
        if emp_hl:
            hl_names.add(emp_hl)
        elif company_default_hl:
            hl_names.add(company_default_hl)

    if not target_employees and company_default_hl:
        hl_names.add(company_default_hl)

    if not hl_names:
        return []

    normalized_lists = []
    for hl_name in sorted(hl_names):
        hl_data = frappe.db.get_value(
            "Holiday List",
            hl_name,
            ["name", "holiday_list_name", "from_date", "to_date", "weekly_off", "total_holidays"],
            as_dict=True,
        )
        if not hl_data:
            continue

        child_holidays_raw = frappe.get_all(
            "Holiday",
            filters={
                "parent": hl_name,
                "holiday_date": ["between", [from_date, to_date]],
            },
            fields=["name", "holiday_date", "description", "weekly_off"],
        )

        child_holidays = []
        for h in child_holidays_raw:
            child_holidays.append(
                {
                    "name": h.get("name"),
                    "holiday_date": _to_iso_date(h.get("holiday_date")),
                    "description": h.get("description"),
                    "weekly_off": _to_int_or_none(h.get("weekly_off")),
                }
            )

        child_holidays.sort(
            key=lambda x: (str(x.get("holiday_date") or ""), x.get("name") or "")
        )

        hl_rec = {
            "name": hl_data.get("name"),
            "holiday_list_name": hl_data.get("holiday_list_name"),
            "from_date": _to_iso_date(hl_data.get("from_date")),
            "to_date": _to_iso_date(hl_data.get("to_date")),
            "weekly_off": hl_data.get("weekly_off"),
            "total_holidays": _to_int_or_none(hl_data.get("total_holidays")),
            "holidays": child_holidays,
        }
        normalized_lists.append(hl_rec)

    normalized_lists.sort(key=lambda x: x.get("name") or "")
    return normalized_lists


def fetch_shift_assignments(
    from_date: str, to_date: str, employee: Optional[str] = None
) -> List[Dict[str, Any]]:
    has_custom_off_day = frappe.get_meta("Shift Assignment").has_field("custom_off_day")
    has_status = frappe.get_meta("Shift Assignment").has_field("status")

    filters: List[Any] = [
        ["docstatus", "=", 1],
        ["start_date", "<=", to_date],
    ]
    if employee:
        filters.append(["employee", "=", employee])
    if has_status:
        filters.append(["status", "=", "Active"])

    or_filters = [
        ["end_date", ">=", from_date],
        ["end_date", "is", "not set"],
    ]

    fields = [
        "name",
        "employee",
        "employee_name",
        "shift_type",
        "start_date",
        "end_date",
        "company",
        "department",
        "docstatus",
    ]
    if has_custom_off_day:
        fields.append("custom_off_day")
    if has_status:
        fields.append("status")

    raw_records = frappe.get_all(
        "Shift Assignment",
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        order_by="employee asc, start_date desc, creation desc, name desc",
    )

    normalized = []
    for row in raw_records:
        rec = {
            "name": row.get("name"),
            "employee": row.get("employee"),
            "employee_name": row.get("employee_name"),
            "shift_type": row.get("shift_type"),
            "start_date": _to_iso_date(row.get("start_date")),
            "end_date": _to_iso_date(row.get("end_date")),
            "custom_off_day": row.get("custom_off_day"),
            "status": row.get("status") if has_status else "Active",
            "company": row.get("company"),
            "department": row.get("department"),
            "docstatus": _to_int_or_none(row.get("docstatus")),
        }
        normalized.append(rec)

    normalized.sort(
        key=lambda x: (
            x.get("employee") or "",
            str(x.get("start_date") or ""),
            x.get("name") or "",
        )
    )
    return normalized


def build_checkin_summaries(
    from_date: str,
    to_date: str,
    employee: Optional[str] = None,
    attendance_records: Optional[List[Dict[str, Any]]] = None,
    checkins: Optional[List[Dict[str, Any]]] = None,
    shift_assignments: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    target_employees: Set[str] = set()
    if employee:
        target_employees.add(employee)
    else:
        if attendance_records:
            for row in attendance_records:
                if row.get("employee"):
                    target_employees.add(row["employee"])
        if checkins:
            for row in checkins:
                if row.get("employee"):
                    target_employees.add(row["employee"])
        if shift_assignments:
            for row in shift_assignments:
                if row.get("employee"):
                    target_employees.add(row["employee"])

    if not target_employees:
        return []

    company_default_hl = _get_company_default_holiday_list()

    emp_checkins_map: Dict[str, List[Dict[str, Any]]] = {emp: [] for emp in target_employees}
    if checkins:
        for chk in checkins:
            emp = chk.get("employee")
            if emp in emp_checkins_map:
                emp_checkins_map[emp].append(chk)

    for emp in emp_checkins_map:
        emp_checkins_map[emp].sort(key=lambda x: str(x.get("time") or ""))

    summaries: List[Dict[str, Any]] = []

    start_d = getdate(from_date)
    end_d = getdate(to_date)

    for emp in sorted(target_employees):
        emp_hl = frappe.db.get_value("Employee", emp, "holiday_list") or company_default_hl

        curr_d = start_d
        while curr_d <= end_d:
            date_str = curr_d.strftime("%Y-%m-%d")
            next_date_str = add_days(date_str, 1)

            sa = _get_applicable_shift_assignment(emp, date_str)
            custom_off_day = sa.get("custom_off_day") if sa else None
            shift_type = sa.get("shift_type") if sa else None
            is_overnight = _is_overnight_shift(shift_type)

            if is_overnight:
                w_start = f"{date_str} 00:00:00"
                w_end = f"{next_date_str} 14:00:00"
            else:
                w_start = f"{date_str} 00:00:00"
                w_end = f"{next_date_str} 00:00:00"

            matching_punches = []
            for chk in emp_checkins_map.get(emp, []):
                t_val = str(chk.get("time") or "")
                if not t_val:
                    continue
                if is_overnight:
                    if w_start <= t_val < w_end:
                        matching_punches.append(t_val)
                else:
                    if w_start <= t_val < w_end:
                        matching_punches.append(t_val)

            count = len(matching_punches)
            earliest_punch = min(matching_punches) if matching_punches else None
            latest_punch = max(matching_punches) if matching_punches else None

            summary_item = {
                "name": f"{emp}::{date_str}",
                "employee": emp,
                "date": date_str,
                "count": count,
                "earliest_punch": earliest_punch,
                "latest_punch": latest_punch,
                "holiday_list": emp_hl,
                "custom_off_day": custom_off_day,
            }
            summaries.append(summary_item)

            curr_d = add_days(curr_d, 1)

    summaries.sort(
        key=lambda x: (
            x.get("employee") or "",
            str(x.get("date") or ""),
            x.get("name") or "",
        )
    )
    return summaries


def generate_snapshot_data(
    from_date: str, to_date: str, employee: Optional[str] = None
) -> Dict[str, Any]:
    from_date_iso = _to_iso_date(from_date)
    to_date_iso = _to_iso_date(to_date)
    if not from_date_iso or not to_date_iso:
        raise ValueError("Invalid from_date or to_date.")

    attendance = fetch_attendance_records(from_date_iso, to_date_iso, employee)
    checkins = fetch_employee_checkins(from_date_iso, to_date_iso, employee)
    shift_assignments = fetch_shift_assignments(from_date_iso, to_date_iso, employee)

    discovered_employees: Set[str] = set()
    for row in attendance:
        if row.get("employee"):
            discovered_employees.add(row["employee"])
    for row in checkins:
        if row.get("employee"):
            discovered_employees.add(row["employee"])
    for row in shift_assignments:
        if row.get("employee"):
            discovered_employees.add(row["employee"])

    holiday_lists = fetch_holiday_lists(
        from_date_iso, to_date_iso, employee, discovered_employees
    )
    checkin_summaries = build_checkin_summaries(
        from_date_iso,
        to_date_iso,
        employee,
        attendance_records=attendance,
        checkins=checkins,
        shift_assignments=shift_assignments,
    )

    snapshot_data = {
        "metadata": {
            "version": "1.0",
            "from_date": from_date_iso,
            "to_date": to_date_iso,
            "employee": employee,
            "counts": {
                "attendance": len(attendance),
                "employee_checkins": len(checkins),
                "checkin_summaries": len(checkin_summaries),
                "holiday_lists": len(holiday_lists),
                "shift_assignments": len(shift_assignments),
            },
        },
        "attendance": attendance,
        "employee_checkins": checkins,
        "checkin_summaries": checkin_summaries,
        "holiday_lists": holiday_lists,
        "shift_assignments": shift_assignments,
    }
    return snapshot_data


def snapshot(
    from_date: str,
    to_date: str,
    employee: Optional[str] = None,
    output_path: Optional[str] = None,
    pretty: bool = True,
) -> str:
    if not output_path:
        ts = int(time.time())
        emp_tag = f"_{employee}" if employee else ""
        filename = f"attendance_snapshot_{from_date}_{to_date}{emp_tag}_{ts}.json"
        output_path = os.path.join(tempfile.gettempdir(), filename)

    validated_path = validate_output_path(output_path)
    validated_path.parent.mkdir(parents=True, exist_ok=True)

    data = generate_snapshot_data(from_date, to_date, employee)

    indent = 2 if pretty else None
    json_content = json.dumps(data, indent=indent, sort_keys=True, default=str)

    with open(validated_path, "w", encoding="utf-8") as f:
        f.write(json_content)

    print(f"Attendance snapshot successfully written to: {validated_path}")
    print(f"Record summary: {data['metadata']['counts']}")
    return str(validated_path)


capture = snapshot


def _build_identity_map(
    records: List[Dict[str, Any]], doctype_name: str, identity_field: str, snapshot_label: str
) -> Dict[str, Dict[str, Any]]:
    id_map: Dict[str, Dict[str, Any]] = {}
    seen_keys: Set[str] = set()
    duplicates: Set[str] = set()

    for row in records:
        key = row.get(identity_field)
        if not key:
            continue
        if key in seen_keys:
            duplicates.add(key)
        seen_keys.add(key)
        id_map[key] = row

    if duplicates:
        sorted_dups = sorted(duplicates)
        raise ValueError(
            f"Duplicate record identity detected in {doctype_name} ({snapshot_label}). "
            f"Found {len(sorted_dups)} duplicate '{identity_field}' value(s): {sorted_dups}"
        )

    return id_map


def _diff_records(
    list_a: List[Dict[str, Any]],
    list_b: List[Dict[str, Any]],
    doctype_name: str,
    identity_field: str = "name",
    child_diff_field: Optional[str] = None,
) -> Dict[str, Any]:
    map_a = _build_identity_map(list_a, doctype_name, identity_field, "Snapshot A")
    map_b = _build_identity_map(list_b, doctype_name, identity_field, "Snapshot B")

    keys_a = set(map_a.keys())
    keys_b = set(map_b.keys())

    added_keys = sorted(keys_b - keys_a)
    removed_keys = sorted(keys_a - keys_b)
    common_keys = sorted(keys_a & keys_b)

    added = [map_b[k] for k in added_keys]
    removed = [map_a[k] for k in removed_keys]
    changed = []
    unchanged_count = 0

    for key in common_keys:
        row_a = map_a[key]
        row_b = map_b[key]

        field_changes: Dict[str, Dict[str, Any]] = {}
        all_fields = sorted(set(row_a.keys()) | set(row_b.keys()))

        for field in all_fields:
            if field == identity_field:
                continue

            val_a = row_a.get(field)
            val_b = row_b.get(field)

            if child_diff_field and field == child_diff_field and isinstance(val_a, list) and isinstance(val_b, list):
                child_diff = _diff_records(val_a, val_b, f"{doctype_name}.{field}", identity_field="name")
                if child_diff["added"] or child_diff["removed"] or child_diff["changed"]:
                    field_changes[field] = {
                        "old": f"{len(val_a)} rows",
                        "new": f"{len(val_b)} rows",
                        "child_diff": child_diff,
                    }
            elif val_a != val_b:
                field_changes[field] = {
                    "old": val_a,
                    "new": val_b,
                }

        if field_changes:
            changed_entry: Dict[str, Any] = {
                "name": key,
                "changes": field_changes,
            }
            if "employee" in row_b or "employee" in row_a:
                changed_entry["employee"] = row_b.get("employee") or row_a.get("employee")
            if "attendance_date" in row_b or "attendance_date" in row_a:
                changed_entry["attendance_date"] = row_b.get("attendance_date") or row_a.get("attendance_date")
            if "date" in row_b or "date" in row_a:
                changed_entry["date"] = row_b.get("date") or row_a.get("date")

            changed.append(changed_entry)
        else:
            unchanged_count += 1

    return {
        "doctype": doctype_name,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }


def compare_snapshots(data_a: Dict[str, Any], data_b: Dict[str, Any]) -> Dict[str, Any]:
    att_diff = _diff_records(
        data_a.get("attendance", []),
        data_b.get("attendance", []),
        "Attendance",
    )
    checkin_diff = _diff_records(
        data_a.get("employee_checkins", []),
        data_b.get("employee_checkins", []),
        "Employee Checkin",
    )
    summary_diff = _diff_records(
        data_a.get("checkin_summaries", []),
        data_b.get("checkin_summaries", []),
        "Checkin Summary",
    )
    hl_diff = _diff_records(
        data_a.get("holiday_lists", []),
        data_b.get("holiday_lists", []),
        "Holiday List",
        child_diff_field="holidays",
    )
    shift_diff = _diff_records(
        data_a.get("shift_assignments", []),
        data_b.get("shift_assignments", []),
        "Shift Assignment",
    )

    total_added = (
        len(att_diff["added"])
        + len(checkin_diff["added"])
        + len(summary_diff["added"])
        + len(hl_diff["added"])
        + len(shift_diff["added"])
    )
    total_removed = (
        len(att_diff["removed"])
        + len(checkin_diff["removed"])
        + len(summary_diff["removed"])
        + len(hl_diff["removed"])
        + len(shift_diff["removed"])
    )
    total_changed = (
        len(att_diff["changed"])
        + len(checkin_diff["changed"])
        + len(summary_diff["changed"])
        + len(hl_diff["changed"])
        + len(shift_diff["changed"])
    )
    total_differences = total_added + total_removed + total_changed

    return {
        "total_differences": total_differences,
        "summary": {
            "Attendance": {
                "added": len(att_diff["added"]),
                "removed": len(att_diff["removed"]),
                "changed": len(att_diff["changed"]),
                "unchanged": att_diff["unchanged_count"],
            },
            "Employee Checkin": {
                "added": len(checkin_diff["added"]),
                "removed": len(checkin_diff["removed"]),
                "changed": len(checkin_diff["changed"]),
                "unchanged": checkin_diff["unchanged_count"],
            },
            "Checkin Summary": {
                "added": len(summary_diff["added"]),
                "removed": len(summary_diff["removed"]),
                "changed": len(summary_diff["changed"]),
                "unchanged": summary_diff["unchanged_count"],
            },
            "Holiday List": {
                "added": len(hl_diff["added"]),
                "removed": len(hl_diff["removed"]),
                "changed": len(hl_diff["changed"]),
                "unchanged": hl_diff["unchanged_count"],
            },
            "Shift Assignment": {
                "added": len(shift_diff["added"]),
                "removed": len(shift_diff["removed"]),
                "changed": len(shift_diff["changed"]),
                "unchanged": shift_diff["unchanged_count"],
            },
        },
        "details": {
            "attendance": att_diff,
            "employee_checkins": checkin_diff,
            "checkin_summaries": summary_diff,
            "holiday_lists": hl_diff,
            "shift_assignments": shift_diff,
        },
    }


def format_diff_report(diff_result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 68)
    lines.append("ATTENDANCE SNAPSHOT DIFF REPORT")
    lines.append("=" * 68)

    details = diff_result.get("details", {})

    for section_key, title in [
        ("attendance", "ATTENDANCE"),
        ("employee_checkins", "EMPLOYEE CHECKIN"),
        ("checkin_summaries", "CHECKIN SUMMARY"),
        ("holiday_lists", "HOLIDAY LIST"),
        ("shift_assignments", "SHIFT ASSIGNMENT"),
    ]:
        sec = details.get(section_key, {})
        added = sec.get("added", [])
        removed = sec.get("removed", [])
        changed = sec.get("changed", [])

        if not added and not removed and not changed:
            continue

        lines.append(f"\n--- {title} ---")
        if added:
            lines.append(f"  [+] Added ({len(added)}):")
            for item in added:
                name = item.get("name")
                emp = f" (Emp: {item.get('employee')})" if item.get("employee") else ""
                lines.append(f"      + {name}{emp}")
        if removed:
            lines.append(f"  [-] Removed ({len(removed)}):")
            for item in removed:
                name = item.get("name")
                emp = f" (Emp: {item.get('employee')})" if item.get("employee") else ""
                lines.append(f"      - {name}{emp}")
        if changed:
            lines.append(f"  [*] Changed ({len(changed)}):")
            for item in changed:
                name = item.get("name")
                lines.append(f"      * {name}:")
                changes = item.get("changes", {})
                for fld, diff_vals in sorted(changes.items()):
                    if fld == "holidays" and "child_diff" in diff_vals:
                        cd = diff_vals["child_diff"]
                        lines.append(
                            f"          - holidays: Added={len(cd['added'])}, Removed={len(cd['removed'])}, Changed={len(cd['changed'])}"
                        )
                    else:
                        old_v = diff_vals.get("old")
                        new_v = diff_vals.get("new")
                        lines.append(f"          - {fld}: {old_v!r} -> {new_v!r}")

    lines.append("\n" + "=" * 68)
    lines.append("SUMMARY TABLE")
    lines.append("=" * 68)
    lines.append(f"{'DocType':<22} {'Added':<10} {'Removed':<10} {'Changed':<10} {'Unchanged':<10}")
    lines.append("-" * 68)

    summary = diff_result.get("summary", {})
    for dt, counts in summary.items():
        lines.append(
            f"{dt:<22} {counts['added']:<10} {counts['removed']:<10} {counts['changed']:<10} {counts['unchanged']:<10}"
        )

    lines.append("-" * 68)
    lines.append(f"Total Differences: {diff_result['total_differences']}")
    lines.append("=" * 68)

    return "\n".join(lines)


def diff(file_a: str, file_b: str, output_format: str = "text") -> Dict[str, Any]:
    path_a = Path(file_a).resolve()
    path_b = Path(file_b).resolve()

    if not path_a.exists():
        raise FileNotFoundError(f"Snapshot file A not found: {path_a}")
    if not path_b.exists():
        raise FileNotFoundError(f"Snapshot file B not found: {path_b}")

    with open(path_a, "r", encoding="utf-8") as f:
        data_a = json.load(f)
    with open(path_b, "r", encoding="utf-8") as f:
        data_b = json.load(f)

    diff_result = compare_snapshots(data_a, data_b)
    report_text = format_diff_report(diff_result)

    if output_format == "json":
        print(json.dumps(diff_result, indent=2, sort_keys=True, default=str))
    else:
        print(report_text)

    return diff_result


def run_pure_diff_tests() -> bool:
    results: List[Tuple[str, str, str]] = []

    def ok(name: str, cond: bool, detail: str = "") -> None:
        status = "PASS" if cond else "FAIL"
        results.append((status, name, detail))
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

    print("\n--- Running Pure In-Memory Diff Tests ---")

    repo_root = get_repo_root()
    inside_path = os.path.join(str(repo_root), "valence", "test_out.json")
    threw = False
    try:
        validate_output_path(inside_path)
    except ValueError:
        threw = True
    ok("Path Security: Rejects inside-repo output path", threw, f"Path: {inside_path}")

    outside_path = os.path.join(tempfile.gettempdir(), "test_snap_valid.json")
    try:
        validated = validate_output_path(outside_path)
        valid_ok = str(validated) == str(Path(outside_path).resolve())
    except Exception:
        valid_ok = False
    ok("Path Security: Allows external output path", valid_ok, f"Path: {outside_path}")

    mock_base = {
        "metadata": {
            "version": "1.0",
            "from_date": "2026-09-01",
            "to_date": "2026-09-05",
            "employee": "EMP-01",
            "counts": {"attendance": 1, "employee_checkins": 1, "checkin_summaries": 1, "holiday_lists": 1, "shift_assignments": 1},
        },
        "attendance": [
            {
                "name": "HR-ATT-001",
                "employee": "EMP-01",
                "employee_name": "Emp One",
                "attendance_date": "2026-09-01",
                "status": "Present",
                "working_hours": 8.0,
                "in_time": "2026-09-01 09:00:00",
                "out_time": "2026-09-01 17:30:00",
                "shift": "Day Shift",
                "leave_type": None,
                "leave_application": None,
                "attendance_request": None,
                "half_day_status": None,
                "late_entry": 0,
                "early_exit": 0,
                "amended_from": None,
                "company": "Valence",
                "department": "IT",
                "custom_short_leave_type": None,
                "custom_short_leave_count": None,
                "docstatus": 1,
            }
        ],
        "employee_checkins": [
            {
                "name": "IN-001",
                "employee": "EMP-01",
                "employee_name": "Emp One",
                "time": "2026-09-01 09:00:00",
                "log_type": "IN",
                "device_id": "DEV-01",
                "shift": "Day Shift",
                "skip_auto_attendance": 0,
                "attendance": "HR-ATT-001",
                "docstatus": 0,
            }
        ],
        "checkin_summaries": [
            {
                "name": "EMP-01::2026-09-01",
                "employee": "EMP-01",
                "date": "2026-09-01",
                "count": 2,
                "earliest_punch": "2026-09-01 09:00:00",
                "latest_punch": "2026-09-01 17:30:00",
                "holiday_list": "Standard HL",
                "custom_off_day": "Sunday",
            }
        ],
        "holiday_lists": [
            {
                "name": "HL-01",
                "holiday_list_name": "Standard HL",
                "from_date": "2026-09-01",
                "to_date": "2026-09-30",
                "weekly_off": "Sunday",
                "total_holidays": 1,
                "holidays": [
                    {
                        "name": "H-01",
                        "holiday_date": "2026-09-06",
                        "description": "Sunday",
                        "weekly_off": 1,
                    }
                ],
            }
        ],
        "shift_assignments": [
            {
                "name": "SA-001",
                "employee": "EMP-01",
                "employee_name": "Emp One",
                "shift_type": "Day Shift",
                "start_date": "2026-09-01",
                "end_date": None,
                "custom_off_day": "Sunday",
                "status": "Active",
                "company": "Valence",
                "department": "IT",
                "docstatus": 1,
            }
        ],
    }

    mock_copy = json.loads(json.dumps(mock_base))
    diff_zero = compare_snapshots(mock_base, mock_copy)
    ok("Zero Diff Invariant: Identical data gives 0 diffs", diff_zero["total_differences"] == 0)

    mock_modified = json.loads(json.dumps(mock_base))
    mock_modified["attendance"][0]["working_hours"] = 4.0
    mock_modified["attendance"][0]["status"] = "Half Day"
    mock_modified["attendance"][0]["docstatus"] = 2

    diff_mod = compare_snapshots(mock_base, mock_modified)
    ok("Field Diff: Detects field-level changes", diff_mod["total_differences"] == 1)
    att_changes = diff_mod["details"]["attendance"]["changed"][0]["changes"]
    ok("Field Diff: Captures working_hours change", att_changes.get("working_hours") == {"old": 8.0, "new": 4.0})
    ok("Field Diff: Captures status change", att_changes.get("status") == {"old": "Present", "new": "Half Day"})
    ok("Field Diff: Captures docstatus change (cancelled)", att_changes.get("docstatus") == {"old": 1, "new": 2})

    mock_sum_mod = json.loads(json.dumps(mock_base))
    mock_sum_mod["checkin_summaries"][0]["count"] = 4
    mock_sum_mod["checkin_summaries"][0]["latest_punch"] = "2026-09-01 21:00:00"
    diff_sum = compare_snapshots(mock_base, mock_sum_mod)
    ok("Summary Diff: Detects checkin summary modification", diff_sum["total_differences"] == 1)
    sum_changes = diff_sum["details"]["checkin_summaries"]["changed"][0]["changes"]
    ok("Summary Diff: Captures count change", sum_changes.get("count") == {"old": 2, "new": 4})
    ok("Summary Diff: Captures latest punch change", sum_changes.get("latest_punch") == {"old": "2026-09-01 17:30:00", "new": "2026-09-01 21:00:00"})

    mock_added = json.loads(json.dumps(mock_base))
    mock_added["attendance"].append(
        {
            "name": "HR-ATT-002",
            "employee": "EMP-01",
            "employee_name": "Emp One",
            "attendance_date": "2026-09-02",
            "status": "Absent",
            "working_hours": 0.0,
            "in_time": None,
            "out_time": None,
            "shift": "Day Shift",
            "leave_type": None,
            "leave_application": None,
            "attendance_request": None,
            "half_day_status": None,
            "late_entry": 0,
            "early_exit": 0,
            "amended_from": None,
            "company": "Valence",
            "department": "IT",
            "custom_short_leave_type": None,
            "custom_short_leave_count": None,
            "docstatus": 1,
        }
    )
    diff_add = compare_snapshots(mock_base, mock_added)
    ok("Addition Diff: Detects added attendance record", len(diff_add["details"]["attendance"]["added"]) == 1)

    diff_rem = compare_snapshots(mock_added, mock_base)
    ok("Removal Diff: Detects removed attendance record", len(diff_rem["details"]["attendance"]["removed"]) == 1)

    empty_snap = {
        "metadata": {
            "version": "1.0",
            "from_date": "2026-09-01",
            "to_date": "2026-09-05",
            "employee": None,
            "counts": {"attendance": 0, "employee_checkins": 0, "checkin_summaries": 0, "holiday_lists": 0, "shift_assignments": 0},
        },
        "attendance": [],
        "employee_checkins": [],
        "checkin_summaries": [],
        "holiday_lists": [],
        "shift_assignments": [],
    }
    diff_empty = compare_snapshots(empty_snap, empty_snap)
    ok("Empty Data: Comparing empty snapshots gives 0 diffs", diff_empty["total_differences"] == 0)

    mock_dup = json.loads(json.dumps(mock_base))
    mock_dup["attendance"].append(json.loads(json.dumps(mock_base["attendance"][0])))
    dup_threw = False
    dup_err = ""
    try:
        compare_snapshots(mock_base, mock_dup)
    except ValueError as e:
        dup_threw = True
        dup_err = str(e)
    ok("Duplicate Detection: Rejects snapshot with duplicate record identity", dup_threw, dup_err[:80])

    all_passed = all(st == "PASS" for st, _, _ in results)
    print(f"\nPure Diff Tests Result: {'ALL PASS' if all_passed else 'FAILURES DETECTED'}")
    return all_passed
