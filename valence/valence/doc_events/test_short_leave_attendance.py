"""E2E + unit checks for Short Leave attendance adjustment.

  bench --site valence.localhost execute valence.valence.doc_events.test_short_leave_attendance.run
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from valence.valence.doc_events import attendance as attendance_mod
from valence.valence.doc_events.attendance import (
	get_actual_shift_gap_hours,
	get_approved_short_leave_hours,
	get_shift_duration_hours,
	has_approved_short_leave,
	set_status,
)
from valence.valence.doc_events.short_leave_application import (
	validate_duration_against_settings,
)
from valence.valence.setup.short_leave_workflow import after_migrate as ensure_short_leave_workflow

SHIFT_NAME = "E2E SL Shift 9-1730"
EMP_NAME_KEY = "E2E Short Leave Att Emp"


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	frappe.set_user("Administrator")
	# Avoid legacy point system interfering with new SLA path
	prev_personal_cap = None
	if frappe.db.exists("DocType", "Attendance Settings"):
		frappe.db.set_single_value("Attendance Settings", "use_late_coming_rules", 0)
		prev_personal_cap = frappe.db.get_single_value(
			"Attendance Settings", "short_leave_personal_monthly_cap"
		)
		# E2E creates multiple Personal leaves in one month — raise cap for the run
		frappe.db.set_single_value("Attendance Settings", "short_leave_personal_monthly_cap", 50)

	ensure_short_leave_workflow()
	_run_unit_gap_tests(ok)

	shift = _ensure_shift()
	employee, company = _ensure_employee(shift)
	_purge_employee_fixtures(employee)
	ok("Fixtures ready", bool(shift and employee), f"shift={shift} emp={employee}")

	created_att = []
	created_sl = []
	base = add_days(getdate(), 40)  # future dates avoid collisions with real attendance

	try:
		# ------ 1. Client example: late 2h + Personal SL → full shift Present ------
		d1 = add_days(base, 0)
		att1 = _make_attendance(
			employee,
			company,
			shift,
			d1,
			datetime.combine(d1, datetime.strptime("11:00:00", "%H:%M:%S").time()),
			datetime.combine(d1, datetime.strptime("17:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att1)
		set_status(frappe.get_doc("Attendance", att1), "validate")
		a = frappe.get_doc("Attendance", att1)
		ok(
			"Without SL: late-in punch hours only (~6.5)",
			flt(a.working_hours) == 6.5,
			f"hours={a.working_hours} status={a.status}",
		)
		# With typical half-day threshold 6 → Present already at 6.5; force status check via hours
		sl1 = _make_approved_short_leave(employee, d1, "Personal", "09:00:00", "11:00:00")
		created_sl.append(sl1)
		set_status(frappe.get_doc("Attendance", att1), "validate")
		a = frappe.get_doc("Attendance", att1)
		ok(
			"Late-in + Personal SL: hours = 8.5 (punch+actual gap)",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours} status={a.status}",
		)
		ok("Late-in + Personal SL: Present", a.status == "Present", a.status)

		# ------ 2. Early out 2h + Personal SL ------
		d2 = add_days(base, 1)
		att2 = _make_attendance(
			employee,
			company,
			shift,
			d2,
			datetime.combine(d2, datetime.strptime("09:00:00", "%H:%M:%S").time()),
			datetime.combine(d2, datetime.strptime("15:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att2)
		sl2 = _make_approved_short_leave(employee, d2, "Personal", "15:30:00", "17:30:00")
		created_sl.append(sl2)
		set_status(frappe.get_doc("Attendance", att2), "validate")
		a = frappe.get_doc("Attendance", att2)
		ok(
			"Early-out + Personal SL: hours = 8.5",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours} status={a.status}",
		)

		# ------ 3. Official SL also credits actual gap ------
		d3 = add_days(base, 2)
		att3 = _make_attendance(
			employee,
			company,
			shift,
			d3,
			datetime.combine(d3, datetime.strptime("11:00:00", "%H:%M:%S").time()),
			datetime.combine(d3, datetime.strptime("17:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att3)
		sl3 = _make_approved_short_leave(employee, d3, "Official", "09:00:00", "12:00:00")  # leave says 3h
		created_sl.append(sl3)
		set_status(frappe.get_doc("Attendance", att3), "validate")
		a = frappe.get_doc("Attendance", att3)
		ok(
			"Official SL credits actual gap 2.0 not leave duration 3.0",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours} leave_dur={get_approved_short_leave_hours(employee, d3)}",
		)

		# ------ 4. Leave duration 2h but actual gap only 1h → credit 1h ------
		d4 = add_days(base, 3)
		att4 = _make_attendance(
			employee,
			company,
			shift,
			d4,
			datetime.combine(d4, datetime.strptime("10:00:00", "%H:%M:%S").time()),
			datetime.combine(d4, datetime.strptime("17:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att4)
		sl4 = _make_approved_short_leave(employee, d4, "Personal", "09:00:00", "11:00:00")
		created_sl.append(sl4)
		set_status(frappe.get_doc("Attendance", att4), "validate")
		a = frappe.get_doc("Attendance", att4)
		# punch 7.5 + gap 1.0 = 8.5
		ok(
			"Actual gap 1h used even when leave form is 2h",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours}",
		)

		# ------ 5. Full shift on time + SL → gap 0, still 8.5 ------
		d5 = add_days(base, 4)
		att5 = _make_attendance(
			employee,
			company,
			shift,
			d5,
			datetime.combine(d5, datetime.strptime("09:00:00", "%H:%M:%S").time()),
			datetime.combine(d5, datetime.strptime("17:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att5)
		sl5 = _make_approved_short_leave(employee, d5, "Personal", "09:00:00", "10:00:00")
		created_sl.append(sl5)
		set_status(frappe.get_doc("Attendance", att5), "validate")
		a = frappe.get_doc("Attendance", att5)
		ok(
			"On-time punches: SL does not inflate above punch (gap 0)",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours}",
		)

		# ------ 6. Cap at shift length (stay after shift end) ------
		d6 = add_days(base, 5)
		att6 = _make_attendance(
			employee,
			company,
			shift,
			d6,
			datetime.combine(d6, datetime.strptime("11:00:00", "%H:%M:%S").time()),
			datetime.combine(d6, datetime.strptime("19:00:00", "%H:%M:%S").time()),
		)
		created_att.append(att6)
		sl6 = _make_approved_short_leave(employee, d6, "Official", "09:00:00", "11:00:00")
		created_sl.append(sl6)
		set_status(frappe.get_doc("Attendance", att6), "validate")
		a = frappe.get_doc("Attendance", att6)
		# punch 8.0 + gap 2.0 = 10 → capped to 8.5
		ok(
			"Hours capped at shift duration 8.5",
			flt(a.working_hours) == 8.5,
			f"hours={a.working_hours}",
		)

		# ------ 7. Late+early without SL → punch only (4.5), Half Day vs thresholds ------
		d7 = add_days(base, 6)
		att7 = _make_attendance(
			employee,
			company,
			shift,
			d7,
			datetime.combine(d7, datetime.strptime("11:00:00", "%H:%M:%S").time()),
			datetime.combine(d7, datetime.strptime("15:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att7)
		set_status(frappe.get_doc("Attendance", att7), "validate")
		a = frappe.get_doc("Attendance", att7)
		ok("Without SL: late+early punch = 4.5", flt(a.working_hours) == 4.5, f"hours={a.working_hours}")
		ok(
			"Without SL: below half-day threshold → Half Day",
			a.status == "Half Day",
			f"status={a.status} (half_day_threshold should be 6)",
		)

		# ------ 8. Same punches + Official SL → rescued to Present ------
		sl7 = _make_approved_short_leave(employee, d7, "Official", "09:00:00", "13:00:00")
		created_sl.append(sl7)
		set_status(frappe.get_doc("Attendance", att7), "validate")
		a = frappe.get_doc("Attendance", att7)
		ok(
			"With SL: late+early adjusted to 8.5 Present",
			flt(a.working_hours) == 8.5 and a.status == "Present",
			f"hours={a.working_hours} status={a.status}",
		)

		# ------ 9. No punches + approved SL → leave duration drives hours ------
		d9 = add_days(base, 7)
		att9 = _make_attendance(employee, company, shift, d9, None, None)
		created_att.append(att9)
		sl9 = _make_approved_short_leave(employee, d9, "Personal", "09:00:00", "11:00:00")
		created_sl.append(sl9)
		set_status(frappe.get_doc("Attendance", att9), "validate")
		a = frappe.get_doc("Attendance", att9)
		ok(
			"No punch + SL: working_hours = leave duration 2.0",
			flt(a.working_hours) == 2.0,
			f"hours={a.working_hours} status={a.status}",
		)

		# ------ 10. Personal > 2hrs blocked on application ------
		blocked = False
		err = ""
		try:
			doc = frappe._dict(
				{
					"short_leave_type": "Personal",
					"duration_hours": 2.5,
				}
			)
			with patch(
				"valence.valence.doc_events.short_leave_application.frappe.db.get_single_value",
				return_value=2,
			):
				validate_duration_against_settings(doc)
		except frappe.ValidationError as e:
			blocked = True
			err = str(e)
		ok("Personal Short Leave > 2hrs is blocked", blocked, err[:120])

		# Official > 2hrs allowed
		official_ok = True
		try:
			validate_duration_against_settings(
				frappe._dict({"short_leave_type": "Official", "duration_hours": 4})
			)
		except Exception:
			official_ok = False
		ok("Official Short Leave > 2hrs is allowed", official_ok)

		# ------ 11. has_approved_short_leave helper ------
		ok("has_approved_short_leave True for d1", has_approved_short_leave(employee, d1))
		ok(
			"has_approved_short_leave False for random date",
			not has_approved_short_leave(employee, add_days(base, 99)),
		)

		# ------ 12. Approve refresh path: draft attendance then approve SL ------
		d12 = add_days(base, 8)
		att12 = _make_attendance(
			employee,
			company,
			shift,
			d12,
			datetime.combine(d12, datetime.strptime("11:00:00", "%H:%M:%S").time()),
			datetime.combine(d12, datetime.strptime("17:30:00", "%H:%M:%S").time()),
		)
		created_att.append(att12)
		set_status(frappe.get_doc("Attendance", att12), "validate")
		before_h = flt(frappe.db.get_value("Attendance", att12, "working_hours"))
		sl12 = _make_approved_short_leave(employee, d12, "Personal", "09:00:00", "11:00:00")
		created_sl.append(sl12)
		# Simulate workflow approve refresh
		from valence.valence.doc_events.short_leave_application import (
			refresh_attendance_after_short_leave_approval,
		)

		sla = frappe.get_doc("Short Leave Application", sl12)
		# Force "just became Approved" by clearing before_save perception
		with patch.object(sla, "get_doc_before_save", return_value=frappe._dict(workflow_state="Pending Approval")):
			refresh_attendance_after_short_leave_approval(sla)
		after_h = flt(frappe.db.get_value("Attendance", att12, "working_hours"))
		ok(
			"Approve refresh lifts hours from punch-only to punch+gap",
			before_h == 6.5 and after_h == 8.5,
			f"before={before_h} after={after_h}",
		)

	finally:
		_cleanup(created_sl, created_att)
		if prev_personal_cap is not None:
			frappe.db.set_single_value(
				"Attendance Settings",
				"short_leave_personal_monthly_cap",
				prev_personal_cap if prev_personal_cap not in (None, "") else 2,
			)
			frappe.db.commit()

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		fails = [n for s, n, _ in results if s == "FAIL"]
		frappe.throw(f"Short leave attendance E2E failed ({failed}): {fails}")
	return {"passed": passed, "failed": failed}


def _run_unit_gap_tests(ok):
	fake_start = timedelta(hours=9)
	fake_end = timedelta(hours=17, minutes=30)
	real_get_value = frappe.db.get_value

	def fake_get_value(doctype, name=None, fieldname=None, *args, **kwargs):
		if doctype == "Shift Type" and fieldname == ["start_time", "end_time"]:
			return (fake_start, fake_end)
		return real_get_value(doctype, name, fieldname, *args, **kwargs)

	with patch.object(attendance_mod.frappe.db, "get_value", side_effect=fake_get_value):
		ok(
			"Unit: late-in gap 2.0",
			flt(
				get_actual_shift_gap_hours(
					"X", datetime(2026, 8, 20, 11, 0, 0), datetime(2026, 8, 20, 17, 30, 0)
				)
			)
			== 2.0,
		)
		ok(
			"Unit: early-out gap 2.0",
			flt(
				get_actual_shift_gap_hours(
					"X", datetime(2026, 8, 20, 9, 0, 0), datetime(2026, 8, 20, 15, 30, 0)
				)
			)
			== 2.0,
		)
		ok(
			"Unit: late+early gap 4.0",
			flt(
				get_actual_shift_gap_hours(
					"X", datetime(2026, 8, 20, 11, 0, 0), datetime(2026, 8, 20, 15, 30, 0)
				)
			)
			== 4.0,
		)
		ok(
			"Unit: on-time gap 0",
			flt(
				get_actual_shift_gap_hours(
					"X", datetime(2026, 8, 20, 9, 0, 0), datetime(2026, 8, 20, 17, 30, 0)
				)
			)
			== 0.0,
		)
		ok("Unit: shift duration 8.5", flt(get_shift_duration_hours("X")) == 8.5)


def _ensure_shift():
	if frappe.db.exists("Shift Type", SHIFT_NAME):
		doc = frappe.get_doc("Shift Type", SHIFT_NAME)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Shift Type",
				"name": SHIFT_NAME,
				"start_time": "09:00:00",
				"end_time": "17:30:00",
			}
		)
		doc.insert(ignore_permissions=True)

	# Predictable thresholds: <2 Absent, <6 Half Day, else Present
	frappe.db.set_value(
		"Shift Type",
		doc.name,
		{
			"start_time": "09:00:00",
			"end_time": "17:30:00",
			"working_hours_threshold_for_half_day": 6,
			"working_hours_threshold_for_absent": 2,
		},
		update_modified=False,
	)
	frappe.db.commit()
	return doc.name


def _ensure_employee(shift):
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	existing = frappe.db.get_value("Employee", {"employee_name": EMP_NAME_KEY}, "name")
	if existing:
		frappe.db.set_value(
			"Employee",
			existing,
			{"status": "Active", "default_shift": shift, "company": company, "relieving_date": None},
			update_modified=False,
		)
		frappe.db.commit()
		return existing, company

	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "E2E",
			"last_name": "ShortLeaveAtt",
			"employee_name": EMP_NAME_KEY,
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": add_days(nowdate(), -400),
			"status": "Active",
			"company": company,
			"default_shift": shift,
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name, company


def _make_attendance(employee, company, shift, day, in_time, out_time):
	# Remove existing for this day
	for name in frappe.get_all(
		"Attendance",
		filters={"employee": employee, "attendance_date": day},
		pluck="name",
	):
		frappe.delete_doc("Attendance", name, force=1, ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"company": company,
			"attendance_date": day,
			"status": "Present",
			"shift": shift,
			"in_time": in_time,
			"out_time": out_time,
		}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _make_approved_short_leave(employee, day, leave_type, from_time, to_time):
	for name in frappe.get_all(
		"Short Leave Application",
		filters={"employee": employee, "date": day, "docstatus": ["<", 2]},
		pluck="name",
	):
		frappe.db.set_value("Short Leave Application", name, "docstatus", 2, update_modified=False)

	doc = frappe.get_doc(
		{
			"doctype": "Short Leave Application",
			"employee": employee,
			"short_leave_type": leave_type,
			"date": day,
			"from_time": from_time,
			"to_time": to_time,
			"reason": f"E2E {leave_type} short leave",
			"status": "Open",
			"workflow_state": "Draft",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	# Bypass workflow transitions — set Approved directly for attendance fixture
	frappe.db.set_value(
		"Short Leave Application",
		doc.name,
		{
			"docstatus": 1,
			"workflow_state": "Approved",
			"status": "Approved",
		},
		update_modified=False,
	)
	frappe.db.commit()
	return doc.name


def _purge_employee_fixtures(employee):
	for name in frappe.get_all(
		"Short Leave Application", filters={"employee": employee}, pluck="name"
	):
		frappe.db.set_value("Short Leave Application", name, "docstatus", 0, update_modified=False)
		frappe.delete_doc("Short Leave Application", name, force=1, ignore_permissions=True)
	for name in frappe.get_all("Attendance", filters={"employee": employee}, pluck="name"):
		frappe.delete_doc("Attendance", name, force=1, ignore_permissions=True)
	frappe.db.commit()


def _cleanup(short_leaves, attendances):
	for name in short_leaves:
		if name and frappe.db.exists("Short Leave Application", name):
			frappe.db.set_value("Short Leave Application", name, "docstatus", 2, update_modified=False)
			frappe.delete_doc("Short Leave Application", name, force=1, ignore_permissions=True)
	for name in attendances:
		if name and frappe.db.exists("Attendance", name):
			frappe.delete_doc("Attendance", name, force=1, ignore_permissions=True)
	frappe.db.commit()
