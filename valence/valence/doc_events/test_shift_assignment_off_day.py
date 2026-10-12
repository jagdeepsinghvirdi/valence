"""Automated checks for Shift Assignment weekly-off field. Run:
  bench --site valence.localhost execute valence.valence.doc_events.test_shift_assignment_off_day.run
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	from valence.valence.doc_events.shift_assignment import (
		OFF_DAY_FIELD,
		ensure_off_day_field,
		set_weekly_off_from_schedule,
	)

	ensure_off_day_field()

	ok(
		"custom_off_day custom field exists",
		bool(
			frappe.db.exists(
				"Custom Field", {"dt": "Shift Assignment", "fieldname": OFF_DAY_FIELD}
			)
		),
	)
	ok(
		"Shift Assignment has custom_off_day column",
		frappe.db.has_column("Shift Assignment", OFF_DAY_FIELD),
	)
	ok(
		"Shift Assignment meta has custom_off_day",
		frappe.get_meta("Shift Assignment").has_field(OFF_DAY_FIELD),
	)

	# Validate hook must not crash when the field is empty
	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
	shift_type = frappe.db.get_value("Shift Type", {}, "name")
	if not shift_type:
		st = frappe.get_doc(
			{
				"doctype": "Shift Type",
				"name": "General",
				"start_time": "09:00:00",
				"end_time": "18:00:00",
			}
		)
		try:
			st.insert(ignore_permissions=True)
			shift_type = st.name
		except Exception:
			shift_type = frappe.db.get_value("Shift Type", {}, "name")
	ok("Employee exists for save test", bool(employee), employee or "NONE")
	ok("Shift Type exists for save test", bool(shift_type), shift_type or "NONE")

	if employee and shift_type:
		doc = frappe.new_doc("Shift Assignment")
		doc.employee = employee
		doc.shift_type = shift_type
		doc.start_date = nowdate()
		doc.status = "Active"
		try:
			set_weekly_off_from_schedule(doc)
			threw = False
			err = ""
		except AttributeError as e:
			threw = True
			err = str(e)
		except Exception as e:
			# Other validation errors are OK as long as it's not the missing-field crash
			threw = "custom_off_day" in str(e) and "has no attribute" in str(e)
			err = str(e)
		ok(
			"set_weekly_off_from_schedule does not raise AttributeError",
			not threw,
			err[:160],
		)

		doc.custom_off_day = "Sunday"
		ok("Weekly Off Day can be set on the document", doc.custom_off_day == "Sunday")

		# Save should succeed with the field present
		saved = True
		err = ""
		try:
			# Avoid overlapping assignments in test data
			existing = frappe.get_all(
				"Shift Assignment",
				filters={
					"employee": employee,
					"start_date": ["<=", getdate()],
					"docstatus": ["<", 2],
				},
				or_filters=[["end_date", ">=", getdate()], ["end_date", "is", "not set"]],
				pluck="name",
			)
			if existing:
				ok(
					"Shift Assignment form can hold custom_off_day (skipped live save — overlap)",
					True,
					f"existing={existing[:3]}",
				)
			else:
				doc.insert(ignore_permissions=True)
				ok(
					"Shift Assignment saved with Weekly Off Day",
					frappe.db.get_value("Shift Assignment", doc.name, OFF_DAY_FIELD) == "Sunday",
					doc.name,
				)
				frappe.delete_doc("Shift Assignment", doc.name, force=1, ignore_permissions=True)
		except Exception as e:
			saved = "has no attribute" not in str(e)
			err = str(e)[:200]
			ok("Shift Assignment save does not crash on custom_off_day", saved, err)

	passed = sum(1 for s, _, _ in results if s == "PASS")
	failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== SUMMARY (Weekly Off) ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")

	left_results = run_left_tests()
	results.extend(left_results)

	roster_oct_results = run_roster_left_october_regression_tests()
	results.extend(roster_oct_results)

	total_passed = sum(1 for s, _, _ in results if s == "PASS")
	total_failed = sum(1 for s, _, _ in results if s == "FAIL")
	print("\n========== TOTAL SUMMARY ==========")
	print(f"PASS: {total_passed}  FAIL: {total_failed}  TOTAL: {len(results)}")
	if total_failed:
		frappe.throw(f"Shift Assignment tests failed ({total_failed})")
	return {"passed": total_passed, "failed": total_failed}


def run_left_tests():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	from valence.valence.doc_events.shift_assignment import (
		ensure_optional_shift_type,
		ensure_shift_assignment_status_options,
	)
	from valence.api import get_applicable_shift, get_applicable_shift_assignment
	from valence.valence.override.whitelisted_method.roster import get_events

	# 1. Status options check
	ensure_shift_assignment_status_options()
	ensure_optional_shift_type()

	prop_setter = frappe.db.get_value(
		"Property Setter",
		"Shift Assignment-status-options",
		["value"],
		as_dict=True,
	)
	ok(
		"Shift Assignment-status-options Property Setter exists",
		bool(prop_setter),
		str(prop_setter),
	)

	options_str = prop_setter.value if prop_setter else ""
	status_options = [opt.strip() for opt in options_str.split("\n") if opt.strip()]
	ok(
		"Status options contain 'Left'",
		"Left" in status_options,
		f"options={status_options}",
	)
	ok(
		"Status options preserve 'Active' and 'Inactive'",
		"Active" in status_options and "Inactive" in status_options,
		f"options={status_options}",
	)

	# 2. Pick an existing active employee and shift type (no new Employee creation required)
	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
	shift_type = frappe.db.get_value("Shift Type", {}, "name")
	if not shift_type:
		st = frappe.get_doc(
			{
				"doctype": "Shift Type",
				"name": "General Test Shift",
				"start_time": "09:00:00",
				"end_time": "18:00:00",
			}
		)
		st.insert(ignore_permissions=True)
		shift_type = st.name

	ok("Active Employee available for Left test", bool(employee), employee or "NONE")
	ok("Shift Type available for Left test", bool(shift_type), shift_type or "NONE")

	if not (employee and shift_type):
		return results

	# Record original employee status to ensure it remains unchanged
	emp_original_status = frappe.db.get_value("Employee", employee, "status")

	# Dates for test scenario
	base_start = "2026-09-01"
	mid_date = "2026-09-15"
	before_date = "2026-09-10"
	after_date = "2026-09-20"
	month_end = "2026-09-30"

	# Cleanup any existing test assignments on these exact test dates for this employee
	existing_test_sa = frappe.get_all(
		"Shift Assignment",
		filters={"employee": employee, "start_date": ["in", [base_start, mid_date]]},
		pluck="name",
	)
	for sa_name in existing_test_sa:
		try:
			doc = frappe.get_doc("Shift Assignment", sa_name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Shift Assignment", sa_name, force=1, ignore_permissions=True)
		except Exception:
			pass

	# 3. Create & submit prior Active assignment (base_start to mid_date - 1)
	sa_active = frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"shift_type": shift_type,
			"start_date": base_start,
			"end_date": "2026-09-14",
			"status": "Active",
		}
	)
	sa_active.insert(ignore_permissions=True)
	sa_active.submit()
	ok("Prior Active Shift Assignment created & submitted", sa_active.docstatus == 1, sa_active.name)

	# 4. Create & submit Left Shift Assignment starting mid-month
	sa_left = frappe.new_doc("Shift Assignment")
	sa_left.employee = employee
	sa_left.shift_type = shift_type
	sa_left.start_date = mid_date
	sa_left.status = "Left"

	try:
		sa_left.insert(ignore_permissions=True)
		sa_left.submit()
		ok("Shift Assignment with status 'Left' saved and submitted successfully", sa_left.docstatus == 1, sa_left.name)
	except Exception as e:
		ok("Shift Assignment with status 'Left' saved and submitted successfully", False, str(e))

	# 5. Reload & Persistence check
	if sa_left.name:
		sa_reloaded = frappe.get_doc("Shift Assignment", sa_left.name)
		ok("Left status persists on reload/reopen", sa_reloaded.status == "Left", f"status={sa_reloaded.status}")

	# 6. Shift resolution checks
	shift_before = get_applicable_shift(employee, before_date)
	ok("Date before Left (2026-09-10) resolves to active shift", shift_before == shift_type, str(shift_before))

	shift_on_left = get_applicable_shift(employee, mid_date)
	shift_after_left = get_applicable_shift(employee, after_date)
	ok("Date on Left (2026-09-15) resolves to None", shift_on_left is None, str(shift_on_left))
	ok("Date after Left (2026-09-20) resolves to None", shift_after_left is None, str(shift_after_left))

	# 7. Roster check: get_events reflects Left for applicable dates
	roster_events = get_events(base_start, month_end, {"name": employee}, {})
	emp_events = roster_events.get(employee, [])
	left_event_dates = {
		ev.get("holiday_date")
		for ev in emp_events
		if ev.get("description") == "Left"
	}
	ok("Roster returns Left events starting 2026-09-15", mid_date in left_event_dates, f"count={len(left_event_dates)}")
	ok("Roster returns Left events through end of month (2026-09-30)", month_end in left_event_dates, f"total={len(left_event_dates)}")
	ok("Dates before Left (2026-09-10) are NOT marked Left in Roster", before_date not in left_event_dates and base_start not in left_event_dates)

	# 8. Record integrity checks: Employee status and prior Shift Assignment unchanged
	emp_current_status = frappe.db.get_value("Employee", employee, "status")
	ok("Employee status remains unchanged", emp_current_status == emp_original_status, f"status={emp_current_status}")

	prior_sa_status = frappe.db.get_value("Shift Assignment", sa_active.name, ["docstatus", "status"], as_dict=True)
	ok(
		"Prior Shift Assignment remains intact",
		prior_sa_status and prior_sa_status.docstatus == 1 and prior_sa_status.status == "Active",
		str(prior_sa_status),
	)

	# 9. Clean up test records
	try:
		if sa_left.name and frappe.db.exists("Shift Assignment", sa_left.name):
			doc = frappe.get_doc("Shift Assignment", sa_left.name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Shift Assignment", sa_left.name, force=1, ignore_permissions=True)
		if sa_active.name and frappe.db.exists("Shift Assignment", sa_active.name):
			doc = frappe.get_doc("Shift Assignment", sa_active.name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Shift Assignment", sa_active.name, force=1, ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		pass

	return results


def run_roster_left_october_regression_tests():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	from valence.valence.doc_events.shift_assignment import (
		ensure_optional_shift_type,
		ensure_shift_assignment_status_options,
	)
	from valence.valence.override.whitelisted_method.roster import get_events

	ensure_shift_assignment_status_options()
	ensure_optional_shift_type()

	shift_type = frappe.db.get_value("Shift Type", {}, "name")
	company = frappe.db.get_value("Company", {}, "name")
	if not shift_type:
		ok("Shift Type available for regression test", False, "No Shift Type found")
		return results

	left_start = "2026-09-20"
	oct_start = "2026-10-01"
	oct_end = "2026-10-31"

	created_records = []  # Tracks only records created by this test: (doctype, docname, is_submitted)

	try:
		# 1. Create a dedicated synthetic test employee (isolates test, touches no sample data)
		synth_emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "ZZ_SynthTest",
				"last_name": "RosterLeft",
				"gender": "Prefer not to say",
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2020-01-01",
				"status": "Active",
				"company": company,
			}
		)
		synth_emp.insert(ignore_permissions=True)
		created_records.append(("Employee", synth_emp.name, False))
		employee = synth_emp.name
		ok("Dedicated synthetic test employee created", bool(employee), employee)

		# 2. Create & submit Left assignment starting on 2026-09-20 with no end date and no Shift Type
		sa_left = frappe.new_doc("Shift Assignment")
		sa_left.employee = employee
		sa_left.start_date = left_start
		sa_left.status = "Left"
		sa_left.shift_type = None
		sa_left.end_date = None
		sa_left.insert(ignore_permissions=True)
		sa_left.submit()
		created_records.append(("Shift Assignment", sa_left.name, True))
		ok(
			"Left assignment starting 2026-09-20 (no end date, no Shift Type) submitted",
			sa_left.docstatus == 1 and sa_left.shift_type is None,
			sa_left.name,
		)

		# 3. Query Roster for October 2026
		roster_events = get_events(oct_start, oct_end, {"name": employee}, {})
		emp_events = roster_events.get(employee, [])

		# 4. Verify malformed Left shift event is excluded
		left_shift_events = [ev for ev in emp_events if ev.get("status") == "Left"]
		ok(
			"Malformed Left shift event is excluded from October roster",
			len(left_shift_events) == 0,
			f"found={len(left_shift_events)}",
		)

		null_color_shifts = [
			ev for ev in emp_events if "name" in ev and ev.get("color") is None
		]
		ok(
			"No shift events with color: null in October roster",
			len(null_color_shifts) == 0,
			f"found={len(null_color_shifts)}",
		)

		# 5. Verify synthetic Left cells are retained for all 31 October dates
		oct_left_dates = {
			ev.get("holiday_date")
			for ev in emp_events
			if ev.get("description") == "Left"
		}
		ok(
			"Synthetic Left cells retained for all 31 October dates",
			len(oct_left_dates) == 31,
			f"count={len(oct_left_dates)}",
		)
		ok("October 1 is marked Left", "2026-10-01" in oct_left_dates)
		ok("October 31 is marked Left", "2026-10-31" in oct_left_dates)

		# 6. Clean up sa_left before testing active assignment
		doc_left = frappe.get_doc("Shift Assignment", sa_left.name)
		doc_left.cancel()
		frappe.delete_doc("Shift Assignment", sa_left.name, force=1, ignore_permissions=True)
		created_records.remove(("Shift Assignment", sa_left.name, True))

		# 7. Verify ordinary Active shifts and weekly offs remain intact on synthetic employee
		active_sa = frappe.new_doc("Shift Assignment")
		active_sa.employee = employee
		active_sa.shift_type = shift_type
		active_sa.start_date = "2026-10-01"
		active_sa.end_date = "2026-10-15"
		active_sa.status = "Active"
		active_sa.custom_off_day = "Sunday"
		active_sa.insert(ignore_permissions=True)
		active_sa.submit()
		created_records.append(("Shift Assignment", active_sa.name, True))
		ok("Ordinary Active shift submitted for October", active_sa.docstatus == 1, active_sa.name)

		roster_active = get_events(oct_start, oct_end, {"name": employee}, {})
		active_emp_events = roster_active.get(employee, [])

		active_events = [
			ev for ev in active_emp_events
			if ev.get("name") == active_sa.name and ev.get("status") == "Active"
		]
		ok("Active shift event is retained in October roster", len(active_events) == 1, f"found={len(active_events)}")
		if active_events:
			ok("Active shift has non-null color", active_events[0].get("color") is not None, f"color={active_events[0].get('color')}")
			ok("Active shift has correct shift_type", active_events[0].get("shift_type") == shift_type)

		holiday_wo_events = [
			ev for ev in active_emp_events
			if "holiday" in ev
		]
		ok("Holiday / Weekly off events are retained and not filtered", len(holiday_wo_events) > 0, f"count={len(holiday_wo_events)}")

	finally:
		# Cleanup only records created by this test; report any cleanup failures
		for doctype, docname, is_submitted in reversed(created_records):
			try:
				if frappe.db.exists(doctype, docname):
					if is_submitted and frappe.db.get_value(doctype, docname, "docstatus") == 1:
						doc = frappe.get_doc(doctype, docname)
						doc.cancel()
					frappe.delete_doc(doctype, docname, force=1, ignore_permissions=True)
			except Exception as cleanup_err:
				ok(f"Cleanup of {doctype} {docname}", False, str(cleanup_err))
		frappe.db.commit()

	return results
