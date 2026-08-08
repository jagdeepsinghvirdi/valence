import frappe
from frappe import _


@frappe.whitelist()
def bulk_create_shift_schedule_assignment(employees, shift_schedule, company, create_shifts_after, shift_location=None):
    """
    Create a Shift Schedule Assignment for each selected employee.
    Called from the "Bulk Assign to Employees" button on Shift Schedule.

    employees: JSON list of employee IDs (strings), e.g. '["HR-EMP-00001", "HR-EMP-00002"]'
    shift_schedule: name of the Shift Schedule doc to link
    company: company for all the assignments
    create_shifts_after: date string, new shifts generate after this date
    shift_location: optional, applied to every created record
    """
    if isinstance(employees, str):
        employees = frappe.parse_json(employees)

    if not employees:
        frappe.throw(_("Please select at least one employee."))

    created = []
    skipped = []

    for employee in employees:
        # Avoid creating a duplicate enabled assignment for the same employee + schedule
        existing = frappe.db.exists(
            "Shift Schedule Assignment",
            {"employee": employee, "shift_schedule": shift_schedule, "enabled": 1},
        )
        if existing:
            skipped.append(employee)
            continue

        doc = frappe.get_doc({
            "doctype": "Shift Schedule Assignment",
            "employee": employee,
            "company": company,
            "shift_schedule": shift_schedule,
            "shift_location": shift_location,
            "enabled": 1,
            "create_shifts_after": create_shifts_after,
        })
        doc.insert()
        created.append(employee)

    return {
        "created_count": len(created),
        "skipped_count": len(skipped),
        "skipped": skipped,
    }