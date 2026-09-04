# Copyright (c) 2026, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint, flt, getdate


def get_attendance_code(attendance, context=None):
	"""
	Derives the standardized attendance code for an attendance record or dict.

	Target codes:
	- Weekly Off Work:
	    PWO   (Full day work on weekly off)
	    PAW   (Half day work on weekly off)
	    2PWO  (Double shift full day on weekly off)
	    2PAW  (Double shift half day on weekly off)
	    WO    (Idle weekly off)
	- Holiday Work:
	    HP    (Full day work on holiday)
	    HP/A  (Half day work on holiday)
	    2HP   (Double shift full day on holiday)
	    2HP/A (Double shift half day on holiday)
	    H     (Idle holiday)
	- Normal Working Day:
	    P     (Full day present)
	    P/A   (Half day present)
	    2P    (Double shift full day on normal day)
	    2P/A  (Double shift half day on normal day)
	    A     (Absent)
	"""
	if not attendance:
		return ""

	doc = attendance if isinstance(attendance, dict) else attendance.as_dict()
	context = context or {}

	status = doc.get("status")
	working_hours = flt(doc.get("working_hours", 0.0))
	employee = doc.get("employee")
	attendance_date = doc.get("attendance_date")

	# 1. Resolve Day Type (Weekly Off, Holiday, Normal)
	day_type = context.get("day_type")
	if not day_type and employee and attendance_date:
		try:
			from valence.api import get_offday_status

			offday = get_offday_status(employee, attendance_date, None)
			if offday in ("Weekly Off", "Holiday"):
				day_type = offday
			else:
				day_type = "Normal"
		except Exception:
			day_type = "Normal"
	elif not day_type:
		if status == "Weekly Off":
			day_type = "Weekly Off"
		elif status == "Holiday":
			day_type = "Holiday"
		else:
			day_type = "Normal"

	# 2. Resolve Double Shift Factor (1 or 2)
	double_factor = 1
	if context.get("double_factor"):
		double_factor = cint(context.get("double_factor"))
	elif context.get("is_double_shift"):
		double_factor = 2
	elif doc.get("custom_double_shift") or doc.get("double_shift") or doc.get("double_shift_factor") == 2:
		double_factor = 2

	# 3. Offday full day hours threshold
	offday_full_hours = context.get("offday_full_day_hours")
	if offday_full_hours is None:
		try:
			offday_full_hours = flt(
				frappe.db.get_single_value("Attendance Settings", "offday_full_day_hours") or 6.0
			)
		except Exception:
			offday_full_hours = 6.0

	# 4. Determine if work was done (present / half day / working hours > 0)
	is_present = status in ("Present", "Work From Home", "On Duty")
	is_half_day = status == "Half Day"
	worked = is_present or is_half_day or (working_hours > 0)

	if not worked:
		if day_type == "Weekly Off":
			return "WO"
		elif day_type == "Holiday":
			return "H"
		elif status:
			return status
		return "A"

	# Determine if worked full day vs half day
	if day_type in ("Weekly Off", "Holiday"):
		if working_hours > 0:
			is_full = working_hours >= offday_full_hours
		else:
			is_full = is_present and not is_half_day
	else:
		if is_half_day:
			is_full = False
		elif is_present:
			is_full = True
		elif working_hours > 0:
			is_full = working_hours >= 8.0
		else:
			is_full = False

	# 5. Derive specific attendance code
	if day_type == "Weekly Off":
		if double_factor == 2:
			return "2PWO" if is_full else "2PAW"
		else:
			return "PWO" if is_full else "PAW"
	elif day_type == "Holiday":
		if double_factor == 2:
			return "2HP" if is_full else "2HP/A"
		else:
			return "HP" if is_full else "HP/A"
	else:
		if double_factor == 2:
			return "2P" if is_full else "2P/A"
		elif is_full:
			return "P"
		elif is_half_day or (0 < working_hours < 8.0):
			return "P/A"
		else:
			return status or "P"
