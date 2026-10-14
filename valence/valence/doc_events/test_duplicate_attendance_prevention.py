from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, nowdate
from hrms.hr.doctype.attendance.attendance import DuplicateAttendanceError


def run():
    frappe.flags.in_test = True
    results = []

    def log_result(name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        results.append((status, name, detail))
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))

    frappe.set_user("Administrator")

    print("")
    print("=" * 76)
    print("REGRESSION TEST SUITE: DUPLICATE ATTENDANCE PREVENTION")
    print("=" * 76)

    # ------------------------------------------------------------------------
    # Setup test company, employee, and non-overlapping shifts
    # ------------------------------------------------------------------------
    company_name = frappe.db.get_value("Company", {}, "name")

    hl_name = "TEST-DUP-HOLIDAY-LIST"
    if not frappe.db.exists("Holiday List", hl_name):
        hl = frappe.new_doc("Holiday List")
        hl.holiday_list_name = hl_name
        hl.from_date = "2026-01-01"
        hl.to_date = "2026-12-31"
        hl.flags.ignore_permissions = True
        hl.insert()

    emp = frappe.new_doc("Employee")
    emp.first_name = "Duplicate"
    emp.last_name = "TestEmp"
    emp.company = company_name
    emp.gender = "Female"
    emp.status = "Active"
    emp.date_of_birth = "1990-01-01"
    emp.date_of_joining = "2026-01-01"
    emp.holiday_list = hl_name
    emp.insert(ignore_permissions=True)
    test_emp_id = emp.name

    shift_a = "TEST-SHIFT-A-MORNING"
    if not frappe.db.exists("Shift Type", shift_a):
        st_a = frappe.new_doc("Shift Type")
        st_a.name = shift_a
        st_a.start_time = "06:00:00"
        st_a.end_time = "14:00:00"
        st_a.enable_auto_attendance = 1
        st_a.process_attendance_after = "2026-01-01"
        st_a.last_sync_of_checkin = "2026-12-31 00:00:00"
        st_a.working_hours_threshold_for_half_day = 4.0
        st_a.working_hours_threshold_for_absent = 1.0
        st_a.flags.ignore_permissions = True
        st_a.flags.ignore_validate = True
        st_a.insert()
    else:
        st_a = frappe.get_doc("Shift Type", shift_a)

    shift_b = "TEST-SHIFT-B-AFTERNOON"
    if not frappe.db.exists("Shift Type", shift_b):
        st_b = frappe.new_doc("Shift Type")
        st_b.name = shift_b
        st_b.start_time = "14:00:00"
        st_b.end_time = "22:00:00"
        st_b.enable_auto_attendance = 1
        st_b.process_attendance_after = "2026-01-01"
        st_b.last_sync_of_checkin = "2026-12-31 00:00:00"
        st_b.working_hours_threshold_for_half_day = 4.0
        st_b.working_hours_threshold_for_absent = 1.0
        st_b.flags.ignore_permissions = True
        st_b.flags.ignore_validate = True
        st_b.insert()
    else:
        st_b = frappe.get_doc("Shift Type", shift_b)

    frappe.db.commit()

    created_holiday_dates = set()

    def cleanup_holiday_entry(date_str):
        d_str = str(date_str)
        if d_str in created_holiday_dates:
            frappe.db.delete("Holiday", {"parent": hl_name, "holiday_date": d_str})
            created_holiday_dates.discard(d_str)

    def cleanup_all_created_holidays():
        if created_holiday_dates:
            for d_str in list(created_holiday_dates):
                frappe.db.delete("Holiday", {"parent": hl_name, "holiday_date": d_str})
            created_holiday_dates.clear()
            frappe.db.commit()

    def cleanup_date(date_str):
        records = frappe.get_all(
            "Attendance",
            filters={"employee": test_emp_id, "attendance_date": date_str},
            pluck="name",
        )
        for name in records:
            att = frappe.get_doc("Attendance", name)
            if att.docstatus == 1:
                att.cancel()
            frappe.db.delete("Attendance", {"name": name})

        checkins = frappe.get_all(
            "Employee Checkin",
            filters={"employee": test_emp_id, "time": ["between", [f"{date_str} 00:00:00", f"{date_str} 23:59:59"]]},
            pluck="name",
        )
        for chk_name in checkins:
            frappe.db.delete("Employee Checkin", {"name": chk_name})

        cleanup_holiday_entry(date_str)
        frappe.db.commit()

    def ensure_holiday(date_str, description="Test Holiday"):
        d_str = str(date_str)
        if not frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": d_str}):
            hl = frappe.get_doc("Holiday List", hl_name)
            hl.append("holidays", {
                "holiday_date": d_str,
                "description": description,
                "weekly_off": 0,
            })
            hl.save(ignore_permissions=True)
            created_holiday_dates.add(d_str)
            frappe.db.commit()

    def ensure_weekly_off(date_str, description="Test Weekly Off"):
        d_str = str(date_str)
        if not frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": d_str}):
            hl = frappe.get_doc("Holiday List", hl_name)
            hl.append("holidays", {
                "holiday_date": d_str,
                "description": description,
                "weekly_off": 1,
            })
            hl.save(ignore_permissions=True)
            created_holiday_dates.add(d_str)
            frappe.db.commit()

    def make_checkin(emp_id, time_str, log_type="IN"):
        chk = frappe.new_doc("Employee Checkin")
        chk.employee = emp_id
        chk.time = time_str
        chk.log_type = log_type
        chk.flags.ignore_permissions = True
        chk.insert()
        return chk

    # ------------------------------------------------------------------------
    # Test 1: Cross-Shift Duplicate Insert Blocked
    # ------------------------------------------------------------------------
    print("\n-- 1. Cross-Shift Duplicate Insert " + "-" * 42)
    test_date_1 = "2026-11-01"
    cleanup_date(test_date_1)

    # Insert first attendance with Shift A
    att1 = frappe.new_doc("Attendance")
    att1.employee = test_emp_id
    att1.attendance_date = test_date_1
    att1.shift = shift_a
    att1.status = "Present"
    att1.insert(ignore_permissions=True)
    att1.submit()

    # Attempt to insert second attendance with Shift B on the same date
    cross_shift_duplicate_blocked = False
    try:
        att2 = frappe.new_doc("Attendance")
        att2.employee = test_emp_id
        att2.attendance_date = test_date_1
        att2.shift = shift_b
        att2.status = "Present"
        att2.insert(ignore_permissions=True)
        att2.submit()
    except DuplicateAttendanceError:
        cross_shift_duplicate_blocked = True
    except Exception as e:
        if "Duplicate" in str(e):
            cross_shift_duplicate_blocked = True

    count_date_1 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_1, "docstatus": ["<", 2]},
    )
    log_result(
        "Cross-shift duplicate insert raises DuplicateAttendanceError",
        cross_shift_duplicate_blocked,
        f"blocked={cross_shift_duplicate_blocked}, active records in DB={count_date_1}",
    )

    # ------------------------------------------------------------------------
    # Test 2: Auto Absent Marking Respects Attendance Under Other Shifts
    # ------------------------------------------------------------------------
    print("\n-- 2. Auto Absent Marking Other-Shift Respect " + "-" * 32)
    test_date_2 = "2026-11-02"
    cleanup_date(test_date_2)

    att_shift_a = frappe.new_doc("Attendance")
    att_shift_a.employee = test_emp_id
    att_shift_a.attendance_date = test_date_2
    att_shift_a.shift = shift_a
    att_shift_a.status = "Present"
    att_shift_a.insert(ignore_permissions=True)
    att_shift_a.submit()

    # Query marked dates from Shift B's perspective
    shift_b_marked_dates = st_b.get_marked_attendance_dates_between(
        test_emp_id, test_date_2, test_date_2
    )
    recognizes_other_shift = getdate(test_date_2) in [getdate(d) for d in shift_b_marked_dates]

    log_result(
        "ShiftType.get_marked_attendance_dates_between detects attendance marked under different shift",
        recognizes_other_shift,
        f"Shift B marked_dates={shift_b_marked_dates}",
    )

    # ------------------------------------------------------------------------
    # Test 3: Attendance Rebuild In-Place Update (No Duplicates)
    # ------------------------------------------------------------------------
    print("\n-- 3. Attendance Rebuild Duplicate Immunity " + "-" * 34)
    test_date_3 = "2026-11-03"
    cleanup_date(test_date_3)

    att_existing = frappe.new_doc("Attendance")
    att_existing.employee = test_emp_id
    att_existing.attendance_date = test_date_3
    att_existing.shift = shift_a
    att_existing.status = "No punch"
    att_existing.insert(ignore_permissions=True)
    att_existing.submit()

    from valence.valence.doc_events.attendance_rebuild import create_attendance

    emp_doc = frappe.db.get_value(
        "Employee",
        test_emp_id,
        ["name", "employee_name", "company", "date_of_joining", "relieving_date"],
        as_dict=True,
    )

    res_create = create_attendance(
        emp_doc,
        getdate(test_date_3),
        shift_a,
        "Present",
        8.0,
        f"{test_date_3} 09:00:00",
        f"{test_date_3} 17:00:00",
        test_date_3,
    )

    count_date_3 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_3, "docstatus": ["<", 2]},
    )

    log_result(
        "attendance_rebuild.create_attendance does not create duplicate when attendance exists",
        count_date_3 == 1,
        f"active records={count_date_3}, action={res_create.get('action')}",
    )

    # ------------------------------------------------------------------------
    # Test 4: Attendance Request Reuses Existing Attendance Across Shifts
    # ------------------------------------------------------------------------
    print("\n-- 4. Attendance Request Shift Alignment " + "-" * 37)
    test_date_4 = "2026-11-04"
    cleanup_date(test_date_4)

    # Existing attendance has Shift A
    att_for_ar = frappe.new_doc("Attendance")
    att_for_ar.employee = test_emp_id
    att_for_ar.attendance_date = test_date_4
    att_for_ar.shift = shift_a
    att_for_ar.status = "No punch"
    att_for_ar.insert(ignore_permissions=True)
    att_for_ar.submit()

    # Submit Attendance Request with Shift B
    ar = frappe.new_doc("Attendance Request")
    ar.employee = test_emp_id
    ar.from_date = test_date_4
    ar.to_date = test_date_4
    ar.reason = "Work From Home"
    ar.shift = shift_b
    ar.include_holidays = 1
    ar.explanation = "Regression test OD/WFH"
    ar.flags.ignore_permissions = True
    ar.insert()
    ar.submit()

    count_date_4 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_4, "docstatus": ["<", 2]},
    )
    ar.reload()
    shift_preserved = ar.shift == shift_b

    att_for_ar.reload()
    status_updated = att_for_ar.status == "Work From Home" and att_for_ar.attendance_request == ar.name

    log_result(
        "Attendance Request reuses existing attendance without creating duplicate",
        count_date_4 == 1,
        f"active records={count_date_4}",
    )
    log_result(
        "Attendance Request own shift field is not corrupted",
        shift_preserved,
        f"ar.shift={ar.shift}, expected={shift_b}",
    )
    log_result(
        "Existing Attendance document updated with Attendance Request status and link",
        status_updated,
        f"status={att_for_ar.status}, req_link={att_for_ar.attendance_request}",
    )

    # ------------------------------------------------------------------------
    # Test 5: Leave Application Updates Existing Without Duplication
    # ------------------------------------------------------------------------
    print("\n-- 5. Leave Application Existing Attendance Update " + "-" * 26)
    test_date_5 = "2026-11-05"
    cleanup_date(test_date_5)

    att_before_leave = frappe.new_doc("Attendance")
    att_before_leave.employee = test_emp_id
    att_before_leave.attendance_date = test_date_5
    att_before_leave.status = "Absent"
    att_before_leave.insert(ignore_permissions=True)
    att_before_leave.submit()

    leave_type = frappe.db.get_value("Leave Type", {}, "name")
    if not leave_type:
        lt = frappe.new_doc("Leave Type")
        lt.leave_type_name = "Test-Leave-Dup-Suite"
        lt.insert(ignore_permissions=True)
        leave_type = lt.name

    la = frappe.new_doc("Leave Application")
    la.employee = test_emp_id
    la.leave_type = leave_type
    la.from_date = test_date_5
    la.to_date = test_date_5
    la.description = "Test leave update"
    la.status = "Approved"
    la.flags.ignore_permissions = True
    la.flags.ignore_validate = True
    la.insert()
    la.update_attendance()

    count_date_5 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_5, "docstatus": ["<", 2]},
    )
    att_before_leave.reload()

    log_result(
        "Leave Application updates existing attendance in-place without duplicate",
        count_date_5 == 1 and att_before_leave.status == "On Leave",
        f"active records={count_date_5}, status={att_before_leave.status}",
    )

    # ------------------------------------------------------------------------
    # Test 6: Half Day Leave In-Place Update & Second Insert Rejection
    # ------------------------------------------------------------------------
    print("\n-- 6. Half Day Leave Compatibility " + "-" * 40)
    test_date_6 = "2026-11-06"
    cleanup_date(test_date_6)

    # Half day leave attendance document with modify_half_day_status = 1
    att_hd = frappe.new_doc("Attendance")
    att_hd.employee = test_emp_id
    att_hd.attendance_date = test_date_6
    att_hd.status = "Half Day"
    att_hd.half_day_status = "Present"
    att_hd.modify_half_day_status = 1
    att_hd.leave_type = leave_type
    att_hd.insert(ignore_permissions=True)
    att_hd.submit()

    # An insert of a second document on the same date should be blocked
    second_hd_blocked = False
    try:
        att_hd_2 = frappe.new_doc("Attendance")
        att_hd_2.employee = test_emp_id
        att_hd_2.attendance_date = test_date_6
        att_hd_2.status = "Present"
        att_hd_2.insert(ignore_permissions=True)
        att_hd_2.submit()
    except DuplicateAttendanceError:
        second_hd_blocked = True
    except Exception as e:
        if "Duplicate" in str(e):
            second_hd_blocked = True

    count_date_6 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_6, "docstatus": ["<", 2]},
    )
    log_result(
        "Second Attendance insert is blocked even when existing has modify_half_day_status=1",
        second_hd_blocked and count_date_6 == 1,
        f"blocked={second_hd_blocked}, active records={count_date_6}",
    )

    # ------------------------------------------------------------------------
    # Test 7: Employee Row-Level Locking Serialization
    # ------------------------------------------------------------------------
    print("\n-- 7. Employee Row Lock Verification " + "-" * 39)
    locked = False
    try:
        frappe.db.sql(
            "SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE",
            (test_emp_id,),
        )
        locked = True
    except Exception as e:
        locked = False

    log_result(
        "Employee row lock (SELECT ... FOR UPDATE) executes successfully",
        locked,
        f"employee={test_emp_id}",
    )

    # ------------------------------------------------------------------------
    # Test 8: Programmatic Insert with ignore_validate=True Blocked
    # ------------------------------------------------------------------------
    print("\n-- 8. Ignore Validate Bypass Blocked in before_insert " + "-" * 20)
    test_date_8 = "2026-11-08"
    cleanup_date(test_date_8)

    att_base = frappe.new_doc("Attendance")
    att_base.employee = test_emp_id
    att_base.attendance_date = test_date_8
    att_base.status = "Present"
    att_base.insert(ignore_permissions=True)
    att_base.submit()

    ignore_val_blocked = False
    try:
        att_bypasser = frappe.new_doc("Attendance")
        att_bypasser.employee = test_emp_id
        att_bypasser.attendance_date = test_date_8
        att_bypasser.status = "Absent"
        att_bypasser.flags.ignore_validate = True
        att_bypasser.insert(ignore_permissions=True)
    except DuplicateAttendanceError:
        ignore_val_blocked = True
    except Exception as e:
        if "Duplicate" in str(e):
            ignore_val_blocked = True

    count_date_8 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_8, "docstatus": ["<", 2]},
    )
    log_result(
        "Direct insert with flags.ignore_validate=True is blocked when record exists",
        ignore_val_blocked and count_date_8 == 1,
        f"blocked={ignore_val_blocked}, active records={count_date_8}",
    )

    # ------------------------------------------------------------------------
    # Test 9: Double Shift Behavior & Single-Doc Invariant
    # ------------------------------------------------------------------------
    print("\n-- 9. Double Shift Single-Doc Behavior " + "-" * 34)
    test_date_9 = "2026-11-09"
    cleanup_date(test_date_9)

    from valence.valence.attendance_code import get_attendance_code

    att_ds = frappe.new_doc("Attendance")
    att_ds.employee = test_emp_id
    att_ds.attendance_date = test_date_9
    att_ds.status = "Present"
    att_ds.in_time = "2026-11-09 06:00:00"
    att_ds.out_time = "2026-11-09 22:00:00"
    att_ds.working_hours = 16.0
    att_ds.shift = shift_a
    att_ds.insert(ignore_permissions=True)
    att_ds.submit()
    att_ds.reload()

    code = get_attendance_code(att_ds.as_dict())
    ds_code_valid = code == "2P"

    # Second document for the second shift must be blocked
    ds_second_blocked = False
    try:
        att_ds_2 = frappe.new_doc("Attendance")
        att_ds_2.employee = test_emp_id
        att_ds_2.attendance_date = test_date_9
        att_ds_2.status = "Present"
        att_ds_2.working_hours = 8.0
        att_ds_2.shift = shift_b
        att_ds_2.insert(ignore_permissions=True)
    except DuplicateAttendanceError:
        ds_second_blocked = True
    except Exception as e:
        if "Duplicate" in str(e):
            ds_second_blocked = True

    count_date_9 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_9, "docstatus": ["<", 2]},
    )
    log_result(
        "Double shift is represented by a single record (2P) and rejects second shift document",
        ds_code_valid and ds_second_blocked and count_date_9 == 1,
        f"code={code}, blocked={ds_second_blocked}, active records={count_date_9}",
    )

    # ------------------------------------------------------------------------
    # Test 10: Attendance Request Concurrent Insertion Race Recovery
    # ------------------------------------------------------------------------
    print("\n-- 10. Attendance Request Concurrent Insert Recovery " + "-" * 19)
    test_date_10 = "2026-11-10"
    cleanup_date(test_date_10)

    # Pre-create an attendance on test_date_10 with status "No punch"
    att_race_pre = frappe.new_doc("Attendance")
    att_race_pre.employee = test_emp_id
    att_race_pre.attendance_date = test_date_10
    att_race_pre.status = "No punch"
    att_race_pre.insert(ignore_permissions=True)
    att_race_pre.submit()
    frappe.db.commit()

    # Instantiate Attendance Request for test_date_10
    ar_race = frappe.new_doc("Attendance Request")
    ar_race.employee = test_emp_id
    ar_race.from_date = test_date_10
    ar_race.to_date = test_date_10
    ar_race.reason = "Work From Home"
    ar_race.shift = shift_b
    ar_race.include_holidays = 1
    ar_race.explanation = "Race condition test"
    ar_race.flags.ignore_permissions = True
    ar_race.insert()
    frappe.db.commit()

    # Simulate race condition: initial get_attendance_doc returns None (as if another process
    # created attendance concurrently between lookup and insert).
    # Then new_doc.insert() encounters DuplicateAttendanceError and recovers safely.
    first_lookup = [True]
    from unittest.mock import patch
    from valence.valence.override.attendance_request import AttendanceRequest as ValenceAR
    orig_get_attendance_doc = ValenceAR.get_attendance_doc

    def race_get_attendance_doc(self, date):
        if first_lookup[0]:
            first_lookup[0] = False
            return None
        return orig_get_attendance_doc(self, date)

    race_success = True
    try:
        with patch.object(ValenceAR, "get_attendance_doc", race_get_attendance_doc):
            ar_race.submit()
    except Exception as e:
        race_success = False

    count_date_10 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_10, "docstatus": ["<", 2]},
    )
    att_race_pre.reload()
    ar_docstatus = frappe.db.get_value("Attendance Request", ar_race.name, "docstatus")

    log_result(
        "Attendance Request recovers from concurrent insert race without failing or duplicating",
        race_success and ar_docstatus == 1 and count_date_10 == 1 and att_race_pre.status == "Work From Home" and att_race_pre.attendance_request == ar_race.name,
        f"success={race_success}, ar_docstatus={ar_docstatus}, active records={count_date_10}, status={att_race_pre.status}",
    )
    try:
        ar_race.cancel()
        frappe.db.delete("Attendance Request", {"name": ar_race.name})
    except Exception:
        pass
    frappe.db.commit()

    # ------------------------------------------------------------------------
    # Test 11: True Multi-Threaded Concurrent Insert Test (Two DB Connections)
    # ------------------------------------------------------------------------
    print("\n-- 11. True Multi-Threaded Concurrent Insert Test " + "-" * 20)
    import threading
    test_date_11 = "2026-09-05"
    cleanup_date(test_date_11)
    frappe.db.commit()

    site_name = frappe.local.site
    sites_path = getattr(frappe.local, "sites_path", None)
    thread_results = []
    barrier = threading.Barrier(2)

    def thread_worker(th_id, shift_name):
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 15")
            barrier.wait(timeout=10)

            # Consistent row-locking pattern on employee
            from valence.valence.override.attendance import lock_employee
            lock_employee(test_emp_id)

            existing = frappe.db.get_value(
                "Attendance",
                {"employee": test_emp_id, "attendance_date": test_date_11, "docstatus": ["<", 2]},
                "name",
            )
            if existing:
                frappe.db.rollback()
                thread_results.append((th_id, "SKIPPED_EXISTING", existing))
                return

            att = frappe.new_doc("Attendance")
            att.employee = test_emp_id
            att.attendance_date = test_date_11
            att.shift = shift_name
            att.status = "Present"
            att.insert(ignore_permissions=True)
            att.submit()
            frappe.db.commit()
            thread_results.append((th_id, "SUCCESS", att.name))
        except (DuplicateAttendanceError, frappe.QueryDeadlockError, frappe.QueryTimeoutError) as e:
            try:
                frappe.db.rollback()
            except Exception:
                pass
            thread_results.append((th_id, "BLOCKED", type(e).__name__))
        except Exception as e:
            try:
                frappe.db.rollback()
            except Exception:
                pass
            thread_results.append((th_id, "ERROR", f"{type(e).__name__}: {e}"))
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    t1 = threading.Thread(target=thread_worker, args=(1, shift_a))
    t2 = threading.Thread(target=thread_worker, args=(2, shift_b))

    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    count_date_11 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_11, "docstatus": ["<", 2]},
    )
    statuses = [r[1] for r in thread_results]
    one_succeeded = statuses.count("SUCCESS") == 1
    competing_handled_safely = ("SKIPPED_EXISTING" in statuses) or ("BLOCKED" in statuses)
    no_unexpected_errors = statuses.count("ERROR") == 0
    exactly_one_record = count_date_11 == 1

    log_result(
        "True concurrent multi-connection insert: exactly one succeeds, competing operation handled safely, exactly one record remains",
        exactly_one_record and one_succeeded and competing_handled_safely and no_unexpected_errors,
        f"count={count_date_11}, results={thread_results}",
    )

    # ------------------------------------------------------------------------
    # Test 12: Attendance Rebuild Comprehensive Safety Matrix
    # ------------------------------------------------------------------------
    print("\n-- 12. Attendance Rebuild Comprehensive Safety Matrix " + "-" * 17)
    rebuild_safety_passed = True
    rebuild_safety_details = []

    matrix = [
        # (Status, LeaveApp, AttReq, ShouldBeProtected, Description)
        ("Present", False, False, False, "Present without leave/req is eligible for checkin recalculation"),
        ("Half Day", False, False, False, "Half Day worked without leave is eligible for recalculation"),
        ("Half Day", True, False, True, "Half Day with Leave Application must be protected"),
        ("On Leave", True, False, True, "On Leave must be protected"),
        ("Holiday", False, False, False, "Holiday without leave/req is preserved if no punches, eligible for recalculation if punches exist"),
        ("Weekly Off", False, False, False, "Weekly Off without leave/req is preserved if no punches, eligible for recalculation if punches exist"),
        ("Work From Home", False, True, True, "Work From Home must be protected"),
        ("On Duty", False, True, True, "On Duty must be protected"),
    ]

    from valence.valence.doc_events.attendance_rebuild import is_protected, rebuild_date

    emp_doc = frappe.get_doc("Employee", test_emp_id)

    for idx, (st, has_leave, has_req, should_protect, desc) in enumerate(matrix):
        d_str = f"2026-09-{10 + idx:02d}"
        cleanup_date(d_str)

        if st == "Holiday":
            ensure_holiday(d_str, "Test Holiday")
        elif st == "Weekly Off":
            ensure_weekly_off(d_str, "Test Weekly Off")

        rec = frappe.new_doc("Attendance")
        rec.employee = test_emp_id
        rec.attendance_date = d_str
        rec.status = st
        if has_leave:
            rec.leave_application = "TEST-LAP-001"
            rec.leave_type = leave_type
        if has_req:
            rec.attendance_request = "TEST-ARQ-001"
        rec.flags.ignore_links = True
        rec.flags.ignore_validate = True
        rec.insert(ignore_permissions=True)
        rec.submit()
        frappe.db.commit()

        prot = is_protected(rec)
        if prot != should_protect:
            rebuild_safety_passed = False
            rebuild_safety_details.append(f"{st} is_protected={prot}, expected={should_protect}")

        res = rebuild_date(emp_doc, getdate(d_str))
        rec.reload()

        if should_protect:
            expected_prefix = "Protected by" if (has_leave or has_req) else "Protected status"
            if res["action"] != "skipped" or rec.status != st or not res["note"].startswith(expected_prefix):
                rebuild_safety_passed = False
                rebuild_safety_details.append(f"{st} protection failed! action={res['action']}, status={rec.status}, note={res['note']}")
        else:
            if st in ("Holiday", "Weekly Off"):
                # When no punches exist, record must be preserved with specific note
                expected_note = f"Preserved {st} without check-ins"
                if res["action"] != "skipped" or rec.status != st or res["note"] != expected_note:
                    rebuild_safety_passed = False
                    rebuild_safety_details.append(f"{st} without punches was not preserved! action={res['action']}, status={rec.status}, note={res['note']}")
            else:
                if res["action"] not in ("updated", "skipped") or rec.status not in ("Absent", st):
                    rebuild_safety_passed = False
                    rebuild_safety_details.append(f"{st} failed eligible recalculation: action={res['action']}")

        cleanup_date(d_str)

    log_result(
        "Attendance Rebuild safety matrix: preserves protected records, updates only eligible",
        rebuild_safety_passed,
        "all 8 status variants verified" if rebuild_safety_passed else "; ".join(rebuild_safety_details),
    )

    # ------------------------------------------------------------------------
    # Test 13: Attendance Rebuild on Holiday and Weekly Off
    # ------------------------------------------------------------------------
    print("\n-- 13. Attendance Rebuild on Holiday and Weekly Off " + "-" * 20)

    # 13a: Holiday WITH valid punches -> updates to Present
    date_h_work = "2026-10-01"
    cleanup_date(date_h_work)
    ensure_holiday(date_h_work, "Gandhi Jayanti")

    att_h_work = frappe.new_doc("Attendance")
    att_h_work.employee = test_emp_id
    att_h_work.attendance_date = date_h_work
    att_h_work.status = "Holiday"
    att_h_work.working_hours = 0
    att_h_work.insert(ignore_permissions=True)
    att_h_work.submit()

    make_checkin(test_emp_id, f"{date_h_work} 09:00:00", "IN")
    make_checkin(test_emp_id, f"{date_h_work} 17:00:00", "OUT")

    res_h_work = rebuild_date(emp_doc, getdate(date_h_work))
    att_h_work.reload()
    count_h_work = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_h_work, "docstatus": ["<", 2]})

    log_result(
        "Holiday with valid punches is recalculated to Present without duplicate",
        res_h_work["action"] == "updated" and att_h_work.status == "Present" and att_h_work.working_hours == 8.0 and count_h_work == 1,
        f"action={res_h_work['action']}, status={att_h_work.status}, hours={att_h_work.working_hours}, count={count_h_work}",
    )

    # 13b: Holiday WITHOUT valid punches -> preserved as Holiday
    date_h_idle = "2026-10-02"
    cleanup_date(date_h_idle)
    ensure_holiday(date_h_idle, "National Holiday")

    att_h_idle = frappe.new_doc("Attendance")
    att_h_idle.employee = test_emp_id
    att_h_idle.attendance_date = date_h_idle
    att_h_idle.status = "Holiday"
    att_h_idle.working_hours = 0
    att_h_idle.insert(ignore_permissions=True)
    att_h_idle.submit()

    res_h_idle = rebuild_date(emp_doc, getdate(date_h_idle))
    att_h_idle.reload()
    count_h_idle = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_h_idle, "docstatus": ["<", 2]})

    log_result(
        "Holiday without punches is preserved as Holiday with specific note",
        res_h_idle["action"] == "skipped" and att_h_idle.status == "Holiday" and res_h_idle["note"] == "Preserved Holiday without check-ins" and count_h_idle == 1,
        f"action={res_h_idle['action']}, status={att_h_idle.status}, note={res_h_idle['note']}, count={count_h_idle}",
    )

    # 13c: Weekly Off WITH valid punches -> updates to Present
    date_wo_work = "2026-10-04"
    cleanup_date(date_wo_work)
    ensure_weekly_off(date_wo_work, "Sunday Off")

    att_wo_work = frappe.new_doc("Attendance")
    att_wo_work.employee = test_emp_id
    att_wo_work.attendance_date = date_wo_work
    att_wo_work.status = "Weekly Off"
    att_wo_work.working_hours = 0
    att_wo_work.insert(ignore_permissions=True)
    att_wo_work.submit()

    make_checkin(test_emp_id, f"{date_wo_work} 09:00:00", "IN")
    make_checkin(test_emp_id, f"{date_wo_work} 17:00:00", "OUT")

    res_wo_work = rebuild_date(emp_doc, getdate(date_wo_work))
    att_wo_work.reload()
    count_wo_work = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_wo_work, "docstatus": ["<", 2]})

    log_result(
        "Weekly Off with valid punches is recalculated to Present without duplicate",
        res_wo_work["action"] == "updated" and att_wo_work.status == "Present" and att_wo_work.working_hours == 8.0 and count_wo_work == 1,
        f"action={res_wo_work['action']}, status={att_wo_work.status}, hours={att_wo_work.working_hours}, count={count_wo_work}",
    )

    # 13d: Weekly Off WITHOUT valid punches -> preserved as Weekly Off
    date_wo_idle = "2026-10-11"
    cleanup_date(date_wo_idle)
    ensure_weekly_off(date_wo_idle, "Sunday Off")

    att_wo_idle = frappe.new_doc("Attendance")
    att_wo_idle.employee = test_emp_id
    att_wo_idle.attendance_date = date_wo_idle
    att_wo_idle.status = "Weekly Off"
    att_wo_idle.working_hours = 0
    att_wo_idle.insert(ignore_permissions=True)
    att_wo_idle.submit()

    res_wo_idle = rebuild_date(emp_doc, getdate(date_wo_idle))
    att_wo_idle.reload()
    count_wo_idle = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_wo_idle, "docstatus": ["<", 2]})

    log_result(
        "Weekly Off without punches is preserved as Weekly Off with specific note",
        res_wo_idle["action"] == "skipped" and att_wo_idle.status == "Weekly Off" and res_wo_idle["note"] == "Preserved Weekly Off without check-ins" and count_wo_idle == 1,
        f"action={res_wo_idle['action']}, status={att_wo_idle.status}, note={res_wo_idle['note']}, count={count_wo_idle}",
    )

    cleanup_date(date_h_work)
    cleanup_date(date_h_idle)
    cleanup_date(date_wo_work)
    cleanup_date(date_wo_idle)

    # ------------------------------------------------------------------------
    # Test 14: Safe Lock Timeout and Deadlock Handling
    # ------------------------------------------------------------------------
    print("\n-- 14. Safe Lock Timeout and Deadlock Handling " + "-" * 30)

    # 14a: Lock wait timeout on rebuild_date
    date_timeout = "2026-09-25"
    cleanup_date(date_timeout)
    frappe.db.commit()

    lock_holder_barrier = threading.Barrier(2)
    timeout_results = {}

    def lock_holder():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 10")
            frappe.db.sql("SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE", (test_emp_id,))
            lock_holder_barrier.wait(timeout=5)
            import time
            time.sleep(3)
            frappe.db.rollback()
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    def timeout_worker():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            lock_holder_barrier.wait(timeout=5)
            import time
            time.sleep(0.5)

            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 1")
            emp_d = frappe.get_doc("Employee", test_emp_id)
            res = rebuild_date(emp_d, getdate(date_timeout))
            timeout_results["res"] = res
            timeout_results["success"] = True
        except Exception as e:
            timeout_results["error"] = type(e).__name__
            timeout_results["success"] = False
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    th_holder = threading.Thread(target=lock_holder)
    th_worker = threading.Thread(target=timeout_worker)

    th_holder.start()
    th_worker.start()
    th_holder.join(timeout=15)
    th_worker.join(timeout=15)

    res_timeout = timeout_results.get("res", {})
    timeout_handled_safely = (
        timeout_results.get("success", False)
        and res_timeout.get("action") == "skipped"
        and "lock wait timeout" in res_timeout.get("note", "").lower()
    )

    count_date_timeout = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_timeout, "docstatus": ["<", 2]})

    log_result(
        "Lock wait timeout in rebuild_date is handled safely without crashing or corrupting data",
        timeout_handled_safely and count_date_timeout == 0,
        f"handled={timeout_handled_safely}, note={res_timeout.get('note')}, count={count_date_timeout}",
    )
    cleanup_date(date_timeout)
    frappe.db.commit()

    # 14b: lock_employee raises QueryTimeoutError on lock wait timeout
    lock_employee_timeout_barrier = threading.Barrier(2)
    le_timeout_results = {}

    def lock_holder_for_le():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 10")
            frappe.db.sql("SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE", (test_emp_id,))
            lock_employee_timeout_barrier.wait(timeout=5)
            import time
            time.sleep(3)
            frappe.db.rollback()
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    def le_timeout_worker():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            lock_employee_timeout_barrier.wait(timeout=5)
            import time
            time.sleep(0.5)

            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 1")
            from valence.valence.override.attendance import lock_employee
            lock_employee(test_emp_id)
            le_timeout_results["raised"] = None
        except frappe.QueryTimeoutError as e:
            le_timeout_results["raised"] = "QueryTimeoutError"
            le_timeout_results["msg"] = str(e)
        except Exception as e:
            le_timeout_results["raised"] = type(e).__name__
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    th_h_le = threading.Thread(target=lock_holder_for_le)
    th_w_le = threading.Thread(target=le_timeout_worker)
    th_h_le.start()
    th_w_le.start()
    th_h_le.join(timeout=15)
    th_w_le.join(timeout=15)

    log_result(
        "lock_employee raises QueryTimeoutError on lock wait timeout",
        le_timeout_results.get("raised") == "QueryTimeoutError",
        f"raised={le_timeout_results.get('raised')}",
    )
    frappe.db.commit()

    # 14c: lock_employee raises QueryDeadlockError on deadlock (not miscast as QueryTimeoutError)
    from unittest.mock import patch
    from valence.valence.override.attendance import lock_employee

    deadlock_raised = None
    deadlock_msg = ""
    try:
        with patch("frappe.db.sql", side_effect=frappe.QueryDeadlockError("1213", "Deadlock")):
            lock_employee(test_emp_id)
    except frappe.QueryDeadlockError as e:
        deadlock_raised = "QueryDeadlockError"
        deadlock_msg = str(e)
    except Exception as e:
        deadlock_raised = type(e).__name__

    log_result(
        "lock_employee raises QueryDeadlockError on deadlock (not miscast as QueryTimeoutError)",
        deadlock_raised == "QueryDeadlockError" and "deadlock" in deadlock_msg.lower(),
        f"raised={deadlock_raised}, message={deadlock_msg[:60]}",
    )
    frappe.db.commit()

    # 14d: Attendance Request submit() rolls back and raises QueryDeadlockError on employee lock deadlock
    date_ar_dl = "2026-09-28"
    cleanup_date(date_ar_dl)

    att_dl_pre = frappe.new_doc("Attendance")
    att_dl_pre.employee = test_emp_id
    att_dl_pre.attendance_date = date_ar_dl
    att_dl_pre.status = "Present"
    att_dl_pre.insert(ignore_permissions=True)
    att_dl_pre.submit()
    frappe.db.commit()

    ar_dl = frappe.new_doc("Attendance Request")
    ar_dl.employee = test_emp_id
    ar_dl.from_date = date_ar_dl
    ar_dl.to_date = date_ar_dl
    ar_dl.reason = "Work From Home"
    ar_dl.explanation = "Deadlock test"
    ar_dl.include_holidays = 1
    ar_dl.flags.ignore_permissions = True
    ar_dl.insert()
    frappe.db.commit()

    orig_sql = frappe.db.sql
    def mock_sql_deadlock(query, *args, **kwargs):
        if isinstance(query, str) and "SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE" in query:
            raise frappe.QueryDeadlockError("1213", "Deadlock found when trying to get lock")
        return orig_sql(query, *args, **kwargs)

    ar_dl_raised = None
    try:
        with patch("frappe.db.sql", side_effect=mock_sql_deadlock):
            ar_dl.submit()
    except frappe.QueryDeadlockError:
        ar_dl_raised = "QueryDeadlockError"
    except Exception as e:
        ar_dl_raised = type(e).__name__

    ar_dl_docstatus = frappe.db.get_value("Attendance Request", ar_dl.name, "docstatus")
    att_dl_pre.reload()
    count_ar_dl = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_ar_dl, "docstatus": ["<", 2]})

    log_result(
        "Attendance Request submit() rolls back and raises QueryDeadlockError on employee lock deadlock",
        ar_dl_raised == "QueryDeadlockError" and ar_dl_docstatus == 0 and att_dl_pre.status == "No punch" and not att_dl_pre.attendance_request and count_ar_dl == 1,
        f"raised={ar_dl_raised}, ar_docstatus={ar_dl_docstatus}, att_status={att_dl_pre.status}, count={count_ar_dl}",
    )
    cleanup_date(date_ar_dl)
    try:
        frappe.db.delete("Attendance Request", {"name": ar_dl.name})
    except Exception:
        pass
    frappe.db.commit()

    # 14e: Attendance Request submit() rolls back and raises QueryTimeoutError on lock wait timeout
    date_ar_to = "2026-09-29"
    cleanup_date(date_ar_to)

    att_to_pre = frappe.new_doc("Attendance")
    att_to_pre.employee = test_emp_id
    att_to_pre.attendance_date = date_ar_to
    att_to_pre.status = "Present"
    att_to_pre.insert(ignore_permissions=True)
    att_to_pre.submit()
    frappe.db.commit()

    ar_to = frappe.new_doc("Attendance Request")
    ar_to.employee = test_emp_id
    ar_to.from_date = date_ar_to
    ar_to.to_date = date_ar_to
    ar_to.reason = "Work From Home"
    ar_to.explanation = "Timeout test"
    ar_to.include_holidays = 1
    ar_to.flags.ignore_permissions = True
    ar_to.insert()
    frappe.db.commit()

    def mock_sql_timeout(query, *args, **kwargs):
        if isinstance(query, str) and "SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE" in query:
            raise frappe.QueryTimeoutError("1205", "Lock wait timeout exceeded")
        return orig_sql(query, *args, **kwargs)

    ar_to_raised = None
    try:
        with patch("frappe.db.sql", side_effect=mock_sql_timeout):
            ar_to.submit()
    except frappe.QueryTimeoutError:
        ar_to_raised = "QueryTimeoutError"
    except Exception as e:
        ar_to_raised = type(e).__name__

    ar_to_docstatus = frappe.db.get_value("Attendance Request", ar_to.name, "docstatus")
    att_to_pre.reload()
    count_ar_to = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_ar_to, "docstatus": ["<", 2]})

    log_result(
        "Attendance Request submit() rolls back and raises QueryTimeoutError on lock wait timeout",
        ar_to_raised == "QueryTimeoutError" and ar_to_docstatus == 0 and att_to_pre.status == "No punch" and not att_to_pre.attendance_request and count_ar_to == 1,
        f"raised={ar_to_raised}, ar_docstatus={ar_to_docstatus}, att_status={att_to_pre.status}, count={count_ar_to}",
    )
    cleanup_date(date_ar_to)
    try:
        frappe.db.delete("Attendance Request", {"name": ar_to.name})
    except Exception:
        pass
    frappe.db.commit()

    # 14f: Attendance Request submit() rolls back and raises QueryDeadlockError on attendance insertion deadlock
    date_ar_ins_dl = "2026-09-30"
    cleanup_date(date_ar_ins_dl)

    ar_ins_dl = frappe.new_doc("Attendance Request")
    ar_ins_dl.employee = test_emp_id
    ar_ins_dl.from_date = date_ar_ins_dl
    ar_ins_dl.to_date = date_ar_ins_dl
    ar_ins_dl.reason = "Work From Home"
    ar_ins_dl.explanation = "Insert deadlock test"
    ar_ins_dl.include_holidays = 1
    ar_ins_dl.flags.ignore_permissions = True
    ar_ins_dl.insert()
    frappe.db.commit()

    def mock_insert_deadlock(doc_self, *args, **kwargs):
        raise frappe.QueryDeadlockError("1213", "Deadlock on attendance insert")

    ar_ins_dl_raised = None
    try:
        with patch("hrms.hr.doctype.attendance.attendance.Attendance.insert", mock_insert_deadlock):
            ar_ins_dl.submit()
    except frappe.QueryDeadlockError:
        ar_ins_dl_raised = "QueryDeadlockError"
    except Exception as e:
        ar_ins_dl_raised = type(e).__name__

    ar_ins_dl_docstatus = frappe.db.get_value("Attendance Request", ar_ins_dl.name, "docstatus")
    count_ar_ins_dl = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_ar_ins_dl, "docstatus": ["<", 2]})

    log_result(
        "Attendance Request submit() rolls back and raises QueryDeadlockError on attendance insert deadlock",
        ar_ins_dl_raised == "QueryDeadlockError" and ar_ins_dl_docstatus == 0 and count_ar_ins_dl == 0,
        f"raised={ar_ins_dl_raised}, ar_docstatus={ar_ins_dl_docstatus}, count={count_ar_ins_dl}",
    )
    cleanup_date(date_ar_ins_dl)
    try:
        frappe.db.delete("Attendance Request", {"name": ar_ins_dl.name})
    except Exception:
        pass
    frappe.db.commit()

    # 14g: Attendance Request submit() rolls back and raises QueryTimeoutError on attendance insertion timeout
    date_ar_ins_to = "2026-10-01"
    cleanup_date(date_ar_ins_to)

    ar_ins_to = frappe.new_doc("Attendance Request")
    ar_ins_to.employee = test_emp_id
    ar_ins_to.from_date = date_ar_ins_to
    ar_ins_to.to_date = date_ar_ins_to
    ar_ins_to.reason = "Work From Home"
    ar_ins_to.explanation = "Insert timeout test"
    ar_ins_to.include_holidays = 1
    ar_ins_to.flags.ignore_permissions = True
    ar_ins_to.insert()
    frappe.db.commit()

    def mock_insert_timeout(doc_self, *args, **kwargs):
        raise frappe.QueryTimeoutError("1205", "Lock wait timeout on attendance insert")

    ar_ins_to_raised = None
    try:
        with patch("hrms.hr.doctype.attendance.attendance.Attendance.insert", mock_insert_timeout):
            ar_ins_to.submit()
    except frappe.QueryTimeoutError:
        ar_ins_to_raised = "QueryTimeoutError"
    except Exception as e:
        ar_ins_to_raised = type(e).__name__

    ar_ins_to_docstatus = frappe.db.get_value("Attendance Request", ar_ins_to.name, "docstatus")
    count_ar_ins_to = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_ar_ins_to, "docstatus": ["<", 2]})

    log_result(
        "Attendance Request submit() rolls back and raises QueryTimeoutError on attendance insert lock timeout",
        ar_ins_to_raised == "QueryTimeoutError" and ar_ins_to_docstatus == 0 and count_ar_ins_to == 0,
        f"raised={ar_ins_to_raised}, ar_docstatus={ar_ins_to_docstatus}, count={count_ar_ins_to}",
    )
    cleanup_date(date_ar_ins_to)
    try:
        frappe.db.delete("Attendance Request", {"name": ar_ins_to.name})
    except Exception:
        pass
    # 14h: Atomic batch contract: mark_absent does not prematurely commit caller's pending changes
    date_st_pending = "2026-11-20"
    cleanup_date(date_st_pending)
    frappe.db.commit()

    orig_middle_14h = frappe.db.get_value("Employee", test_emp_id, "middle_name")

    # Caller makes an uncommitted pending change in current transaction
    frappe.db.set_value("Employee", test_emp_id, "middle_name", "UncommittedMiddle", update_modified=False)

    # In a separate connection, verify the change is NOT committed yet
    committed_in_other_conn = []
    def check_other_conn():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            val = frappe.db.get_value("Employee", test_emp_id, "middle_name")
            committed_in_other_conn.append(val)
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    t = threading.Thread(target=check_other_conn)
    t.start()
    t.join(timeout=10)

    st_obj = frappe.get_doc("Shift Type", shift_a)
    with patch.object(st_obj, "get_dates_for_attendance", return_value=[date_st_pending]):
        with patch("valence.api.get_applicable_shift", return_value=shift_a):
            with patch("valence.api.get_day_type", return_value="Absent"):
                st_obj.mark_absent_for_dates_with_no_attendance(test_emp_id)

    # In a separate connection, verify it is STILL NOT committed (mark_absent did NOT call commit!)
    committed_after_mark = []
    def check_other_conn_after():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            val = frappe.db.get_value("Employee", test_emp_id, "middle_name")
            committed_after_mark.append(val)
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    t2 = threading.Thread(target=check_other_conn_after)
    t2.start()
    t2.join(timeout=10)

    # Clean rollback by caller before logging result
    frappe.db.rollback()
    restored_val = frappe.db.get_value("Employee", test_emp_id, "middle_name")

    not_committed_prematurely = (
        committed_in_other_conn == [orig_middle_14h]
        and committed_after_mark == [orig_middle_14h]
        and restored_val == orig_middle_14h
    )

    log_result(
        "ShiftType mark_absent respects caller transaction: does not commit caller pending changes prematurely",
        not_committed_prematurely,
        f"before={committed_in_other_conn}, after={committed_after_mark}, restored={restored_val}",
    )
    cleanup_date(date_st_pending)
    frappe.db.commit()

    # 14i: Atomic batch contract: already-marked date does not roll back caller's pending work
    date_st_exist = "2026-11-21"
    cleanup_date(date_st_exist)
    att_existing = frappe.new_doc("Attendance")
    att_existing.employee = test_emp_id
    att_existing.attendance_date = date_st_exist
    att_existing.status = "Present"
    att_existing.insert(ignore_permissions=True)
    att_existing.submit()
    frappe.db.commit()

    # Capture original middle_name before modifying
    orig_middle_14i = frappe.db.get_value("Employee", test_emp_id, "middle_name")

    # Caller makes pending change in current transaction
    test_pending_val = "KeepMePending"
    frappe.db.set_value("Employee", test_emp_id, "middle_name", test_pending_val, update_modified=False)

    # Verify from independent connection that pending change is NOT committed before mark_absent
    conn_before_14i = []
    def check_conn_before_14i():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            conn_before_14i.append(frappe.db.get_value("Employee", test_emp_id, "middle_name"))
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    tb = threading.Thread(target=check_conn_before_14i)
    tb.start()
    tb.join(timeout=10)

    # Invoke mark_absent for the already-marked date
    with patch.object(st_obj, "get_dates_for_attendance", return_value=[date_st_exist]):
        with patch("valence.api.get_applicable_shift", return_value=shift_a):
            st_obj.mark_absent_for_dates_with_no_attendance(test_emp_id)

    # Verify from independent connection that pending change is STILL NOT committed after mark_absent
    conn_after_14i = []
    def check_conn_after_14i():
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            conn_after_14i.append(frappe.db.get_value("Employee", test_emp_id, "middle_name"))
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    ta = threading.Thread(target=check_conn_after_14i)
    ta.start()
    ta.join(timeout=10)

    # Verify caller's pending change was NOT rolled back by the already-marked date check in current transaction
    pending_held = frappe.db.get_value("Employee", test_emp_id, "middle_name") == test_pending_val

    # Roll back the caller's pending change BEFORE calling log_result()
    frappe.db.rollback()

    # Verify that original value is restored and that test never leaves KeepMePending in DB
    restored_middle_14i = frappe.db.get_value("Employee", test_emp_id, "middle_name")
    is_restored_14i = restored_middle_14i == orig_middle_14i

    passed_14i = (
        conn_before_14i == [orig_middle_14i]
        and conn_after_14i == [orig_middle_14i]
        and pending_held
        and is_restored_14i
    )

    log_result(
        "ShiftType mark_absent: already-marked date does not roll back caller pending work",
        passed_14i,
        f"conn_before={conn_before_14i}, conn_after={conn_after_14i}, pending_held={pending_held}, restored={restored_middle_14i}",
    )
    cleanup_date(date_st_exist)
    frappe.db.commit()

    # 14j: Atomic batch error propagation: deadlock on later date halts processing and enables clean batch rollback
    date_st_1 = "2026-11-22"
    date_st_2 = "2026-11-23"
    date_st_3 = "2026-11-24"
    cleanup_date(date_st_1)
    cleanup_date(date_st_2)
    cleanup_date(date_st_3)
    frappe.db.commit()

    import hrms.hr.doctype.attendance.attendance as att_module
    orig_mark_att = att_module.mark_attendance

    def mock_mark_att_deadlock(employee, date, status, shift):
        if str(date) == date_st_2:
            raise frappe.QueryDeadlockError("1213", "Deadlock on second date")
        return orig_mark_att(employee, date, status, shift)

    st_dl_raised = None

    with patch.object(st_obj, "get_dates_for_attendance", return_value=[date_st_1, date_st_2, date_st_3]):
        with patch("valence.api.get_applicable_shift", return_value=shift_a):
            with patch("valence.api.get_day_type", return_value="Absent"):
                with patch("valence.valence.override.shift_type.mark_attendance", side_effect=mock_mark_att_deadlock):
                    try:
                        st_obj.mark_absent_for_dates_with_no_attendance(test_emp_id)
                    except frappe.QueryDeadlockError:
                        st_dl_raised = "QueryDeadlockError"
                        # Outer transaction handler rolls back the entire atomic batch
                        frappe.db.rollback()
                    except Exception as e:
                        st_dl_raised = type(e).__name__
                        frappe.db.rollback()

    count_st_1 = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_st_1, "docstatus": ["<", 2]})
    count_st_2 = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_st_2, "docstatus": ["<", 2]})
    count_st_3 = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_st_3, "docstatus": ["<", 2]})

    log_result(
        "ShiftType mark_absent: deadlock on later date halts processing and enables clean atomic batch rollback",
        st_dl_raised == "QueryDeadlockError" and count_st_1 == 0 and count_st_2 == 0 and count_st_3 == 0,
        f"raised={st_dl_raised}, date1={count_st_1}, date2={count_st_2}, date3={count_st_3}",
    )
    cleanup_date(date_st_1)
    cleanup_date(date_st_2)
    cleanup_date(date_st_3)
    frappe.db.commit()

    # 14k: Atomic batch lock failure: raises QueryTimeoutError (does not return silently)
    date_st_to = "2026-11-25"
    cleanup_date(date_st_to)
    frappe.db.commit()

    st_lock_raised = None
    with patch.object(st_obj, "get_dates_for_attendance", return_value=[date_st_to]):
        with patch("valence.api.get_applicable_shift", return_value=shift_a):
            with patch("valence.valence.override.attendance.lock_employee", side_effect=frappe.QueryTimeoutError("1205", "Lock wait timeout")):
                try:
                    st_obj.mark_absent_for_dates_with_no_attendance(test_emp_id)
                except frappe.QueryTimeoutError:
                    st_lock_raised = "QueryTimeoutError"
                except Exception as e:
                    st_lock_raised = type(e).__name__

    count_st_to = frappe.db.count("Attendance", {"employee": test_emp_id, "attendance_date": date_st_to, "docstatus": ["<", 2]})

    log_result(
        "ShiftType mark_absent raises QueryTimeoutError on lock acquisition failure instead of returning silently",
        st_lock_raised == "QueryTimeoutError" and count_st_to == 0,
        f"raised={st_lock_raised}, count={count_st_to}",
    )
    cleanup_date(date_st_to)
    frappe.db.commit()

    # ------------------------------------------------------------------------
    # Test 15: Holiday List Entry Isolation and Cleanup on Failure
    # ------------------------------------------------------------------------
    print("\n-- 15. Holiday List Isolation and Failure Cleanup " + "-" * 26)

    # 15a: Pre-existing Holiday and Weekly Off entries survive test cleanup,
    # while test-created entries are removed.
    date_pre_h = "2026-12-24"
    date_pre_wo = "2026-12-25"
    date_test_h = "2026-12-26"
    date_test_wo = "2026-12-27"

    # Pre-populate pre-existing entries directly in Holiday List (simulating existing organization holidays)
    frappe.db.delete("Holiday", {"parent": hl_name, "holiday_date": ("in", [date_pre_h, date_pre_wo, date_test_h, date_test_wo])})
    hl_doc = frappe.get_doc("Holiday List", hl_name)
    hl_doc.append("holidays", {"holiday_date": date_pre_h, "description": "Pre-existing Holiday", "weekly_off": 0})
    hl_doc.append("holidays", {"holiday_date": date_pre_wo, "description": "Pre-existing Weekly Off", "weekly_off": 1})
    hl_doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Calling ensure_holiday / ensure_weekly_off on pre-existing entries must NOT add them to created_holiday_dates
    ensure_holiday(date_pre_h, "Pre-existing Holiday")
    ensure_weekly_off(date_pre_wo, "Pre-existing Weekly Off")

    pre_not_tracked = (date_pre_h not in created_holiday_dates) and (date_pre_wo not in created_holiday_dates)

    # Calling ensure_holiday / ensure_weekly_off on new dates MUST add them to created_holiday_dates
    ensure_holiday(date_test_h, "Test Created Holiday")
    ensure_weekly_off(date_test_wo, "Test Created Weekly Off")

    test_tracked = (date_test_h in created_holiday_dates) and (date_test_wo in created_holiday_dates)

    # Perform cleanup of the test-created dates
    cleanup_date(date_test_h)
    cleanup_date(date_test_wo)

    # Verify: test entries are deleted, pre-existing entries survived intact
    test_h_deleted = not frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_test_h})
    test_wo_deleted = not frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_test_wo})
    pre_h_survived = bool(frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_pre_h, "description": "Pre-existing Holiday"}))
    pre_wo_survived = bool(frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_pre_wo, "description": "Pre-existing Weekly Off"}))

    test_15a_passed = pre_not_tracked and test_tracked and test_h_deleted and test_wo_deleted and pre_h_survived and pre_wo_survived

    log_result(
        "Pre-existing Holiday and Weekly Off survive test cleanup while test-created entries are removed",
        test_15a_passed,
        f"pre_not_tracked={pre_not_tracked}, test_tracked={test_tracked}, test_deleted={test_h_deleted and test_wo_deleted}, pre_survived={pre_h_survived and pre_wo_survived}",
    )

    # 15b: Cleanup behavior if a test fails midway
    date_fail_test = "2026-12-28"
    fail_test_caught = False
    fail_tracked = False
    try:
        ensure_holiday(date_fail_test, "Failing Test Holiday")
        fail_tracked = date_fail_test in created_holiday_dates
        raise ValueError("Simulated unexpected test failure midway")
    except ValueError:
        fail_test_caught = True
    finally:
        cleanup_date(date_fail_test)

    fail_h_cleaned = not frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_fail_test})
    pre_h_still_exists = bool(frappe.db.exists("Holiday", {"parent": hl_name, "holiday_date": date_pre_h}))

    test_15b_passed = fail_test_caught and fail_tracked and fail_h_cleaned and pre_h_still_exists

    log_result(
        "Holiday cleanup runs reliably when a test fails midway without leaving orphan entries",
        test_15b_passed,
        f"caught={fail_test_caught}, tracked={fail_tracked}, cleaned={fail_h_cleaned}, pre_survived={pre_h_still_exists}",
    )

    # Teardown temporary pre-existing fixture entries so the holiday list remains clean
    frappe.db.delete("Holiday", {"parent": hl_name, "holiday_date": ("in", [date_pre_h, date_pre_wo])})
    frappe.db.commit()

    # Clean up all test dates and temporary holiday entries
    matrix_dates = [f"2026-09-{10 + i:02d}" for i in range(8)]
    extra_dates = [
        "2026-09-25", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-11",
        date_pre_h, date_pre_wo, date_test_h, date_test_wo, date_fail_test,
    ]
    all_test_dates = [
        test_date_1, test_date_2, test_date_3, test_date_4, test_date_5, test_date_6,
        test_date_8, test_date_9, test_date_10, test_date_11,
        date_ar_dl, date_ar_to, date_ar_ins_dl, date_ar_ins_to,
        date_st_pending, date_st_exist, date_st_1, date_st_2, date_st_3, date_st_to,
    ] + matrix_dates + extra_dates

    for d in all_test_dates:
        cleanup_date(d)

    cleanup_all_created_holidays()
    frappe.db.sql("UPDATE tabEmployee SET middle_name=NULL WHERE first_name='Duplicate' AND last_name='TestEmp'")
    frappe.db.commit()

    # ------------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------------
    total = len(results)
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = total - passed

    print("\n" + "=" * 76)
    print(f"TOTAL: {total} | PASSED: {passed} | FAILED: {failed}")
    print("=" * 76)

    return {"total": total, "passed": passed, "failed": failed, "results": results}


def verify_cleanliness():
    pending_employees = frappe.get_all("Employee", filters={"first_name": "Duplicate", "last_name": "TestEmp", "middle_name": ["is", "set"]}, fields=["name", "middle_name"])
    holidays = frappe.get_all("Holiday", filters={"parent": "TEST-DUP-HOLIDAY-LIST"}, fields=["name", "holiday_date", "description"])
    print(f"VERIFY_CLEANLINESS: pending_employees={pending_employees}, holidays_count={len(holidays)}, holidays={holidays}")
    return {"pending_employees": pending_employees, "holidays_count": len(holidays), "holidays": holidays}
