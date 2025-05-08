import frappe
from frappe import _
from hrms.hr.doctype.shift_type.shift_type import ShiftType as _ShiftType
from hrms.utils import get_date_range
from hrms.utils.holiday_list import get_holiday_dates_between
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

class ShiftType(_ShiftType):
    
	def get_dates_for_attendance(self, employee: str) -> list[str]:
		start_date, end_date = self.get_start_and_end_dates(employee)

		# No shift assignment found, no need to process absent attendance records
		if start_date is None:
			return []

		date_range = get_date_range(start_date, end_date)

		# Skip marking absent on holidays
		holiday_list = self.get_holiday_list(employee)
		holiday_dates = get_holiday_dates_between(holiday_list, start_date, end_date)
		
		# Skip dates with existing attendance
		marked_attendance_dates = self.get_marked_attendance_dates_between(employee, start_date, end_date)
		return sorted(set(date_range) - set(marked_attendance_dates))

    

    
    