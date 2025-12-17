import frappe

import frappe
from frappe.utils import get_datetime, get_datetime_str
from datetime import datetime, timedelta
from frappe.utils import flt,cint, get_url_to_form, nowdate
from erpnext.accounts.utils import getdate
from email.utils import formataddr

@frappe.whitelist()
def get_employee_checkin_entries(employee, attendance_date):
    # Convert string to datetime and define start and end of the day
    start_date = get_datetime(attendance_date)
    end_date = start_date + timedelta(days=1)

    # Fetch first check-in (earliest)
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

    # Fetch last check-in (latest)
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

    return {
        "in_time": in_time_doc[0].time if in_time_doc else None,
        "out_time": out_time_doc[0].time if out_time_doc else None
    }

@frappe.whitelist()
def get_offday_status(employee, attendance_date,attendance):
    
    from datetime import datetime
    
    if isinstance(attendance_date, str):
        date_obj = datetime.strptime(attendance_date, "%Y-%m-%d").date()
    else:
        date_obj = attendance_date
    
    # Step 1: Check Holiday List
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if holiday_list:
        if frappe.db.exists("Holiday", {"holiday_date": date_obj, "parent": holiday_list}):
            holiday_doc = frappe.get_doc("Holiday List",holiday_list)

            for holiday in holiday_doc.holidays:
                if attendance:
                    if holiday.weekly_off:
                        frappe.db.set_value("Attendance", attendance, {
                        "status": "Weekly Off",
                        "leave_type": None
                        })
                        frappe.db.commit()
                        return "Weekly Off"
                    else:
                        frappe.db.set_value("Attendance", attendance, {
                            "status": "Holiday",
                            "leave_type": None
                            })
                        frappe.db.commit()
                        return "Holiday"
   
    # Step 2: Check Shift Assignment for weekly off

    shift_assignment = frappe.get_all(
    "Shift Assignment",
    filters={
        "employee": employee,
        "start_date": ["<=", date_obj],
    },
    fields=["name", "shift_type", "custom_off_day", "end_date"]
    )

    valid_shift_assignments = []

    for shift in shift_assignment:
        if not shift["end_date"] or shift["end_date"] >= date_obj:
            valid_shift_assignments.append(shift)

    if valid_shift_assignments:
        weekday = date_obj.strftime('%A')
        emp_offday = valid_shift_assignments[0]["custom_off_day"]

        if weekday == emp_offday:
            if attendance:
                frappe.db.set_value("Attendance", attendance, {
                    "status": "Weekly Off",
                    "leave_type": None
                })
                frappe.db.commit()
            return "Weekly Off"

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

    
