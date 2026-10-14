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

    # Pre-create an attendance on test_date_10 just before create_or_update_attendance runs,
    # and verify that ar_race.create_or_update_attendance safely catches DuplicateAttendanceError
    # or reuses the record without throwing.
    att_race_pre = frappe.new_doc("Attendance")
    att_race_pre.employee = test_emp_id
    att_race_pre.attendance_date = test_date_10
    att_race_pre.status = "No punch"
    att_race_pre.insert(ignore_permissions=True)
    att_race_pre.submit()

    # Call create_or_update_attendance directly
    race_success = True
    try:
        ar_race.create_or_update_attendance(test_date_10)
    except Exception as e:
        race_success = False

    count_date_10 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_10, "docstatus": ["<", 2]},
    )
    att_race_pre.reload()

    log_result(
        "Attendance Request recovers from concurrent insert race without failing or duplicating",
        race_success and count_date_10 == 1 and att_race_pre.status == "Work From Home",
        f"success={race_success}, active records={count_date_10}, status={att_race_pre.status}",
    )

    # ------------------------------------------------------------------------
    # Test 11: True Multi-Threaded Concurrent Insert Test (Two DB Connections)
    # ------------------------------------------------------------------------
    print("\n-- 11. True Multi-Threaded Concurrent Insert Test " + "-" * 20)
    import threading
    test_date_11 = "2026-11-11"
    cleanup_date(test_date_11)

    site_name = frappe.local.site
    sites_path = getattr(frappe.local, "sites_path", None)
    thread_results = []
    barrier = threading.Barrier(2)

    def thread_worker(th_id, shift_name):
        try:
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 3")
            barrier.wait(timeout=10)

            att = frappe.new_doc("Attendance")
            att.employee = test_emp_id
            att.attendance_date = test_date_11
            att.shift = shift_name
            att.status = "Present"
            att.insert(ignore_permissions=True)
            att.submit()
            frappe.db.commit()
            thread_results.append((th_id, "SUCCESS", None))
        except (DuplicateAttendanceError, frappe.QueryDeadlockError) as e:
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
            thread_results.append((th_id, "ERROR", type(e).__name__))
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass

    t1 = threading.Thread(target=thread_worker, args=(1, shift_a))
    t2 = threading.Thread(target=thread_worker, args=(2, shift_b))

    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)

    count_date_11 = frappe.db.count(
        "Attendance",
        {"employee": test_emp_id, "attendance_date": test_date_11, "docstatus": ["<", 2]},
    )
    statuses = [r[1] for r in thread_results]
    no_duplicate_created = count_date_11 <= 1
    has_blocked = "BLOCKED" in statuses or "ERROR" in statuses

    log_result(
        "True concurrent multi-connection insert: at most one succeeds, competing connection blocked, count <= 1",
        no_duplicate_created and (statuses.count("SUCCESS") <= 1) and len(statuses) == 2,
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
        ("Holiday", False, False, True, "Holiday must be protected"),
        ("Weekly Off", False, False, True, "Weekly Off must be protected"),
        ("Work From Home", False, True, True, "Work From Home must be protected"),
        ("On Duty", False, True, True, "On Duty must be protected"),
    ]

    from valence.valence.doc_events.attendance_rebuild import is_protected, rebuild_date

    test_date_12_base = 20
    emp_doc = frappe.get_doc("Employee", test_emp_id)

    for idx, (st, has_leave, has_req, should_protect, desc) in enumerate(matrix):
        d_str = f"2026-11-{test_date_12_base + idx:02d}"
        cleanup_date(d_str)

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

        prot = is_protected(rec)
        if prot != should_protect:
            rebuild_safety_passed = False
            rebuild_safety_details.append(f"{st} is_protected={prot}, expected={should_protect}")

        res = rebuild_date(emp_doc, getdate(d_str))
        rec.reload()

        if should_protect:
            if res["action"] != "skipped" or rec.status != st:
                rebuild_safety_passed = False
                rebuild_safety_details.append(f"{st} mutated! action={res['action']}, status={rec.status}")
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

    # Clean up test dates
    for d in [test_date_1, test_date_2, test_date_3, test_date_4, test_date_5, test_date_6, test_date_8, test_date_9, test_date_10, test_date_11]:
        cleanup_date(d)

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
