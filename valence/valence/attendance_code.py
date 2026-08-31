from frappe.utils import flt

NON_REPORTABLE_STATUSES = {"Mispunch", "No punch"}
WORKED_STATUSES = {"Present", "Work From Home", "Present With Short Leave"}

ON_DUTY_STATUS = "On Duty"
ON_DUTY_CODE = "TT"
PRESENT_CODE = "P"
ABSENT_CODE = "A"
LWP_CODE = "L"

DOUBLE_FULL_FACTOR = 2.0
DOUBLE_HALF_FACTOR = 1.5

LEAVE_CODES = {
	"earned leave": "EL",
	"casual leave": "CL",
	"sick leave": "SL",
	"leave without pay": "L",
	"compensatory off": "CO",
}

WEEKLY_OFF_CODES = {
	"idle": "WO",
	"half": "PAW",
	"full": "PWO",
	"double_half": "2PAW",
	"double": "2PWO",
	"compose_leave": False,
}

HOLIDAY_CODES = {
	"idle": "H",
	"half": "HP/A",
	"full": "HP",
	"double_half": "2HP/A",
	"double": "2HP",
	"compose_leave": True,
}

NORMAL_CODES = {
	"full": PRESENT_CODE,
	"double_half": "2P/A",
	"double": "2P",
}


def get_attendance_code(attendance, context=None):
	doc = _as_dict(attendance)
	if not doc:
		return None

	status = doc.get("status")
	if not status or status in NON_REPORTABLE_STATUSES:
		return None

	context = context or {}
	day_type = _day_type(doc, context)

	if day_type == "Weekly Off":
		return _offday_code(doc, context, WEEKLY_OFF_CODES)

	if day_type == "Holiday":
		return _offday_code(doc, context, HOLIDAY_CODES)

	return _normal_code(doc, context)


def _as_dict(attendance):
	if isinstance(attendance, dict):
		return attendance
	if hasattr(attendance, "as_dict"):
		return attendance.as_dict()
	return None


def _day_type(doc, context):
	if "day_type" in context:
		return context.get("day_type")

	status = doc.get("status")
	if status == "Weekly Off":
		return "Weekly Off"
	if status == "Holiday":
		return "Holiday"

	from valence.api import get_day_type

	return get_day_type(doc.get("employee"), doc.get("attendance_date"))


def _offday_code(doc, context, codes):
	hours = flt(doc.get("working_hours"))

	if not _is_worked(doc) or hours <= 0:
		if codes.get("compose_leave"):
			leave_code = _leave_code(doc.get("leave_type"))
			if leave_code:
				return "{0}/{1}".format(leave_code, codes["idle"])
		return codes["idle"]

	factor = _double_factor(doc, context)
	if factor >= DOUBLE_FULL_FACTOR:
		return codes["double"]
	if factor >= DOUBLE_HALF_FACTOR:
		return codes["double_half"]

	if hours >= _full_day_hours(context):
		return codes["full"]
	return codes["half"]


def _normal_code(doc, context):
	status = doc.get("status")

	if status == ON_DUTY_STATUS:
		return ON_DUTY_CODE

	if status == "Half Day":
		return _half_day_code(doc, context)

	if status == "On Leave":
		leave_code = _leave_code(doc.get("leave_type"))
		if not leave_code:
			return ABSENT_CODE
		if leave_code == LWP_CODE:
			return "{0}/{0}".format(LWP_CODE)
		return leave_code

	if status == "Absent":
		return ABSENT_CODE

	if not _is_worked(doc):
		return ABSENT_CODE

	factor = _double_factor(doc, context)
	if factor >= DOUBLE_FULL_FACTOR:
		return NORMAL_CODES["double"]
	if factor >= DOUBLE_HALF_FACTOR:
		return NORMAL_CODES["double_half"]
	return NORMAL_CODES["full"]


def _half_day_code(doc, context):
	leave_code = _leave_code(doc.get("leave_type"))
	worked_half = _worked_half(doc, context)

	if leave_code:
		if _worked_other_half(doc):
			return _ordered(PRESENT_CODE, leave_code, worked_half)
		return "{0}/{1}".format(leave_code, ABSENT_CODE)

	return _ordered(PRESENT_CODE, ABSENT_CODE, worked_half)


def _ordered(worked_token, other_token, worked_half):
	if worked_half == "Second Half":
		return "{0}/{1}".format(other_token, worked_token)
	return "{0}/{1}".format(worked_token, other_token)


def _worked_other_half(doc):
	if doc.get("half_day_status") == "Present":
		return True
	if doc.get("half_day_status") == "Absent":
		return False
	return bool(doc.get("in_time") and doc.get("out_time"))


def _is_worked(doc):
	if doc.get("status") in WORKED_STATUSES:
		return True
	return bool(doc.get("in_time") and doc.get("out_time"))


def _leave_code(leave_type):
	if not leave_type:
		return None

	key = leave_type.strip().lower()
	if key in LEAVE_CODES:
		return LEAVE_CODES[key]

	initials = "".join(word[0] for word in leave_type.split() if word)
	return initials.upper() or None


def _double_factor(doc, context):
	if "double_factor" in context:
		return flt(context.get("double_factor"))

	from valence.valence.doc_events.attendance import get_double_shift_factor

	return flt(get_double_shift_factor(doc.get("shift"), flt(doc.get("working_hours"))))


def _worked_half(doc, context):
	if "worked_half" in context:
		return context.get("worked_half")

	if not (doc.get("in_time") and doc.get("out_time")):
		return None

	from valence.valence.doc_events.attendance import get_worked_half

	return get_worked_half(doc.get("shift"), doc.get("in_time"), doc.get("out_time"))


def _full_day_hours(context):
	if "full_day_hours" in context:
		return flt(context.get("full_day_hours"))

	from valence.valence.doc_events.attendance import get_offday_full_day_hours

	return flt(get_offday_full_day_hours())
