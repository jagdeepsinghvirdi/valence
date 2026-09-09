from __future__ import annotations

import frappe
from frappe.utils import getdate

from valence.api import (
	get_applicable_shift,
	get_applicable_shift_assignment,
	get_day_type,
	get_day_type_map,
	get_shift_weekly_off_days,
)

PREFIX = "ZZ-SHIFT-RES"
DEFAULT_SHIFT = f"{PREFIX} Default"
TEMP_SHIFT = f"{PREFIX} Temp"
NO_OFF_SHIFT = f"{PREFIX} NoOff"


def _company():
	return frappe.db.get_value("Company", {}, "name")


def _ensure_shift(name, start="09:00:00", end="17:00:00"):
	if not frappe.db.exists("Shift Type", name):
		frappe.get_doc(
			{
				"doctype": "Shift Type",
				"__newname": name,
				"start_time": start,
				"end_time": end,
				"working_hours_threshold_for_half_day": 4,
				"working_hours_threshold_for_absent": 2,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value(
			"Shift Type",
			name,
			{
				"start_time": start,
				"end_time": end,
				"working_hours_threshold_for_half_day": 4,
				"working_hours_threshold_for_absent": 2,
			},
			update_modified=False,
		)
	return name


OVERNIGHT_SHIFT = f"{PREFIX} Overnight"


class _StubAttendance:
	def __init__(self, in_time=None, out_time=None):
		self.in_time = in_time
		self.out_time = out_time
		self.values = {}

	def db_set(self, field, value):
		self.values[field] = value


def _status_for(shift, hours, in_time=None, out_time=None):
	from valence.valence.doc_events.attendance import _apply_hours_status

	stub = _StubAttendance(in_time=in_time, out_time=out_time)
	_apply_hours_status(stub, hours, shift)
	return stub.values.get("status")


def _ensure_employee():
	existing = frappe.db.get_value("Employee", {"employee_name": PREFIX}, "name")
	if existing:
		return existing

	emp = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": PREFIX,
			"gender": "Prefer not to say",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2020-01-01",
			"status": "Active",
			"company": _company(),
		}
	)
	emp.insert(ignore_permissions=True)
	return emp.name


def _make_assignment(employee, shift, off_day, start_date, end_date=None):
	doc = frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"shift_type": shift,
			"company": _company(),
			"start_date": start_date,
			"end_date": end_date,
			"status": "Active",
			"custom_off_day": off_day,
		}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _make_schedule_assignment(employee, shift, repeat_on_days, start_date, end_date):
	from hrms.hr.doctype.shift_schedule.shift_schedule import get_or_insert_shift_schedule

	schedule = get_or_insert_shift_schedule(shift, "Every Week", repeat_on_days)
	doc = frappe.get_doc(
		{
			"doctype": "Shift Schedule Assignment",
			"shift_schedule": schedule,
			"employee": employee,
			"company": _company(),
			"shift_status": "Active",
			"enabled": 0,
		}
	).insert(ignore_permissions=True)
	doc.create_shifts(start_date, end_date)
	return doc.name


def _ensure_sunday_holiday_list():
	name = f"{PREFIX} Sundays"
	if frappe.db.exists("Holiday List", name):
		return name

	from frappe.utils import add_days

	doc = frappe.get_doc(
		{
			"doctype": "Holiday List",
			"__newname": name,
			"holiday_list_name": name,
			"from_date": "2026-01-01",
			"to_date": "2026-12-31",
		}
	)

	day = getdate("2026-01-04")
	while day <= getdate("2026-12-31"):
		doc.append(
			"holidays",
			{"holiday_date": day, "description": "Sunday", "weekly_off": 1},
		)
		day = add_days(day, 7)

	doc.insert(ignore_permissions=True)
	return name


def _cleanup(employee):
	for name in frappe.get_all(
		"Shift Assignment", filters={"employee": employee}, pluck="name"
	):
		doc = frappe.get_doc("Shift Assignment", name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.delete_doc("Shift Assignment", name, force=1, ignore_permissions=True)

	for name in frappe.get_all(
		"Shift Schedule Assignment", filters={"employee": employee}, pluck="name"
	):
		frappe.delete_doc("Shift Schedule Assignment", name, force=1, ignore_permissions=True)


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))

	frappe.set_user("Administrator")

	print("")
	print("=" * 72)
	print("SHIFT RESOLUTION - SOURCE OF TRUTH")
	print("=" * 72)

	_ensure_shift(DEFAULT_SHIFT)
	_ensure_shift(TEMP_SHIFT)
	_ensure_shift(NO_OFF_SHIFT)
	employee = _ensure_employee()
	_cleanup(employee)

	try:
		_make_assignment(employee, DEFAULT_SHIFT, "Sunday", "2026-01-01")
		_make_assignment(employee, TEMP_SHIFT, "Monday", "2026-06-01", "2026-06-07")

		inside = getdate("2026-06-03")
		after = getdate("2026-06-15")

		assignment = get_applicable_shift_assignment(employee, inside)
		ok(
			"Assignment period resolves to the temporary assignment",
			assignment and assignment.get("shift_type") == TEMP_SHIFT,
			str(assignment and assignment.get("shift_type")),
		)
		ok(
			"Applicable shift inside period is the assigned shift",
			get_applicable_shift(employee, inside) == TEMP_SHIFT,
		)

		off_inside = get_shift_weekly_off_days(employee, inside)
		ok(
			"Assigned weekly off applies inside the period",
			off_inside == {"monday"},
			str(off_inside),
		)
		ok(
			"Default weekly off does NOT leak into the period",
			"sunday" not in off_inside,
			str(off_inside),
		)

		ok(
			"Monday inside period is Weekly Off",
			get_day_type(employee, "2026-06-01") == "Weekly Off",
			str(get_day_type(employee, "2026-06-01")),
		)
		ok(
			"Sunday inside period is NOT Weekly Off",
			get_day_type(employee, "2026-06-07") is None,
			str(get_day_type(employee, "2026-06-07")),
		)

		ok(
			"Reverts to default shift after the assignment ends",
			get_applicable_shift(employee, after) == DEFAULT_SHIFT,
			str(get_applicable_shift(employee, after)),
		)
		off_after = get_shift_weekly_off_days(employee, after)
		ok(
			"Default weekly off resumes after the period",
			off_after == {"sunday"},
			str(off_after),
		)
		ok(
			"Sunday after the period is Weekly Off again",
			get_day_type(employee, "2026-06-21") == "Weekly Off",
			str(get_day_type(employee, "2026-06-21")),
		)

		day_map = get_day_type_map([employee], "2026-06-01", "2026-06-21")
		ok(
			"Bulk day map agrees inside the period",
			day_map.get((employee, getdate("2026-06-01"))) == "Weekly Off"
			and day_map.get((employee, getdate("2026-06-07"))) is None,
		)
		ok(
			"Bulk day map agrees after the period",
			day_map.get((employee, getdate("2026-06-21"))) == "Weekly Off",
		)

		_cleanup(employee)
		_make_assignment(employee, DEFAULT_SHIFT, "Sunday", "2026-01-01")
		_make_assignment(employee, NO_OFF_SHIFT, None, "2026-06-01", "2026-06-07")

		off_empty = get_shift_weekly_off_days(employee, inside)
		ok(
			"Assignment without a weekly off does NOT inherit the older one",
			off_empty == set(),
			str(off_empty),
		)
		ok(
			"Sunday inside a no-weekly-off assignment is a working day",
			get_day_type(employee, "2026-06-07") is None,
			str(get_day_type(employee, "2026-06-07")),
		)

		print("")
		print("-- Roster weekly offs " + "-" * 49)

		_cleanup(employee)
		_make_assignment(employee, DEFAULT_SHIFT, "Sunday", "2026-01-01")
		_make_assignment(employee, TEMP_SHIFT, "Monday", "2026-06-01", "2026-06-07")

		from valence.valence.override.whitelisted_method.roster import get_weekly_offs

		roster = get_weekly_offs("2026-06-01", "2026-06-30", {"name": employee})
		roster_dates = {row["holiday_date"] for row in roster.get(employee, [])}

		ok(
			"Roster marks the assigned weekly off inside the period",
			"2026-06-01" in roster_dates,
			str(sorted(roster_dates)),
		)
		ok(
			"Roster does NOT leak the default weekly off into the period",
			"2026-06-07" not in roster_dates,
			str(sorted(roster_dates)),
		)
		ok(
			"Roster resumes the default weekly off after the period",
			"2026-06-14" in roster_dates and "2026-06-21" in roster_dates,
			str(sorted(roster_dates)),
		)
		ok(
			"Roster no longer applies one weekday to the whole month",
			"2026-06-08" not in roster_dates,
			str(sorted(roster_dates)),
		)

		print("")
		print("-- Shift schedule gaps " + "-" * 48)

		_cleanup(employee)
		_make_schedule_assignment(
			employee,
			TEMP_SHIFT,
			["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"],
			"2026-05-01",
			"2026-05-29",
		)

		schedule_map = get_day_type_map([employee], "2026-05-01", "2026-05-31")
		ok(
			"Schedule off day shows on the start date when it is an off day",
			schedule_map.get((employee, getdate("2026-05-01"))) == "Weekly Off",
			str(schedule_map.get((employee, getdate("2026-05-01")))),
		)
		ok(
			"Schedule off day shows on a gap day inside the schedule",
			schedule_map.get((employee, getdate("2026-05-15"))) == "Weekly Off",
			str(schedule_map.get((employee, getdate("2026-05-15")))),
		)
		ok(
			"Schedule off day shows on the end date when it is an off day",
			schedule_map.get((employee, getdate("2026-05-29"))) == "Weekly Off",
			str(schedule_map.get((employee, getdate("2026-05-29")))),
		)
		ok(
			"Working day inside the schedule is not a weekly off",
			schedule_map.get((employee, getdate("2026-05-28"))) is None,
			str(schedule_map.get((employee, getdate("2026-05-28")))),
		)
		ok(
			"Schedule off day does not leak past the schedule end",
			get_day_type(employee, "2026-06-05") is None,
			str(get_day_type(employee, "2026-06-05")),
		)
		ok(
			"Single-date lookup agrees with the bulk map on the end date",
			get_day_type(employee, "2026-05-29") == "Weekly Off",
			str(get_day_type(employee, "2026-05-29")),
		)

		print("")
		print("-- Weekly off backfill " + "-" * 48)

		for name in frappe.get_all(
			"Shift Assignment", filters={"employee": employee}, pluck="name"
		):
			frappe.db.set_value(
				"Shift Assignment", name, "custom_off_day", None, update_modified=False
			)

		ok(
			"Legacy assignment with a blank weekly off shows no off day",
			get_day_type(employee, "2026-05-15") is None,
			str(get_day_type(employee, "2026-05-15")),
		)

		from valence.patches.backfill_shift_assignment_weekly_off import execute as backfill

		backfill()

		ok(
			"Backfill restores the off day from the schedule",
			get_day_type(employee, "2026-05-15") == "Weekly Off",
			str(get_day_type(employee, "2026-05-15")),
		)
		ok(
			"Backfill also restores the schedule end date",
			get_day_type(employee, "2026-05-29") == "Weekly Off",
			str(get_day_type(employee, "2026-05-29")),
		)
		ok(
			"Backfill leaves working days alone",
			get_day_type(employee, "2026-05-28") is None,
			str(get_day_type(employee, "2026-05-28")),
		)

		backfill()

		ok(
			"Backfill is idempotent",
			get_day_type(employee, "2026-05-15") == "Weekly Off",
			str(get_day_type(employee, "2026-05-15")),
		)

		print("")
		print("-- Shift off day vs Holiday List " + "-" * 38)

		_cleanup(employee)
		previous_holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
		frappe.db.set_value(
			"Employee",
			employee,
			"holiday_list",
			_ensure_sunday_holiday_list(),
			update_modified=False,
		)
		_make_assignment(employee, DEFAULT_SHIFT, "Friday", "2026-09-01", "2026-09-30")

		ok(
			"Shift off day is a Weekly Off inside the period",
			get_day_type(employee, "2026-09-04") == "Weekly Off",
			str(get_day_type(employee, "2026-09-04")),
		)
		ok(
			"Holiday List weekly off is suppressed inside the period",
			get_day_type(employee, "2026-09-06") is None,
			str(get_day_type(employee, "2026-09-06")),
		)
		ok(
			"Holiday List weekly off resumes after the period",
			get_day_type(employee, "2026-10-04") == "Weekly Off",
			str(get_day_type(employee, "2026-10-04")),
		)

		override_map = get_day_type_map([employee], "2026-09-01", "2026-09-30")
		ok(
			"Bulk map marks only the shift off day",
			override_map.get((employee, getdate("2026-09-04"))) == "Weekly Off"
			and override_map.get((employee, getdate("2026-09-06"))) is None,
			str(
				[
					override_map.get((employee, getdate("2026-09-04"))),
					override_map.get((employee, getdate("2026-09-06"))),
				]
			),
		)

		from valence.valence.override.whitelisted_method.roster import get_weekly_offs

		september = get_weekly_offs("2026-09-01", "2026-09-30", {"name": employee})
		september_dates = {row["holiday_date"] for row in september.get(employee, [])}
		ok(
			"Roster shows the shift off day and not the Holiday List Sunday",
			"2026-09-04" in september_dates and "2026-09-06" not in september_dates,
			str(sorted(september_dates)),
		)

		from valence.valence.override.whitelisted_method.roster import get_events

		def _holiday_dates(payload):
			return {
				str(row["holiday_date"])
				for row in payload.get(employee, [])
				if "holiday" in row
			}

		september_events = _holiday_dates(
			get_events("2026-09-01", "2026-09-30", {"name": employee}, {})
		)
		ok(
			"Roster events drop the Holiday List Sunday inside the period",
			"2026-09-04" in september_events and "2026-09-06" not in september_events,
			str(sorted(september_events)),
		)

		october_events = _holiday_dates(
			get_events("2026-10-01", "2026-10-31", {"name": employee}, {})
		)
		ok(
			"Roster events keep the Holiday List Sunday after the period",
			"2026-10-04" in october_events,
			str(sorted(october_events)),
		)

		frappe.db.set_value(
			"Employee",
			employee,
			"holiday_list",
			previous_holiday_list,
			update_modified=False,
		)
		_cleanup(employee)

		print("")
		print("-- Overnight shift and half-day thresholds " + "-" * 28)

		from valence.valence.doc_events.attendance import (
			get_shift_duration_hours,
			get_worked_half,
		)

		_ensure_shift(OVERNIGHT_SHIFT, "22:00:00", "06:00:00")

		ok(
			"Overnight shift duration crosses midnight correctly",
			get_shift_duration_hours(OVERNIGHT_SHIFT) == 8.0,
			str(get_shift_duration_hours(OVERNIGHT_SHIFT)),
		)

		before_mid = ("2026-06-10 22:00:00", "2026-06-11 02:00:00")
		after_mid = ("2026-06-11 02:00:00", "2026-06-11 06:00:00")
		full_night = ("2026-06-10 22:00:00", "2026-06-11 06:00:00")

		ok(
			"Overnight first half detected before midnight",
			get_worked_half(OVERNIGHT_SHIFT, *before_mid) == "First Half",
			str(get_worked_half(OVERNIGHT_SHIFT, *before_mid)),
		)
		ok(
			"Overnight second half detected after midnight",
			get_worked_half(OVERNIGHT_SHIFT, *after_mid) == "Second Half",
			str(get_worked_half(OVERNIGHT_SHIFT, *after_mid)),
		)
		ok(
			"Overnight full night spans both halves",
			get_worked_half(OVERNIGHT_SHIFT, *full_night) == "Both",
			str(get_worked_half(OVERNIGHT_SHIFT, *full_night)),
		)
		ok(
			"Overnight full night is Present",
			_status_for(OVERNIGHT_SHIFT, 8, *full_night) == "Present",
			str(_status_for(OVERNIGHT_SHIFT, 8, *full_night)),
		)
		ok(
			"Overnight partial night is Half Day",
			_status_for(OVERNIGHT_SHIFT, 4, *before_mid) == "Half Day",
			str(_status_for(OVERNIGHT_SHIFT, 4, *before_mid)),
		)

		day_full = ("2026-06-10 09:00:00", "2026-06-10 17:00:00")
		day_first = ("2026-06-10 09:00:00", "2026-06-10 13:00:00")
		day_span = ("2026-06-10 09:00:00", "2026-06-10 15:00:00")
		day_short = ("2026-06-10 09:00:00", "2026-06-10 10:00:00")

		ok(
			"Full required hours are Present",
			_status_for(DEFAULT_SHIFT, 8, *day_full) == "Present",
			str(_status_for(DEFAULT_SHIFT, 8, *day_full)),
		)
		ok(
			"More than required hours stay Present",
			_status_for(DEFAULT_SHIFT, 9, *day_full) == "Present",
			str(_status_for(DEFAULT_SHIFT, 9, *day_full)),
		)
		ok(
			"Hours above half-day threshold spanning midpoint are Present",
			_status_for(DEFAULT_SHIFT, 6, *day_span) == "Present",
			str(_status_for(DEFAULT_SHIFT, 6, *day_span)),
		)
		ok(
			"Exactly the half-day threshold on one half is Half Day",
			_status_for(DEFAULT_SHIFT, 4, *day_first) == "Half Day",
			str(_status_for(DEFAULT_SHIFT, 4, *day_first)),
		)
		ok(
			"Below the absent threshold is Absent",
			_status_for(DEFAULT_SHIFT, 1, *day_short) == "Absent",
			str(_status_for(DEFAULT_SHIFT, 1, *day_short)),
		)

	finally:
		_cleanup(employee)
		frappe.db.commit()

	failures = [r for r in results if r[0] == "FAIL"]
	print("")
	print("=" * 72)
	print(
		"TOTAL {0}    PASSED {1}    FAILED {2}".format(
			len(results), len(results) - len(failures), len(failures)
		)
	)
	print("=" * 72)
	if failures:
		print("")
		for _, name, detail in failures:
			print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
	print("")
	return len(failures)
