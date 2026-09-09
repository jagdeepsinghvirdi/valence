import frappe

from valence.valence.doc_events.shift_assignment import ALL_DAYS, OFF_DAY_FIELD


def execute():
	if not frappe.db.has_column("Shift Assignment", OFF_DAY_FIELD):
		return
	if not frappe.db.has_column("Shift Assignment", "shift_schedule_assignment"):
		return

	rows = frappe.get_all(
		"Shift Assignment",
		filters={
			"docstatus": ["<", 2],
			"shift_schedule_assignment": ["is", "set"],
			OFF_DAY_FIELD: ["is", "not set"],
		},
		fields=["name", "shift_schedule_assignment"],
	)
	if not rows:
		return

	schedules = {}
	off_days = {}
	updated = 0
	skipped = set()

	for row in rows:
		assignment = row.shift_schedule_assignment
		if assignment not in schedules:
			schedules[assignment] = frappe.db.get_value(
				"Shift Schedule Assignment", assignment, "shift_schedule"
			)

		schedule = schedules[assignment]
		if not schedule:
			continue

		if schedule not in off_days:
			off_days[schedule] = _off_day_for_schedule(schedule)

		off_day = off_days[schedule]
		if not off_day:
			skipped.add(schedule)
			continue

		frappe.db.set_value(
			"Shift Assignment", row.name, OFF_DAY_FIELD, off_day, update_modified=False
		)
		updated += 1

	print(f"Weekly Off Day backfilled on {updated} of {len(rows)} Shift Assignments")
	if skipped:
		print(f"Skipped schedules without exactly one off day: {', '.join(sorted(skipped))}")


def _off_day_for_schedule(schedule):
	repeat_on_days = {
		d.lower()
		for d in frappe.get_all(
			"Assignment Rule Day",
			filters={"parent": schedule, "parenttype": "Shift Schedule"},
			pluck="day",
		)
	}
	if not repeat_on_days:
		return None

	off_days = ALL_DAYS - repeat_on_days
	if len(off_days) != 1:
		return None

	return list(off_days)[0].capitalize()
