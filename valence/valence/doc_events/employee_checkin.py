import frappe
from frappe.utils import add_days, get_datetime, getdate


def set_applicable_shift(doc, method=None):
	if doc.attendance or not doc.employee or not doc.time:
		return

	from valence.api import _shift_details_on, get_applicable_shift, get_attendance_punch_window

	punch_time = get_datetime(doc.time)
	punch_date = getdate(punch_time)

	candidates = [punch_date, add_days(punch_date, -1)]
	assigned = False
	for attendance_date in candidates:
		shift = get_applicable_shift(doc.employee, attendance_date)
		if not shift:
			continue
		assigned = True
		window_start, window_end = get_attendance_punch_window(doc.employee, attendance_date, shift)
		if window_start <= punch_time <= window_end:
			break
	else:
		if assigned:
			doc.shift = None
			doc.shift_start = None
			doc.shift_end = None
			doc.shift_actual_start = None
			doc.shift_actual_end = None
		return

	details = _shift_details_on(shift, getdate(attendance_date))
	if not details:
		return

	doc.shift = shift
	doc.offshift = 0
	doc.shift_start = details.start_datetime
	doc.shift_end = details.end_datetime
	doc.shift_actual_start = details.actual_start
	doc.shift_actual_end = details.actual_end
