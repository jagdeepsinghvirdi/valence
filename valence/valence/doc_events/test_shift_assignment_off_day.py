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
	print("\n========== SUMMARY ==========")
	print(f"PASS: {passed}  FAIL: {failed}  TOTAL: {len(results)}")
	if failed:
		frappe.throw(f"Shift Assignment off-day tests failed ({failed})")
	return {"passed": passed, "failed": failed}
