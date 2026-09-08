import frappe
from frappe.utils import get_datetime, get_datetime_str
from datetime import datetime, timedelta
from frappe.utils import flt,cint, get_url_to_form, nowdate
from erpnext.accounts.utils import getdate
from email.utils import formataddr
from valence.valence.doc_events.attendance import set_status
# from frappe.utils import get_datetime
# from datetime import timedelta

def _as_timedelta(value):
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if hasattr(value, "hour"):
        return timedelta(hours=value.hour, minutes=value.minute, seconds=getattr(value, "second", 0) or 0)
    if isinstance(value, str):
        try:
            parts = [int(p) for p in value.split(":")]
            if len(parts) == 3:
                return timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])
            elif len(parts) == 2:
                return timedelta(hours=parts[0], minutes=parts[1])
        except Exception:
            pass
    return None


def _is_overnight_shift(shift_name):
    if not shift_name:
        return False
    times = frappe.db.get_value("Shift Type", shift_name, ["start_time", "end_time"])
    if not times or not times[0] or not times[1]:
        return False
    start = _as_timedelta(times[0])
    end = _as_timedelta(times[1])
    if not start or not end:
        return False
    return (end - start).total_seconds() < 0


def _get_shift_punch_window(shift_name, attendance_date):
    """
    Computes (start_datetime, end_datetime) for punch queries based on the Shift Type
    schedule and configured check-in / check-out buffers.
    """
    if isinstance(attendance_date, str):
        date_obj = getdate(attendance_date)
    else:
        date_obj = attendance_date

    day_start = datetime.combine(date_obj, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    if not shift_name:
        return day_start, day_end

    shift_doc = frappe.db.get_value(
        "Shift Type",
        shift_name,
        [
            "start_time",
            "end_time",
            "begin_check_in_before_shift_start_time",
            "allow_check_out_after_shift_end_time",
        ],
        as_dict=True,
    )
    if not shift_doc or not shift_doc.start_time or not shift_doc.end_time:
        return day_start, day_end

    start_delta = _as_timedelta(shift_doc.start_time)
    end_delta = _as_timedelta(shift_doc.end_time)
    if not start_delta or not end_delta:
        return day_start, day_end

    if (end_delta - start_delta).total_seconds() < 0:
        check_in_buf = cint(shift_doc.begin_check_in_before_shift_start_time)
        check_out_buf = cint(shift_doc.allow_check_out_after_shift_end_time)
        if check_out_buf <= 0:
            check_out_buf = 60

        window_start = day_start + start_delta - timedelta(minutes=check_in_buf)
        window_end = day_start + timedelta(days=1) + end_delta + timedelta(minutes=check_out_buf)
        return window_start, window_end

    return day_start, day_end


def get_checkin_window_end(employee, attendance_date, start_date, shift=None):
    """
    End of the check-in search window for an attendance date.

    Day shifts keep the calendar-day window. Overnight shifts (end time earlier than
    start time) extend into the next day so the out-punch after midnight is found.
    """
    default_end = start_date + timedelta(days=1)

    if not shift:
        shift = get_applicable_shift(employee, attendance_date)
    if not shift:
        return default_end

    times = frappe.db.get_value(
        "Shift Type",
        shift,
        ["start_time", "end_time", "allow_check_out_after_shift_end_time"],
        as_dict=True,
    )
    if not times or times.start_time is None or times.end_time is None:
        return default_end

    start_delta = _as_timedelta(times.start_time)
    end_delta = _as_timedelta(times.end_time)
    if start_delta is None or end_delta is None:
        return default_end

    if end_delta >= start_delta:
        return default_end

    buffer_minutes = cint(times.allow_check_out_after_shift_end_time) or 60
    return default_end + end_delta + timedelta(minutes=buffer_minutes)


@frappe.whitelist()
def get_employee_checkin_entries(employee, attendance_date, doc):
    # 1. Load the Attendance document first
    attendance_doc = frappe.get_doc("Attendance", doc)

    # Protect approved leave from being overwritten by fetch time
    if attendance_doc.leave_application or attendance_doc.status == "On Leave":
        leave_ref = attendance_doc.leave_application or attendance_doc.leave_type or "On Leave"
        return {
            "in_time": attendance_doc.in_time,
            "out_time": attendance_doc.out_time,
            "status": attendance_doc.status,
            "message": f"Skipped, approved leave ({leave_ref}) was not overwritten."
        }

    # 2. Convert string date to datetime objects and calculate shift window
    start_date = get_datetime(attendance_date)
    shift = attendance_doc.shift or get_applicable_shift(employee, attendance_date)
    end_date = get_checkin_window_end(employee, attendance_date, start_date, shift=shift)

    # 3. Fetch first and last check-ins
    in_time_doc = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start_date, end_date]]
        },
        fields=["time"],
        order_by="time asc",
        limit_page_length=1
    )

    out_time_doc = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start_date, end_date]]
        },
        fields=["time"],
        order_by="time desc",
        limit_page_length=1
    )
    # 4. Get the times
    if in_time_doc == out_time_doc:
        in_time = in_time_doc[0].time if in_time_doc else None
        out_time = None
    else:
        in_time = in_time_doc[0].time if in_time_doc else None
        out_time = out_time_doc[0].time if out_time_doc else None
    
    # 5. Update the values in memory first so set_status can calculate
    attendance_doc.in_time = in_time
    attendance_doc.out_time = out_time

    # 6. Manually update in_time and out_time in DB (since it's submitted)
    attendance_doc.db_set('in_time', in_time)
    attendance_doc.db_set('out_time', out_time)

    # 7. Run your status logic
    # Your set_status already uses db_set for status and working_hours,
    # so it will work fine on a submitted document.
    if in_time or out_time:
        set_status(attendance_doc, "validate")
    else:
        # If no punches, preserve approved attendance requests
        if attendance_doc.attendance_request or attendance_doc.status in ("Work From Home", "On Duty"):
            return {
                "in_time": in_time,
                "out_time": out_time,
                "status": attendance_doc.status,
                "message": f"Approved request ({attendance_doc.status}) was not overwritten."
            }

        from valence.valence.doc_events.attendance import resolve_no_punch_status

        resolve_no_punch_status(employee, attendance_date, attendance_doc.name)
        attendance_doc.reload()

    return {
        "in_time": in_time,
        "out_time": out_time,
        "status": attendance_doc.status
    }

@frappe.whitelist()
def get_attendance_connections(employee, attendance_date):
    if not employee or not attendance_date:
        return {"leave_applications": [], "short_leave_applications": []}

    leave_applications = frappe.get_list(
        "Leave Application",
        filters={
            "employee": employee,
            "docstatus": ["<", 2],
            "from_date": ["<=", attendance_date],
            "to_date": [">=", attendance_date],
        },
        fields=["name", "leave_type", "status"],
        order_by="from_date desc",
        ignore_permissions=False,
    )

    short_leave_applications = frappe.get_list(
        "Short Leave Application",
        filters={
            "employee": employee,
            "date": attendance_date,
            "docstatus": ["<", 2],
        },
        fields=["name", "short_leave_type", "status"],
        order_by="from_time asc",
        ignore_permissions=False,
    )

    return {
        "leave_applications": leave_applications,
        "short_leave_applications": short_leave_applications,
    }


def _leave_protected_attendance(attendance):
    row = frappe.db.get_value(
        "Attendance",
        attendance,
        ["status", "leave_application", "leave_type"],
        as_dict=True,
    )
    if not row:
        return None
    if row.leave_application:
        return row.leave_application
    if row.status == "On Leave":
        return row.leave_type or "On Leave"
    return None


@frappe.whitelist()
def get_employee_checkin_entries_multiple(employee, attendance_date, attendance):
    messages = []

    protected = _leave_protected_attendance(attendance)
    if protected:
        return {
            "attendance": attendance,
            "message": f"{attendance}: Skipped, approved leave ({protected}) was not overwritten.",
        }

    # Convert date safely
    if isinstance(attendance_date, str):
        date_obj = datetime.strptime(attendance_date, "%Y-%m-%d").date()
        start_date = get_datetime(attendance_date)
    else:
        date_obj = attendance_date
        start_date = get_datetime(attendance_date)

    shift = frappe.db.get_value("Attendance", attendance, "shift") or get_applicable_shift(employee, attendance_date)
    end_date = get_checkin_window_end(employee, attendance_date, start_date, shift=shift)

    # Fetch first check-in
    in_time_doc = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start_date, end_date]]
        },
        fields=["time"],
        order_by="time asc",
        limit_page_length=1
    )

    # Fetch last check-in
    out_time_doc = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start_date, end_date]]
        },
        fields=["time"],
        order_by="time desc",
        limit_page_length=1
    )

    if in_time_doc == out_time_doc:
        in_time = in_time_doc[0].time if in_time_doc else None
        out_time = None
    else:
        in_time = in_time_doc[0].time if in_time_doc else None
        out_time = out_time_doc[0].time if out_time_doc else None

    # ------------------------------------------------
    # Case 1: At least one punch exists
    # ------------------------------------------------
    if in_time or out_time:
        frappe.db.set_value(
            "Attendance",
            attendance,
            {
                "in_time": in_time,
                "out_time": out_time
            }
        )
        set_status(frappe.get_doc("Attendance", attendance), "validate")
        return {
            "attendance": attendance,
            "message": f"{attendance}: Check-in entries fetched successfully."
        }

    # ------------------------------------------------
    # Case 2: No punches → Holiday / Weekly Off / Absent
    # ------------------------------------------------

    current_att = frappe.db.get_value(
        "Attendance", attendance, ["status", "attendance_request"], as_dict=True
    )
    if current_att and (current_att.attendance_request or current_att.status in ("Work From Home", "On Duty")):
        return {
            "attendance": attendance,
            "message": f"{attendance}: Skipped, approved request ({current_att.status}) was not overwritten.",
        }

    from valence.valence.doc_events.attendance import resolve_no_punch_status

    status = resolve_no_punch_status(employee, date_obj, attendance)

    return {
        "attendance": attendance,
        "message": f"{attendance}: Marked as {status}."
    }


# @frappe.whitelist()
# def get_offday_status(employee, attendance_date,attendance):
    
#     from datetime import datetime
    
#     if isinstance(attendance_date, str):
#         date_obj = datetime.strptime(attendance_date, "%Y-%m-%d").date()
#     else:
#         date_obj = attendance_date
    
#     # Step 1: Check Holiday List
#     holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
#     if holiday_list:
#         if frappe.db.exists("Holiday", {"holiday_date": date_obj, "parent": holiday_list}):
#             holiday_doc = frappe.get_doc("Holiday List",holiday_list)

#             for holiday in holiday_doc.holidays:
#                 if attendance:
#                     if holiday.weekly_off:
#                         frappe.db.set_value("Attendance", attendance, {
#                         "status": "Weekly Off",
#                         "leave_type": None
#                         })
#                         frappe.db.commit()
#                         return "Weekly Off"
#                     else:
#                         frappe.db.set_value("Attendance", attendance, {
#                             "status": "Holiday",
#                             "leave_type": None
#                             })
#                         frappe.db.commit()
#                         return "Holiday"
   
#     # Step 2: Check Shift Assignment for weekly off

# shift_assignment = frappe.get_all(
#     "Shift Assignment",
#     filters={"employee": employee, "start_date": ["<=", date_obj]},
#     fields=["name", "shift_type", "custom_off_day", "end_date"]
# )
# valid_shift_assignments = [s for s in shift_assignment if not s["end_date"] or s["end_date"] >= date_obj]

# if valid_shift_assignments:
#     weekday = date_obj.strftime('%A')
#     if valid_shift_assignments[0]["custom_off_day"] == weekday:
#         if attendance:
#             frappe.db.set_value("Attendance", attendance, {"status": "Weekly Off", "leave_type": None})
#             frappe.db.commit()
#         return "Weekly Off"

def get_applicable_shift_assignment(employee, date_obj):
    """Single source of truth: the Shift Assignment covering employee/date, or None."""
    if not employee or not date_obj:
        return None

    date_obj = getdate(date_obj)

    rows = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "start_date": ["<=", date_obj],
            "docstatus": 1,
        },
        or_filters=[["end_date", ">=", date_obj], ["end_date", "is", "not set"]],
        fields=["name", "shift_type", "custom_off_day", "start_date", "end_date"],
        order_by="start_date desc, creation desc",
        limit_page_length=1,
    )

    return rows[0] if rows else None


def get_applicable_shift(employee, date_obj):
    """Applicable Shift Type for employee/date: Shift Assignment first, then default shift."""
    assignment = get_applicable_shift_assignment(employee, date_obj)
    if assignment and assignment.get("shift_type"):
        return assignment.get("shift_type")

    if not employee:
        return None

    return frappe.db.get_value("Employee", employee, "default_shift")


def _weekly_off_days_from_assignment(assignment):
    if not assignment:
        return set()

    raw = (assignment.get("custom_off_day") or "").strip()
    if not raw:
        return set()

    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def get_shift_weekly_off_days(employee, date_obj):
    if not frappe.db.has_column("Shift Assignment", "custom_off_day"):
        return set()

    return _weekly_off_days_from_assignment(
        get_applicable_shift_assignment(employee, date_obj)
    )


def get_day_type_map(employees, start_date, end_date):
    from frappe.utils import add_days

    employees = [e for e in (employees or []) if e]
    if not employees:
        return {}

    start = getdate(start_date)
    end = getdate(end_date)

    holiday_lists = {}
    company_defaults = {}
    for row in frappe.get_all(
        "Employee",
        filters={"name": ["in", employees]},
        fields=["name", "holiday_list", "company"],
    ):
        holiday_list = row.holiday_list
        if not holiday_list and row.company:
            if row.company not in company_defaults:
                company_defaults[row.company] = frappe.db.get_value(
                    "Company", row.company, "default_holiday_list"
                )
            holiday_list = company_defaults[row.company]
        holiday_lists[row.name] = holiday_list

    distinct_lists = sorted({hl for hl in holiday_lists.values() if hl})
    holidays = {}
    if distinct_lists:
        for row in frappe.get_all(
            "Holiday",
            filters={
                "parent": ["in", distinct_lists],
                "holiday_date": ["between", [start, end]],
            },
            fields=["parent", "holiday_date", "weekly_off"],
        ):
            holidays[(row.parent, getdate(row.holiday_date))] = cint(row.weekly_off)

    assignments = {}
    if frappe.db.has_column("Shift Assignment", "custom_off_day"):
        rows = frappe.get_all(
            "Shift Assignment",
            filters={
                "employee": ["in", employees],
                "docstatus": 1,
                "start_date": ["<=", end],
            },
            or_filters=[["end_date", ">=", start], ["end_date", "is", "not set"]],
            fields=["employee", "custom_off_day", "start_date", "end_date"],
            order_by="start_date desc, creation desc",
        )
        for row in rows:
            assignments.setdefault(row.employee, []).append(row)

    def off_days_for(employee, date_obj):
        for row in assignments.get(employee, []):
            if getdate(row.start_date) > date_obj:
                continue
            if row.end_date and getdate(row.end_date) < date_obj:
                continue
            raw = (row.get("custom_off_day") or "").strip()
            if not raw:
                return set()
            return {d.strip().lower() for d in raw.split(",") if d.strip()}
        return set()

    result = {}
    day = start
    while day <= end:
        weekday = day.strftime("%A").lower()
        for employee in employees:
            holiday_list = holiday_lists.get(employee)
            day_type = None
            is_public_holiday = False
            is_holiday_weekly_off = False
            if holiday_list and (holiday_list, day) in holidays:
                if holidays[(holiday_list, day)]:
                    is_holiday_weekly_off = True
                else:
                    is_public_holiday = True

            shift_off_days = off_days_for(employee, day)
            if is_public_holiday:
                day_type = "Holiday"
            elif shift_off_days:
                if weekday in shift_off_days:
                    day_type = "Weekly Off"
                else:
                    day_type = None
            elif is_holiday_weekly_off:
                day_type = "Weekly Off"

            result[(employee, day)] = day_type
        day = add_days(day, 1)

    return result


def get_holiday_list_for_employee_safe(employee):
    if not employee:
        return None
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if holiday_list:
        return holiday_list
    company = frappe.db.get_value("Employee", employee, "company")
    if company:
        return frappe.get_cached_value("Company", company, "default_holiday_list") or frappe.db.get_value("Company", company, "default_holiday_list")
    return None


def get_day_type(employee, attendance_date):
    if not employee or not attendance_date:
        return None

    date_obj = getdate(attendance_date)
    weekday = date_obj.strftime("%A").lower()

    holiday_list = get_holiday_list_for_employee_safe(employee)

    holiday = None
    if holiday_list:
        holiday = frappe.db.get_value(
            "Holiday",
            {
                "parent": holiday_list,
                "holiday_date": date_obj
            },
            ["weekly_off"],
            as_dict=True
        )

        if holiday and not cint(holiday.weekly_off):
            return "Holiday"

    shift_off_days = get_shift_weekly_off_days(employee, date_obj)
    if shift_off_days:
        if weekday in shift_off_days:
            return "Weekly Off"
        return None

    if holiday_list and holiday and cint(holiday.weekly_off):
        return "Weekly Off"

    return None


@frappe.whitelist()
def get_offday_status(employee, attendance_date, attendance=None):
    status = get_day_type(employee, attendance_date)

    if status and attendance:
        frappe.db.set_value("Attendance", attendance, {
            "status": status,
            "leave_type": None
        })

    return status

@frappe.whitelist()
def fetch_lrf_details(lrf_name):
    data = []
    get_batch_no = frappe.db.get_value("Label Requisition Form", lrf_name, "production_b_no")
    released_batch_no = frappe.db.get_value("Label Requisition Form", lrf_name, "released_b_no")
    data.append({"batch_no":get_batch_no, "released_batch_no":released_batch_no})
    
    try:
        child = frappe.get_all(
            "Label Requisition Form Item",  
            filters={"parent": lrf_name},
            fields=["seal_no", "drum_no"],
            )
        return data + child
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "fetch_lrf_details Error")
        return {}

@frappe.whitelist()
def checking_item_grade(item_code,item_name,lrf_name,grade_name):
    
    get_batch_no = frappe.db.get_value("Label Requisition Form", lrf_name, "production_b_no")
    batch_doc = frappe.get_doc("Batch",get_batch_no)

    if grade_name == "Others/IH":
        if not batch_doc.ih:
            frappe.throw("{0} Item Has not available for {1} grade.".format(item_name,grade_name))
    elif grade_name == "IP":
        if not batch_doc.ip:
            frappe.throw("{0} Item Has not available for {1} grade.".format(item_name,grade_name))
    elif grade_name == "USP":
        if not batch_doc.usp:
            frappe.throw("{0} Item Has not available for {1} grade.".format(item_name,grade_name))
    elif grade_name == "EP/BP":
        if not batch_doc.epbp:
            frappe.throw("{0} Item Has not available for {1} grade.".format(item_name,grade_name))

@frappe.whitelist()
def sales_invoice_payment_remainder():
    
    if cint(frappe.db.get_value("Accounts Settings",None,"custom_auto_send_payment_reminder_mails")):
        # mail on every sunday
        # if getdate().weekday() == 6: -----------committed by bhagyashri
            frappe.enqueue(send_sales_invoice_mails, queue='long', timeout=5000, job_name='Payment Reminder Mails')
            # frappe.enqueue(send_proforma_invoice_mails, queue='long', timeout=5000, job_name='Payment Reminder Mails')
            return "Payment Reminder Mails Send"

@frappe.whitelist()
def send_sales_invoice_mails():
    from frappe.utils import fmt_money
    
    def header(customer):
        return """<strong>""" + customer + """</strong><br><br>Dear Sir,<br><br>
        Kind attention account department.<br>
        We wish to invite your kind immediate attention to our following bill/s which have remained unpaid till date and are overdue for payment.<br>
        <div align="center">
            <table border="1" cellspacing="0" cellpadding="0" width="100%">
                <thead>
                    <tr>
                        <th width="16%" valign="top">Bill No</th>
                        <th width="12%" valign="top">Bill Date</th>
                        <th width="21%" valign="top">Order No</th>
                        <th width="15%" valign="top">Order Date</th>
                        <th width="16%" valign="top">Actual Amt</th>
                        <th width="18%" valign="top">Rem. Amt</th>
                    </tr></thead><tbody>"""
                
    def table_content(name, posting_date, po_no, po_date, rounded_total, outstanding_amount):
        posting_date = posting_date.strftime("%d-%m-%Y") if bool(posting_date) else '-'
        po_date = po_date.strftime("%d-%m-%Y") if bool(po_date) else '-'

        rounded_total = fmt_money(rounded_total, 2, 'INR')
        outstanding_amount = fmt_money(outstanding_amount, 2, 'INR')

        return """<tr>
                <td width="16%" valign="top"> {0} </td>
                <td width="12%" valign="top"> {1} </td>
                <td width="21%" valign="top"> {2} </td>
                <td width="15%" valign="top"> {3} </td>
                <td width="16%" valign="top" align="right"> {4} </td>
                <td width="18%" valign="top" align="right"> {5} </td>
            </tr>""".format(name, posting_date, po_no or '-', po_date, rounded_total, outstanding_amount)

    def footer(actual_amount, outstanding_amount):
        actual_amt = fmt_money(sum(actual_amount), 2, 'INR')
        outstanding_amt = fmt_money(sum(outstanding_amount), 2, 'INR')
        return """<tr>
                    <td width="68%" colspan="4" valign="top" align="right">
                        <strong>Net Receivable &nbsp; </strong>
                    </td>
                    <td align="right" width="13%" valign="top">
                        <strong> {} </strong>
                    </td>
                    <td align="right" width="18%" valign="top">
                        <strong> {} </strong>
                    </td>
                </tr></tbody></table></div><br>
                We request you to look into the matter and release the payment/s without Further delay. <br><br>
                If you need any clarifications for any of above invoice/s, please reach out to our Accounts Receivable Team by sending email to accounts@valencelabs.co.<br><br>
                We will appreciate your immediate response in this regard.<br><br>
                
                Thanking you in anticipation.<br><br>For, Valence Labs Private Limited.
                """.format(actual_amt, outstanding_amt)

    non_customers = ()
    data = frappe.get_list("Sales Invoice", filters={
            'status': ['in', ('Overdue')],
            'outstanding_amount':(">", 5000),
            'currency': 'INR',
            'docstatus': 1,
            "custom_dont_send_payment_reminder": 0,
            'customer': ['not in', non_customers],},
            order_by='posting_date',
            fields=["name", "customer", "posting_date", "po_no", "po_date", "rounded_total", "outstanding_amount", "contact_email", "naming_series"])

    def get_customers():
        customers_list = list(set([d.customer for d in data if d.customer]))
        customers_list.sort()

        for customer in customers_list:
            yield customer

    def get_customer_si(customer):
        for d in data:
            if d.customer == customer:
                yield d

    customers = get_customers()

    for customer in customers:
        attachments, outstanding, actual_amount, recipients = [], [], [], []
        table = ''

        # customer_si = [d for d in data if d.customer == customer]
        customer_si = get_customer_si(customer)

        for si in customer_si:
            name = "Previous Year Outstanding"
            if si.naming_series != "OSINV-":
                name = si.name
                try:
                    attachments.append(frappe.attach_print('Sales Invoice', si.name, print_format="Sales Invoice", print_letterhead=True))
                except:
                    pass

            table += table_content(name, si.posting_date, si.po_no, si.po_date,
                        si.rounded_total, si.outstanding_amount)

            outstanding.append(si.outstanding_amount)
            actual_amount.append(si.rounded_total or 0.0)

            if bool(si.contact_email) and si.contact_email not in recipients:
                recipients.append(si.contact_email)
            print(recipients)

        message = header(customer) + '' + table + '' + footer(actual_amount, outstanding)
        # recipients = "it@valencelabs.co"
        try:
            frappe.sendmail(
                recipients=recipients,
                cc = '',
                subject = 'Overdue Invoices: ' + customer,
                sender = 'accounts@valencelabs.co',
                message = message,
                attachments = attachments
            )
        except:
            frappe.log_error("Mail Sending Issue", frappe.get_traceback())
            continue

    
