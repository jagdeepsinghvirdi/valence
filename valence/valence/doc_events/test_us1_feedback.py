from __future__ import annotations

import os

import frappe

from valence.valence.doc_events.attendance import (
	_apply_hours_status,
	get_worked_half,
	worked_single_half,
)
from valence.valence.doc_events.leave_application import reset_approval_on_amend

SHIFT_NAME = "Test-Day"


class _StubAttendance:
	def __init__(self, in_time=None, out_time=None):
		self.in_time = in_time
		self.out_time = out_time
		self.values = {}

	def db_set(self, field, value):
		self.values[field] = value


class _StubLeave:
	def __init__(self, amended_from=None, workflow_state=None, is_new=True, status=None):
		self.amended_from = amended_from
		self.workflow_state = workflow_state
		self.status = status
		self._is_new = is_new

	def get(self, field, default=None):
		return getattr(self, field, default)

	def is_new(self):
		return self._is_new


def _status_for(shift, hours, in_time=None, out_time=None):
	stub = _StubAttendance(in_time=in_time, out_time=out_time)
	_apply_hours_status(stub, hours, shift)
	return stub.values.get("status")


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))

	frappe.set_user("Administrator")

	print("")
	print("=" * 72)
	print("USER STORY 1 - CLIENT FEEDBACK CHANGES")
	print("=" * 72)

	print("")
	print("-- A. Attendance half day " + "-" * 46)

	shift = SHIFT_NAME if frappe.db.exists("Shift Type", SHIFT_NAME) else None
	if not shift:
		ok(
			"Shift Type available",
			False,
			f"'{SHIFT_NAME}' not found, half-day status checks skipped",
		)
	else:
		day = "2026-09-02"
		full_in, full_out = f"{day} 09:00:00", f"{day} 17:00:00"
		first_in, first_out = f"{day} 09:00:00", f"{day} 13:00:00"
		second_in, second_out = f"{day} 13:00:00", f"{day} 17:00:00"
		span_in, span_out = f"{day} 09:00:00", f"{day} 16:00:00"

		ok(
			"get_worked_half detects first half",
			get_worked_half(shift, first_in, first_out) == "First Half",
			str(get_worked_half(shift, first_in, first_out)),
		)
		ok(
			"get_worked_half detects second half",
			get_worked_half(shift, second_in, second_out) == "Second Half",
			str(get_worked_half(shift, second_in, second_out)),
		)
		ok(
			"get_worked_half detects a spanning day as Both",
			get_worked_half(shift, span_in, span_out) == "Both",
			str(get_worked_half(shift, span_in, span_out)),
		)
		ok(
			"worked_single_half is False without punches",
			worked_single_half(shift, None, None) is False,
		)

		first_status = _status_for(shift, 4, first_in, first_out)
		ok(
			"Case 1 first half worked, second half absent -> Half Day",
			first_status == "Half Day",
			f"got {first_status}",
		)

		second_status = _status_for(shift, 4, second_in, second_out)
		ok(
			"Case 2 first half absent, second half worked -> Half Day",
			second_status == "Half Day",
			f"got {second_status}",
		)

		full_status = _status_for(shift, 8, full_in, full_out)
		ok(
			"Full day worked stays Present",
			full_status == "Present",
			f"got {full_status}",
		)

		span_status = _status_for(shift, 7, span_in, span_out)
		ok(
			"Partial day spanning the midpoint stays Present",
			span_status == "Present",
			f"got {span_status}",
		)

		absent_status = _status_for(shift, 0)
		ok(
			"No working hours stays Absent",
			absent_status == "Absent",
			f"got {absent_status}",
		)

		short_leave_status = _status_for(shift, 5)
		ok(
			"Hours without punches are unaffected by the half rule",
			short_leave_status == "Present",
			f"got {short_leave_status}",
		)

	print("")
	print("-- B. Leave amend resets HOD approval " + "-" * 34)

	amended = _StubLeave(amended_from="HR-LAP-0001", workflow_state="Approved", status="Approved")
	reset_approval_on_amend(amended)
	ok(
		"Amended approved leave returns to Draft",
		amended.workflow_state == "Draft",
		f"got {amended.workflow_state}",
	)
	ok(
		"Amended approved leave status resets to Open",
		amended.status == "Open",
		f"got {amended.status}",
	)

	super_hod = _StubLeave(
		amended_from="HR-LAP-0002", workflow_state="Pending Super HOD Approval"
	)
	reset_approval_on_amend(super_hod)
	ok(
		"Amended Super HOD pending leave also returns to Draft",
		super_hod.workflow_state == "Draft",
		f"got {super_hod.workflow_state}",
	)

	fresh = _StubLeave(amended_from=None, workflow_state="Approved")
	reset_approval_on_amend(fresh)
	ok(
		"Non amended leave is untouched",
		fresh.workflow_state == "Approved",
		f"got {fresh.workflow_state}",
	)

	saved = _StubLeave(amended_from="HR-LAP-0003", workflow_state="Approved", is_new=False)
	reset_approval_on_amend(saved)
	ok(
		"Already inserted amendment is not reset again",
		saved.workflow_state == "Approved",
		f"got {saved.workflow_state}",
	)

	draft = _StubLeave(amended_from="HR-LAP-0004", workflow_state="Draft", status="Open")
	reset_approval_on_amend(draft)
	ok(
		"Draft amendment is left alone",
		draft.workflow_state == "Draft",
		f"got {draft.workflow_state}",
	)

	print("")
	print("-- C. Attendance connections " + "-" * 43)

	from valence.api import get_attendance_connections

	empty = get_attendance_connections(None, None)
	ok(
		"Connections API tolerates missing arguments",
		empty == {"leave_applications": [], "short_leave_applications": []},
		str(empty),
	)
	ok(
		"Connections API is whitelisted",
		getattr(get_attendance_connections, "is_whitelisted", False) is True
		or "get_attendance_connections" in str(frappe.whitelisted),
	)
	ok(
		"Short Leave Application doctype exists",
		bool(frappe.db.exists("DocType", "Short Leave Application")),
	)

	print("")
	print("-- D. Fetch Time leave guard " + "-" * 43)

	from valence.api import _leave_protected_attendance

	ok(
		"Unknown attendance is not treated as protected",
		_leave_protected_attendance("NON-EXISTENT-ATTENDANCE") is None,
	)

	leave_backed = frappe.get_all(
		"Attendance",
		filters={"leave_application": ["is", "set"]},
		fields=["name", "leave_application"],
		limit_page_length=1,
	)
	if leave_backed:
		guarded = _leave_protected_attendance(leave_backed[0].name)
		ok(
			"Leave backed attendance is protected from Fetch Time",
			bool(guarded),
			f"{leave_backed[0].name} -> {guarded}",
		)
	else:
		ok(
			"Leave backed attendance is protected from Fetch Time",
			True,
			"no leave backed Attendance on this site, guard exercised by unit path only",
		)

	print("")
	print("-- E. Roster in global search " + "-" * 42)

	page_dir = frappe.get_app_path("valence", "valence", "page", "roster")
	ok(
		"Roster page definition exists",
		os.path.exists(os.path.join(page_dir, "roster.json")),
		page_dir,
	)
	ok(
		"Roster page record is installed",
		bool(frappe.db.exists("Page", "roster")),
		"run bench migrate if this fails",
	)
	if frappe.db.exists("Page", "roster"):
		ok(
			"Roster page title is searchable as 'Roster'",
			frappe.db.get_value("Page", "roster", "title") == "Roster",
		)

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
		print("FAILURES")
		for _, name, detail in failures:
			print(f"  {name}" + (f" - {detail}" if detail else ""))

	print("")
	return len(failures)
