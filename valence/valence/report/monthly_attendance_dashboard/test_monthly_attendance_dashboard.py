from __future__ import annotations

from datetime import timedelta

import frappe

from valence.valence.attendance_summary import score_codes, split_code
from valence.valence.report.monthly_attendance_dashboard.monthly_attendance_dashboard import (
	build_columns,
	department_chain,
	get_period,
	resolve_code,
	within_employment,
)

SHIFT = "TEST-SHIFT"
FULL_DAY_HOURS = 6.0

SHIFT_CACHE = {SHIFT: {"duration": 8.0, "midpoint": timedelta(hours=13)}}

DAY = "2026-07-06"
FULL_IN, FULL_OUT = f"{DAY} 09:00:00", f"{DAY} 17:00:00"
FIRST_IN, FIRST_OUT = f"{DAY} 09:00:00", f"{DAY} 13:00:00"
SECOND_IN, SECOND_OUT = f"{DAY} 13:00:00", f"{DAY} 17:00:00"


def _record(**kwargs):
	record = {
		"status": None,
		"leave_type": None,
		"working_hours": 0,
		"in_time": None,
		"out_time": None,
		"shift": SHIFT,
		"half_day_status": None,
		"attendance_request": None,
	}
	record.update(kwargs)
	return record


def _code(record, day_type=None, reasons=None):
	return resolve_code(record, day_type, SHIFT_CACHE, reasons or {}, FULL_DAY_HOURS)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))

	frappe.set_user("Administrator")

	print("")
	print("=" * 76)
	print("MONTHLY ATTENDANCE DASHBOARD")
	print("=" * 76)

	print("")
	print("-- Attendance codes " + "-" * 55)

	checks = [
		("Present", _record(status="Present", working_hours=8, in_time=FULL_IN, out_time=FULL_OUT), None, {}, "P"),
		("Half day first half", _record(status="Half Day", working_hours=4, in_time=FIRST_IN, out_time=FIRST_OUT, half_day_status="Absent"), None, {}, "P/A"),
		("Half day second half", _record(status="Half Day", working_hours=4, in_time=SECOND_IN, out_time=SECOND_OUT, half_day_status="Absent"), None, {}, "A/P"),
		("Absent", _record(status="Absent"), None, {}, "A"),
		("No punch shows Absent", _record(status="No punch"), None, {}, "A"),
		("Mispunch shows Mispunch", _record(status="Mispunch"), None, {}, "MP"),
		("On Duty", _record(status="On Duty"), None, {}, "TT"),
		("Half day On Duty", _record(status="Half Day", in_time=FIRST_IN, out_time=FIRST_OUT, attendance_request="AR-1"), None, {"AR-1": "On Duty"}, "P/TT"),
		("WFH reports as P", _record(status="Work From Home", working_hours=8), None, {}, "P"),
		("Short leave reports as P", _record(status="Present With Short Leave", working_hours=8), None, {}, "P"),
		("Earned Leave", _record(status="On Leave", leave_type="Earned Leave"), None, {}, "EL"),
		("Privilege Leave", _record(status="On Leave", leave_type="Privilege Leave"), None, {}, "PL"),
		("Casual Leave", _record(status="On Leave", leave_type="Casual Leave"), None, {}, "CL"),
		("Sick Leave", _record(status="On Leave", leave_type="Sick Leave"), None, {}, "SL"),
		("Leave Without Pay", _record(status="On Leave", leave_type="Leave Without Pay"), None, {}, "L/L"),
		("Compensatory Off", _record(status="On Leave", leave_type="Compensatory Off"), None, {}, "CO"),
		("Weekly off idle", _record(status="Weekly Off"), "Weekly Off", {}, "WO"),
		("Weekly off worked full", _record(status="Present", working_hours=7, in_time=FULL_IN, out_time=FULL_OUT), "Weekly Off", {}, "PWO"),
		("Weekly off worked half", _record(status="Present", working_hours=4, in_time=FIRST_IN, out_time=FIRST_OUT), "Weekly Off", {}, "PAW"),
		("Weekly off double shift", _record(status="Present", working_hours=16, in_time=FULL_IN, out_time=FULL_OUT), "Weekly Off", {}, "2PWO"),
		("Holiday idle", _record(status="Holiday"), "Holiday", {}, "H"),
		("Holiday worked full", _record(status="Present", working_hours=8, in_time=FULL_IN, out_time=FULL_OUT), "Holiday", {}, "HP"),
		("Holiday worked half", _record(status="Present", working_hours=4, in_time=FIRST_IN, out_time=FIRST_OUT), "Holiday", {}, "HP/A"),
		("Holiday double shift", _record(status="Present", working_hours=16, in_time=FULL_IN, out_time=FULL_OUT), "Holiday", {}, "2HP"),
		("Double shift", _record(status="Present", working_hours=16, in_time=FULL_IN, out_time=FULL_OUT), None, {}, "2P"),
		("Partial double shift", _record(status="Present", working_hours=12, in_time=FULL_IN, out_time=FULL_OUT), None, {}, "2P/A"),
		("Holiday is never absent", _record(status="Absent"), "Holiday", {}, "H"),
		("Leave on weekly off not marked", _record(status="On Leave", leave_type="Casual Leave"), "Weekly Off", {}, "WO"),
	]

	for label, record, day_type, reasons, expected in checks:
		actual = _code(record, day_type, reasons)
		ok(label, actual == expected, f"expected {expected!r} got {actual!r}")

	ok(
		"Missing record on a weekly off shows WO",
		resolve_code(None, "Weekly Off", SHIFT_CACHE, {}, FULL_DAY_HOURS) == "WO",
	)
	ok(
		"Missing record on a holiday shows H",
		resolve_code(None, "Holiday", SHIFT_CACHE, {}, FULL_DAY_HOURS) == "H",
	)
	ok(
		"Missing record on a working day is blank",
		resolve_code(None, None, SHIFT_CACHE, {}, FULL_DAY_HOURS) == "",
	)

	print("")
	print("-- Summary columns " + "-" * 56)

	ok("2P/A is atomic and not split", split_code("2P/A") == [("2P/A", "full")])
	ok("HP/A is atomic and not split", split_code("HP/A") == [("HP/A", "full")])
	ok(
		"P/CL splits into two halves",
		split_code("P/CL") == [("P", "half"), ("CL", "half")],
	)

	totals = score_codes(["P", "P", "A", "P/A"])
	ok("AB counts full and half absences", totals["ab"] == 1.5, str(totals["ab"]))
	ok("Present days count halves", totals["present_days"] == 2.5, str(totals["present_days"]))

	dd_rot = score_codes(["2P", "2PWO", "PWO"])
	ok("DD counts 2P and 2PWO", dd_rot["dd"] == 2.0, str(dd_rot["dd"]))
	ok("ROT counts PWO", dd_rot["rot"] == 1.0, str(dd_rot["rot"]))

	leave_totals = score_codes(["CL", "SL", "EL", "PL", "L/L", "CO"])
	ok("Paid leaves counts CL SL EL PL", leave_totals["paid_leaves"] == 4.0, str(leave_totals["paid_leaves"]))
	ok("LWP counts L/L as one day", leave_totals["lwp"] == 1.0, str(leave_totals["lwp"]))
	ok("CO counted once", leave_totals["co"] == 1.0, str(leave_totals["co"]))

	ot = score_codes(["PWO", "PAW", "2PWO", "CO"])
	ok("OT nets earned minus consumed", ot["ot"] == 2.5, str(ot["ot"]))

	nh = score_codes(["H", "HP", "CO/H"])
	ok("NH includes CO/H", nh["nh"] == 3.0, str(nh["nh"]))

	pday = score_codes(["P", "WO", "H"])
	ok("Pday is WD plus WO plus NH", pday["pday"] == 3.0, str(pday["pday"]))

	mixed = score_codes(["A", "CL", "L/L"])
	ok(
		"Leave plus absent totals correctly",
		mixed["leave_absent"] == 3.0,
		str(mixed["leave_absent"]),
	)

	ok("Mispunch is not counted in any total", score_codes(["MP"])["pday"] == 0.0)
	ok("Unknown codes are ignored safely", score_codes(["ZZ"])["pday"] == 0.0)

	print("")
	print("-- Month handling " + "-" * 57)

	start, end, days = get_period({"month": 2, "year": 2024})
	ok("February 2024 is a leap month", days == 29, str(days))

	start, end, days = get_period({"month": 2, "year": 2026})
	ok("February 2026 has 28 days", days == 28, str(days))

	start, end, days = get_period({"month": 7, "year": 2026})
	ok("July has 31 days", days == 31, str(days))
	ok("Period starts on day 1", start.day == 1, str(start))
	ok("Period ends on the last day", end.day == 31, str(end))

	start, end, days = get_period({"month": 4, "year": 2026})
	ok("April has 30 days", days == 30, str(days))

	columns = build_columns(28)
	day_columns = [c for c in columns if c["fieldname"].startswith("d") and c["fieldname"][1:].isdigit()]
	ok("Day columns regenerate for the month length", len(day_columns) == 28, str(len(day_columns)))
	ok("Day columns start at day 1", day_columns[0]["fieldname"] == "d1")
	ok("Day columns end at the last day", day_columns[-1]["fieldname"] == "d28")

	fieldnames = [c["fieldname"] for c in columns]
	for required in ("dd", "rot", "hold", "remarks", "hr_remarks", "function_label", "module_label"):
		ok(f"Column {required} present", required in fieldnames)

	print("")
	print("-- Employment period " + "-" * 54)

	joiner = {"date_of_joining": "2026-07-15", "relieving_date": None}
	ok("Day before joining is excluded", within_employment(joiner, frappe.utils.getdate("2026-07-14")) is False)
	ok("Joining day is included", within_employment(joiner, frappe.utils.getdate("2026-07-15")) is True)
	ok("Day after joining is included", within_employment(joiner, frappe.utils.getdate("2026-07-20")) is True)

	leaver = {"date_of_joining": "2020-01-01", "relieving_date": "2026-07-10"}
	ok("Day before leaving is included", within_employment(leaver, frappe.utils.getdate("2026-07-10")) is True)
	ok("Day after leaving is excluded", within_employment(leaver, frappe.utils.getdate("2026-07-11")) is False)

	print("")
	print("-- Department hierarchy " + "-" * 51)

	tree = {
		"All Departments": {"name": "All Departments", "department_name": "All Departments", "parent_department": None, "is_group": 1},
		"HR and Admin - VL": {"name": "HR and Admin - VL", "department_name": "HR and Admin", "parent_department": "All Departments", "is_group": 1},
		"Administration - VL": {"name": "Administration - VL", "department_name": "Administration", "parent_department": "HR and Admin - VL", "is_group": 1},
		"Security - VL": {"name": "Security - VL", "department_name": "Security", "parent_department": "Administration - VL", "is_group": 0},
	}

	chain = department_chain("Security - VL", tree)
	labels = [node[1] for node in chain]
	ok("Root department is dropped", "All Departments" not in labels, str(labels))
	ok("Department resolves to the top level", labels[0] == "HR and Admin", str(labels))
	ok("Function resolves to the middle level", labels[1] == "Administration", str(labels))
	ok("Module resolves to the deepest level", labels[-1] == "Security", str(labels))

	shallow = department_chain("HR and Admin - VL", tree)
	ok("Shallow department has no module level", len(shallow) == 1, str(shallow))

	ok("Unknown department yields an empty chain", department_chain(None, tree) == [])

	print("")
	print("-- Combinations " + "-" * 59)

	combo = score_codes(["CL", "WO", "P", "PWO"])
	ok("Leave plus weekly off in one month", combo["wd"] == 2.0 and combo["wo"] == 2.0, str(combo))

	combo = score_codes(["P", "P", "MP", "CL"])
	ok(
		"Mispunch does not inflate present days",
		combo["present_days"] == 2.0,
		str(combo["present_days"]),
	)

	combo = score_codes(["A", "H", "WO", "P/CL"])
	ok(
		"Mixed month totals stay consistent",
		combo["pday"] == 3.0 and combo["ab"] == 1.0,
		str(combo),
	)

	failures = [r for r in results if r[0] == "FAIL"]

	print("")
	print("=" * 76)
	print(
		"TOTAL {0}    PASSED {1}    FAILED {2}".format(
			len(results), len(results) - len(failures), len(failures)
		)
	)
	print("=" * 76)

	if failures:
		print("")
		print("FAILURES")
		for _, name, detail in failures:
			print(f"  {name}" + (f" - {detail}" if detail else ""))

	print("")
	return len(failures)
