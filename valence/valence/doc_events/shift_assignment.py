import frappe

ALL_DAYS = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"}
OFF_DAY_FIELD = "custom_off_day"


def after_migrate():
	ensure_off_day_field()
	ensure_shift_assignment_status_options()
	frappe.clear_cache()
	frappe.db.commit()


def ensure_shift_assignment_status_options():
	"""Ensure 'Left' is an available status option on Shift Assignment."""
	name = "Shift Assignment-status-options"
	expected_options = "Active\nInactive\nLeft"

	if frappe.db.exists("Property Setter", name):
		current = frappe.db.get_value("Property Setter", name, "value")
		if current != expected_options:
			frappe.db.set_value("Property Setter", name, "value", expected_options)
	else:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"name": name,
				"doc_type": "Shift Assignment",
				"doctype_or_field": "DocField",
				"field_name": "status",
				"property": "options",
				"property_type": "Small Text",
				"value": expected_options,
				"module": "Valence",
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Shift Assignment")


def ensure_off_day_field():
	"""Weekly-off field on Shift Assignment — required by roster, calendar, and attendance."""
	if frappe.db.exists("Custom Field", {"dt": "Shift Assignment", "fieldname": OFF_DAY_FIELD}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Shift Assignment",
			"module": "Valence",
			"label": "Weekly Off Day",
			"fieldname": OFF_DAY_FIELD,
			"fieldtype": "Select",
			"options": "\nSunday\nMonday\nTuesday\nWednesday\nThursday\nFriday\nSaturday",
			"insert_after": "shift_type",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"description": (
				"Employee weekly off weekday. Auto-filled from Shift Schedule Repeat On Days "
				"when a schedule is linked; otherwise set it manually."
			),
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Shift Assignment")


def set_weekly_off_from_schedule(doc, method=None):
	"""Fill Weekly Off Day from the linked Shift Schedule, without crashing if the field is missing."""
	if not doc.meta.has_field(OFF_DAY_FIELD):
		return
	if doc.get(OFF_DAY_FIELD):
		return
	if not doc.shift_schedule_assignment:
		return
	shift_schedule = frappe.db.get_value(
		"Shift Schedule Assignment", doc.shift_schedule_assignment, "shift_schedule"
	)
	if not shift_schedule:
		return

	repeat_on_days = {
		d.lower()
		for d in frappe.get_all(
			"Assignment Rule Day", filters={"parent": shift_schedule}, pluck="day"
		)
	}
	off_days = ALL_DAYS - repeat_on_days

	if len(off_days) == 1:
		doc.set(OFF_DAY_FIELD, list(off_days)[0].capitalize())
	elif len(off_days) > 1:
		# Field only supports one off day — flag rather than silently pick one
		frappe.throw(
			f"Shift Schedule has {len(off_days)} off days, but Shift Assignment only supports "
			"one weekly off day. Please select exactly one day off in Repeat On Days."
		)
