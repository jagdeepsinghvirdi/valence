import frappe
from frappe.utils import cint, flt, getdate

LEAVE_CODES = {
	"Casual Leave": "CL",
	"Sick Leave": "SL",
	"Earned Leave": "EL",
	"Compensatory Off": "CO",
	"Leave Without Pay": "LWP",
}

LWP_CODE = "LWP"


def _get_leave_code(leave_type):
	if not leave_type:
		return ""
	if leave_type in LEAVE_CODES:
		return LEAVE_CODES[leave_type]
	words = leave_type.strip().split()
	if words:
		return "".join(w[0].upper() for w in words if w)
	return leave_type[:2].upper()


def get_attendance_code(attendance, context=None):
	if not attendance:
		return None

	doc = attendance if isinstance(attendance, dict) else attendance.as_dict()
	context = context or {}

	status = doc.get("status")
	working_hours = flt(doc.get("working_hours", 0.0))
	employee = doc.get("employee")
	attendance_date = doc.get("attendance_date")
	leave_type = doc.get("leave_type")
	half_day_status = doc.get("half_day_status")
	in_time = doc.get("in_time")
	out_time = doc.get("out_time")
	attendance_request = doc.get("attendance_request")

	# 1. Resolve Day Type
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

	# 2. Resolve Double Shift Factor
	double_factor = 1.0
	if context.get("double_factor"):
		double_factor = flt(context.get("double_factor"))
	elif context.get("is_double_shift"):
		double_factor = 2.0
	elif doc.get("custom_double_shift") or doc.get("double_shift") or doc.get("double_shift_factor") == 2:
		double_factor = 2.0

	# 3. Offday full day hours threshold
	offday_full_hours = context.get("full_day_hours")
	if offday_full_hours is None:
		offday_full_hours = context.get("offday_full_day_hours")
	if offday_full_hours is None:
		try:
			offday_full_hours = flt(
				frappe.db.get_single_value("Attendance Settings", "offday_full_day_hours") or 6.0
			)
		except Exception:
			offday_full_hours = 6.0
	else:
		offday_full_hours = flt(offday_full_hours)

	# --- WEEKLY OFF ---
	if day_type == "Weekly Off":
		if status == "On Leave":
			return "WO"
		if working_hours > 0:
			if double_factor >= 2.0:
				return "2PWO"
			elif double_factor > 1.0:
				return "2PAW"
			elif working_hours >= offday_full_hours:
				return "PWO"
			else:
				return "PAW"
		if status == "Present" and working_hours == 0:
			if in_time and out_time:
				return "PWO"
		return "WO"

	# --- HOLIDAY ---
	if day_type == "Holiday":
		if status == "On Leave":
			if leave_type == "Compensatory Off":
				return "CO/H"
			return "H"
		if working_hours > 0:
			if double_factor >= 2.0:
				return "2HP"
			elif double_factor > 1.0:
				return "2HP/A"
			elif working_hours >= offday_full_hours:
				return "HP"
			else:
				return "HP/A"
		if status == "Present" and working_hours == 0:
			if in_time and out_time:
				return "HP"
		return "H"

	# --- NORMAL WORKING DAY ---
	if status in ("Mispunch", "No punch"):
		return None

	if double_factor >= 2.0:
		return "2P"
	elif double_factor > 1.0:
		return "2P/A"

	if status in ("Present", "Work From Home", "Present With Short Leave"):
		return "P"

	if status == "On Duty":
		return "TT"

	if status == "On Leave":
		if not leave_type:
			return "A"
		if leave_type == "Leave Without Pay":
			return "L/L"
		code = _get_leave_code(leave_type)
		return code or "A"

	if status == "Half Day":
		worked_half = context.get("worked_half", "First Half")
		req_reason = context.get("request_reason")
		has_punches = bool(in_time and out_time) or (working_hours > 0)

		if leave_type:
			l_code = "L" if leave_type == "Leave Without Pay" else _get_leave_code(leave_type)
			if half_day_status == "Absent" or not has_punches:
				return "{0}/A".format(l_code)
			if worked_half == "Second Half":
				return "{0}/P".format(l_code)
			return "P/{0}".format(l_code)

		if attendance_request and req_reason == "On Duty":
			if worked_half == "Second Half":
				return "TT/P"
			return "P/TT"

		if half_day_status == "Absent" or has_punches or working_hours > 0:
			if worked_half == "Second Half":
				return "A/P"
			return "P/A"

		return "P/A"

	if status == "Absent":
		return "A"

	if working_hours >= 8.0:
		return "P"
	elif working_hours > 0:
		return "P/A"

	return status or "A"
