import frappe
from frappe.utils import getdate, nowdate, add_days, get_first_day, get_last_day
from datetime import datetime, timedelta

def set_status(self, method):
    if not self.in_time and not self.out_time: 
        from valence.api import get_offday_status     
        if not self.in_time and not self.out_time:        
            att_status = get_offday_status(self.employee,self.attendance_date,self.name)
            if att_status:
                self.db_set('status',att_status)       
            else:
                self.status = "No punch"
    elif not self.in_time:
        self.status = "In Mispunch"
    elif not self.out_time:
        self.status = "Out Mispunch"
    elif self.in_time and self.out_time:
        
        FMT = "%Y-%m-%d %H:%M:%S"

        if isinstance(self.in_time, str):
            in_time = datetime.strptime(self.in_time, FMT)
        else:
            in_time = self.in_time

        if isinstance(self.out_time, str):
            out_time = datetime.strptime(self.out_time, FMT)
        else:
            out_time = self.out_time

        # Get total seconds worked
        duration_seconds = (out_time - in_time).total_seconds()

        # Convert to decimal hours
        hours = round(duration_seconds / 3600, 1)  # One digit after point
        if not self.working_hours:
            self.db_set('working_hours',hours)

        
        # Get shift thresholds
        shift = frappe.get_doc("Shift Type", self.shift)
        half_day_threshold = shift.working_hours_threshold_for_half_day or 0
        absent_threshold = shift.working_hours_threshold_for_absent or 0

        # Decide status based on thresholds
        if hours < absent_threshold:
            self.db_set('status', 'Absent')
        elif hours < half_day_threshold:
            self.db_set('status', 'Half Day')
        else:
            self.db_set('status', 'Present')


def set_short_leave_count(self, method):

    # Consider "after submit" logic if doc is submitted
    is_after_submit = self.docstatus == 1

    #if is_after_submit & working hours not set
    if is_after_submit and not self.working_hours:
        if self.in_time and self.out_time:
            FMT = "%Y-%m-%d %H:%M:%S"

            if isinstance(self.in_time, str):
                in_time = datetime.strptime(self.in_time, FMT)
            else:
                in_time = self.in_time

            if isinstance(self.out_time, str):
                out_time = datetime.strptime(self.out_time, FMT)
            else:
                out_time = self.out_time

            # Get total seconds worked
            duration_seconds = (out_time - in_time).total_seconds()

            # Convert to decimal hours
            hours = round(duration_seconds / 3600, 1)  # One digit after point
            
            self.db_set('working_hours',hours)

            # Get shift thresholds
            shift = frappe.get_doc("Shift Type", self.shift)
            half_day_threshold = shift.working_hours_threshold_for_half_day or 0
            absent_threshold = shift.working_hours_threshold_for_absent or 0

            # Decide status based on thresholds
            if hours < absent_threshold:
                self.db_set('status', 'Absent')
            elif hours < half_day_threshold:
                self.db_set('status', 'Half Day')
            else:
                self.db_set('status', 'Present')
    
    # Check if late coming rules should be applied
    use_late_coming_rules = frappe.db.get_single_value("Attendance Settings", "use_late_coming_rules")
    
    # If late coming rules are not enabled, skip custom logic
    if not use_late_coming_rules:
        return

    # Store the original short leave count before any changes
    original_short_leave_count = self.custom_short_leave_count if hasattr(self, 'custom_short_leave_count') else None
    
    if is_first_attendance_of_month(self):
        self.db_set("custom_short_leave_count",frappe.db.get_single_value("Attendance Settings", 'short_leave_in_month'))
    
    else:
        # Get the most recent attendance record for this employee EXCEPT the current one
        previous_attendance = frappe.get_list("Attendance", 
                               filters={
                                   'employee': self.employee,
                                   'name': ['!=', self.name]  # Exclude current document
                               },
                               fields=['custom_short_leave_count','name'], 
                               order_by='modified desc', 
                               limit_page_length=1)
        
        if previous_attendance and len(previous_attendance) > 0:
            self.db_set("custom_short_leave_count", previous_attendance[0].get('custom_short_leave_count'))
            
            
        else:
            # If no previous record found, use the default value
            self.db_set("custom_short_leave_count",frappe.db.get_single_value("Attendance Settings", 'short_leave_in_month'))
    
    # if short leave count becomes 0 then return no next steps will be followed
    if self.custom_short_leave_count <= 0:
        return
    
    # Store the current short leave count after initial assignment
    current_short_leave_count = self.custom_short_leave_count
    
    # Get shift times
    shift_start_time = frappe.db.get_value("Shift Type", self.shift, 'start_time') 
    # check_in_before_shift_start_time = frappe.db.get_value("Shift Type", self.shift, 'begin_check_in_before_shift_start_time') 
    # shift_start_time = shift_start_time +timedelta(minutes=check_in_before_shift_start_time)

    shift_end_time = frappe.db.get_value("Shift Type", self.shift, 'end_time')
    # check_out_after_shift_end_time = frappe.db.get_value("Shift Type", self.shift, 'allow_check_out_after_shift_end_time') 
    # shift_end_time = shift_end_time +timedelta(minutes=check_out_after_shift_end_time)
    
    in_time_diff = None
    out_time_diff = None
    deduction_applied = False
    
    # Convert in_time to get timedelta
    if self.in_time:
        if isinstance(self.in_time, str):
            in_time = datetime.strptime(self.in_time, "%Y-%m-%d %H:%M:%S")
            
        else:
            in_time = self.in_time
        in_time_timedelta = timedelta(hours=in_time.hour, minutes=in_time.minute, seconds=in_time.second)
        
        # Convert shift_start_time to timedelta if it's not already
        if not isinstance(shift_start_time, timedelta):
            
            shift_start_hours, shift_start_minutes, shift_start_seconds = shift_start_time.hour, shift_start_time.minute, shift_start_time.second
            shift_start_timedelta = timedelta(hours=shift_start_hours, minutes=shift_start_minutes, seconds=shift_start_seconds)
        else:
            
            shift_start_timedelta = shift_start_time

        if in_time_timedelta > shift_start_timedelta:
            in_time_diff = in_time_timedelta - shift_start_timedelta
            # Subtract 30 minutes only if in_time_diff > 0
            in_time_diff -= timedelta(minutes=30)

            # Ensure result is not negative
            if in_time_diff.total_seconds() < 0:
                in_time_diff = timedelta(0)
        else:
            in_time_diff = timedelta(0)
   
    # Convert out_time to get timedelta
    if self.out_time:
        if isinstance(self.out_time, str):
            out_time = datetime.strptime(self.out_time, "%Y-%m-%d %H:%M:%S")
        else:
            out_time = self.out_time
        
        out_time_timedelta = timedelta(hours=out_time.hour, minutes=out_time.minute, seconds=out_time.second)
        
        # Convert shift_end_time to timedelta if it's not already
        if not isinstance(shift_end_time, timedelta):
            shift_end_hours, shift_end_minutes, shift_end_seconds = shift_end_time.hour, shift_end_time.minute, shift_end_time.second
            shift_end_timedelta = timedelta(hours=shift_end_hours, minutes=shift_end_minutes, seconds=shift_end_seconds)
        else:
            shift_end_timedelta = shift_end_time
            
        out_time_diff = shift_end_timedelta - out_time_timedelta
    
    # Get short leave rules
    short_leave_list = frappe.db.sql(""" 
                                    select time_period_1, time_period_2, deduction_in_short_leave
                                    from `tabShort Leave Logic`
                                    """, as_dict=True)   
    
    # Apply short leave deductions
    for row in short_leave_list:
        start = row["time_period_1"]
        end = row["time_period_2"]
        
        # Check if either in_time or out_time falls within the short leave period
        if (in_time_diff and start <= in_time_diff <= end) or (out_time_diff and start <= out_time_diff <= end):
            # frappe.throw(str(row['deduction_in_short_leave']))
            deduction = row["deduction_in_short_leave"]
            before_deduction = self.custom_short_leave_count
            self.custom_short_leave_count = self.custom_short_leave_count - deduction
            deduction_applied = True
            
            # Update the status directly in the database if after submission
            if is_after_submit and  self.custom_short_leave_count > 0 :
                
                self.db_set('status','Present With Short Leave')
                
                self.db_set('custom_short_leave_count',self.custom_short_leave_count)
                
                # # Check if this Attendance record exists and is submitted
                # if frappe.db.exists("Attendance", self.name):
                #     # Fetch the submitted document
                #     original_doc = frappe.get_doc("Attendance", self.name)
                    
                #     if original_doc.docstatus == 1:
                        
                #         # Cancel the doc
                #         original_doc.cancel()

                #         # Capture all field values before deleting
                #         data_to_recreate = original_doc.as_dict()

                #         # Delete the cancelled doc
                #         frappe.delete_doc("Attendance", self.name)

                #         # Remove system fields before recreating
                #         data_to_recreate.pop("name", None)
                #         data_to_recreate["status"] = "Present With Short Leave"
                #         data_to_recreate["docstatus"] = 0  # Draft
                #         data_to_recreate["custom_short_leave_count"] = self.custom_short_leave_count  # explicitly preserve it

                #         # Recreate the Attendance doc
                #         new_attendance = frappe.new_doc("Attendance")
                #         new_attendance.update(data_to_recreate)
                #         new_attendance.insert()
            

            # Create Short Leave Ledger entry
            create_short_leave_ledger_entry(
                self.employee,
                self.employee_name,
                self.attendance_date,
                deduction,
                self.custom_short_leave_count
            )

            # Check if short leave count is zero or less and set status to "Half Day"
            if self.custom_short_leave_count <= 0:
                self.custom_short_leave_count = 0
                
                if is_after_submit:
                    
                    self.db_set('status','Half Day')
                    self.db_set('custom_short_leave_count',self.custom_short_leave_count)                    
                else:
                    self.status = "Half Day"
                    
                # Set leave type based on priority and available balance
                leave_type = get_leave_type_by_priority(self.employee, self.attendance_date)
                
                if is_after_submit:
                    
                    self.db_set('leave_type',leave_type)
                    self.db_set('half_day_status',"Present")         
                    self.db_set('docstatus',0)                               
                else:
                    self.leave_type = leave_type
                    self.half_day_status = "Present"

                if leave_type:
                    # Create a leave application
                    leave_application = frappe.new_doc("Leave Application")
                    leave_application.employee = self.employee
                    leave_application.leave_type = leave_type
                    leave_application.from_date = self.attendance_date
                    leave_application.to_date = self.attendance_date
                    leave_application.half_day = 1  # Set to 1 for half day
                    leave_application.half_day_date = self.attendance_date
                    leave_application.status = "Approved"  # You may want to set this to "Open" or another status
                    leave_application.total_leave_days = 0.5  # Half day
                    leave_application.description = "Automatically created due to short leave deduction"
                    
                    
                    # Save the leave application
                    leave_application.insert()
                    leave_application.submit()
                    
                    
                    # Link the leave application to the attendance record
                    if is_after_submit:
                        self.db_set("leave_application", leave_application.name)
                        self.db_set('docstatus',1)  
                    else:
                        self.leave_application = leave_application.name

                break # Exit the loop once we've hit zero

def is_first_attendance_of_month(self):
    # Get the attendance date
    att_date = self.attendance_date

    # Get first and last day of the same month
    month_start = get_first_day(att_date)
    month_end = get_last_day(att_date)
    
    # Count how many attendances already exist for this employee in the same month
    total = frappe.db.count("Attendance", {
        "employee": self.employee,
        "attendance_date": ["between", [month_start, month_end]]
    })
    
    # If count is 1, this is the first attendance in the month (the current one)
    is_first_in_month = total == 1
    return is_first_in_month

def create_short_leave_ledger_entry(employee, employee_name, date, deduction, remaining):
    """Create an entry in the Short Leave Ledger doctype"""

    if remaining <= 0:
        remaining = 0
    
    # Convert date string to datetime object if it's a string
    if isinstance(date, str):
        date_obj = datetime.strptime(date, "%Y-%m-%d")
    else:
        date_obj = date
    
    # Get current month name
    current_month = date_obj.strftime("%B")
    
    ledger = frappe.new_doc("Short Leave Ledger")
    ledger.month = current_month
    ledger.employee = employee
    ledger.employee_name = employee_name
    ledger.short_leave_date = date
    ledger.deduction_in_short_leave = deduction
    ledger.remaining_short_leave = remaining
    ledger.half_day = 1 if remaining <= 0 else 0
    
    # Save the document
    ledger.insert(ignore_permissions=True)
    ledger.save()

def get_leave_type_by_priority(employee, attendance_date):
    """
    Get leave type based on priority and available balance:
    1. Compensatory Off
    2. Sick Leave
    3. CL (Casual Leave)
    4. EL (Earned Leave)
    5. Leave Without Pay (default fallback)
    """
    leave_types_in_priority = [
        "Compensatory Off",
        "Sick Leave",
        "Casual Leave",  # CL
        "Earned Leave"   # EL
    ]
    
    for leave_type in leave_types_in_priority:
        # Check if employee has balance for this leave type
        balance = get_leave_balance(employee, leave_type, attendance_date)
        
        if balance > 0:
            return leave_type
    
    # If no leave balance found in any of the priority types, return Leave Without Pay
    return "Leave Without Pay"

def get_leave_balance(employee, leave_type, date):
    """Get the available leave balance for the employee for the specified leave type"""
    try:
        # Using Frappe's get_leave_balance_on
        from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on as get_balance
        balance = get_balance(employee, leave_type, date, consider_all_leaves_in_the_allocation_period=True)
        return balance
    except ImportError:
        # Alternative method if the import fails
        allocation = frappe.db.sql("""
            SELECT SUM(total_leaves_allocated) - IFNULL(
                (SELECT SUM(total_leave_days) 
                FROM `tabLeave Application` 
                WHERE employee = %s 
                AND leave_type = %s 
                AND docstatus = 1), 0
            ) as balance
            FROM `tabLeave Allocation` 
            WHERE employee = %s 
            AND leave_type = %s 
            AND docstatus = 1
            AND from_date <= %s AND to_date >= %s
        """, (employee, leave_type, employee, leave_type, date, date), as_dict=True)
        
        if allocation and len(allocation) > 0 and allocation[0].balance is not None:
            return float(allocation[0].balance)
        return 0
    
def process_attendance_offdays():

    today = nowdate()

    # Convert to date object
    today = datetime.strptime(today, "%Y-%m-%d").date()

    # Subtract one day to get yesterday
    yesterday = today - timedelta(days=1)

    # Convert back to string if needed
    yesterday = yesterday.strftime("%Y-%m-%d")

    
    attendance_records = frappe.get_all("Attendance", filters={
        "attendance_date": yesterday ,
        "status": "No punch"  # or filter however you want
    }, fields=["name", "employee", "attendance_date"])

    for record in attendance_records:
        try:
            frappe.call(
                "valence.api.get_offday_status",
                employee=record["employee"],
                attendance_date=record["attendance_date"],
                attendance=record["name"]
            )
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Attendance Status Update Failed")
    