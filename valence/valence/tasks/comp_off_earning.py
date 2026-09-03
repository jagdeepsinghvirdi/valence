# Copyright (c) 2026, finbyz tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

from valence.valence.attendance_code import get_attendance_code
from valence.valence.doctype.attendance_settings.attendance_settings import (
	DEFAULT_COMP_OFF_RULES,
)


def get_comp_off_leave_type():
	"""
	Fetch the configured Comp Off Leave Type from Attendance Settings.
	Raises ValidationError if not configured or if the configured type does not exist.
	Never silently falls back to another leave type.
	"""
	leave_type = frappe.db.get_single_value("Attendance Settings", "comp_off_leave_type")
	if not leave_type:
		frappe.throw(_("Comp Off Leave Type is not configured in Attendance Settings."))
	if not frappe.db.exists("Leave Type", leave_type):
		frappe.throw(_("Configured Comp Off Leave Type '{0}' does not exist.").format(leave_type))
	return leave_type


def _match_comp_off_rule(code, rules, enabled_setting=1):
	"""
	Pure rule matcher for attendance code against comp off rules.
	Used by get_comp_off_earned and for unit testing.
	"""
	if not enabled_setting or not code or not rules:
		return 0.0

	for rule in rules:
		rule_dict = rule if isinstance(rule, dict) else rule.as_dict()
		if rule_dict.get("attendance_code") == code and cint(rule_dict.get("enabled")):
			return flt(rule_dict.get("comp_off_days"))

	return 0.0


def get_comp_off_earned(attendance, context=None) -> float:
	"""
	Calculate Comp Off days earned by an Attendance record based on Attendance Settings rules.
	Returns 0.0 for non-qualifying codes, disabled rules, or when Comp Off is disabled.
	"""
	comp_off_enabled = cint(
		frappe.db.get_single_value("Attendance Settings", "comp_off_enabled")
	)
	if not comp_off_enabled:
		return 0.0

	code = get_attendance_code(attendance, context)
	if not code:
		return 0.0

	settings_doc = frappe.get_single("Attendance Settings")
	rules = settings_doc.get("comp_off_rules") or DEFAULT_COMP_OFF_RULES

	return _match_comp_off_rule(code, rules, enabled_setting=comp_off_enabled)


def get_attendance_comp_off_entries(attendance_name, employee=None, attendance_date=None, leave_type=None):
	"""
	Query submitted Leave Ledger Entries belonging specifically to this Attendance.
	Uses custom_attendance reference on Leave Ledger Entry for exact identity isolation.
	"""
	att_name = attendance_name if isinstance(attendance_name, str) else getattr(attendance_name, "name", None)
	if not att_name:
		return []

	# 1. Primary Attendance-specific filter via custom_attendance
	filters = {
		"custom_attendance": att_name,
		"transaction_type": "Leave Allocation",
		"docstatus": 1,
	}
	if leave_type:
		filters["leave_type"] = leave_type

	try:
		entries = frappe.get_all(
			"Leave Ledger Entry",
			filters=filters,
			fields=["name", "leaves", "transaction_type", "transaction_name", "leave_type", "company", "custom_attendance"],
			order_by="creation asc",
		)
		if entries:
			return entries
	except Exception:
		pass

	# 2. Fallback for unmigrated entries: match employee + date if custom_attendance is not set to another attendance
	if employee and attendance_date:
		fallback_filters = {
			"employee": employee,
			"from_date": attendance_date,
			"to_date": attendance_date,
			"transaction_type": "Leave Allocation",
			"docstatus": 1,
		}
		if leave_type:
			fallback_filters["leave_type"] = leave_type

		try:
			candidates = frappe.get_all(
				"Leave Ledger Entry",
				filters=fallback_filters,
				fields=["name", "leaves", "transaction_type", "transaction_name", "leave_type", "company", "custom_attendance"],
				order_by="creation asc",
			)
			return [
				c for c in candidates
				if not c.get("custom_attendance") or c.get("custom_attendance") == att_name
			]
		except Exception:
			return []

	return []


def process_comp_off_for_attendance(attendance_name):
	"""
	Process Comp Off earning for a single Attendance record.
	Follows the lifecycle:
	1. Enforce submitted Attendance (docstatus == 1).
	2. Calculate new earning code and days BEFORE mutating ledger/allocation state.
	3. Read existing net credit from Leave Ledger Entry.
	4. If net_credited == new_earning: no-op (idempotent).
	5. If net_credited != new_earning:
	   - Reverse old credit if net_credited != 0.
	   - Allocate and credit new earning if new_earning > 0.
	"""
	att = frappe.get_doc("Attendance", attendance_name) if isinstance(attendance_name, str) else attendance_name
	if not att:
		return

	if att.docstatus != 1:
		if att.docstatus == 2:
			reverse_comp_off_for_attendance(att)
		return

	new_earning = get_comp_off_earned(att)

	existing_entries = get_attendance_comp_off_entries(
		att.name,
		employee=att.employee,
		attendance_date=att.attendance_date,
	)
	net_credited = sum(flt(e.leaves) for e in existing_entries)

	if net_credited == new_earning:
		return

	if net_credited != 0:
		original_allocation_name = existing_entries[0].transaction_name
		historical_leave_type = existing_entries[0].leave_type
		company = att.company or existing_entries[0].company

		reversal_entry = frappe.get_doc(
			{
				"doctype": "Leave Ledger Entry",
				"employee": att.employee,
				"employee_name": att.employee_name or frappe.db.get_value("Employee", att.employee, "employee_name"),
				"leave_type": historical_leave_type,
				"transaction_type": "Leave Allocation",
				"transaction_name": original_allocation_name,
				"custom_attendance": att.name,
				"company": company,
				"leaves": -flt(net_credited),
				"from_date": att.attendance_date,
				"to_date": att.attendance_date,
				"is_carry_forward": 0,
				"is_expired": 0,
			}
		)
		reversal_entry.insert(ignore_permissions=True)
		reversal_entry.submit()

		if frappe.db.exists("Leave Allocation", original_allocation_name):
			alloc = frappe.get_doc("Leave Allocation", original_allocation_name)
			new_alloc_total = flt(alloc.total_leaves_allocated) - flt(net_credited)
			alloc.db_set("total_leaves_allocated", new_alloc_total, update_modified=False)
			alloc.add_comment(
				text=_(
					"Reversed {0} Comp Off for Attendance {1} on {2}."
				).format(net_credited, att.name, att.attendance_date)
			)

	if new_earning > 0:
		leave_type = get_comp_off_leave_type()
		allocation = _ensure_comp_off_allocation(
			employee=att.employee,
			leave_type=leave_type,
			attendance_date=att.attendance_date,
			company=att.company,
		)

		credit_entry = frappe.get_doc(
			{
				"doctype": "Leave Ledger Entry",
				"employee": att.employee,
				"employee_name": att.employee_name or frappe.db.get_value("Employee", att.employee, "employee_name"),
				"leave_type": leave_type,
				"transaction_type": "Leave Allocation",
				"transaction_name": allocation.name,
				"custom_attendance": att.name,
				"company": att.company,
				"leaves": flt(new_earning),
				"from_date": att.attendance_date,
				"to_date": att.attendance_date,
				"is_carry_forward": 0,
				"is_expired": 0,
			}
		)
		credit_entry.insert(ignore_permissions=True)
		credit_entry.submit()

		new_total = flt(allocation.total_leaves_allocated) + flt(new_earning)
		allocation.db_set("total_leaves_allocated", new_total, update_modified=False)
		code = get_attendance_code(att)
		allocation.add_comment(
			text=_(
				"Credited {0} Comp Off for Attendance {1} on {2} ({3})."
			).format(new_earning, att.name, att.attendance_date, code)
		)


def reverse_comp_off_for_attendance(attendance_name):
	"""
	Reverse all active Comp Off credit for an Attendance record.
	Identifies the historical leave type and exact Leave Allocation from existing ledger entries.
	"""
	att = frappe.get_doc("Attendance", attendance_name) if isinstance(attendance_name, str) else attendance_name
	if not att:
		return

	existing_entries = get_attendance_comp_off_entries(
		att.name,
		employee=att.employee,
		attendance_date=att.attendance_date,
	)
	net_credited = sum(flt(e.leaves) for e in existing_entries)
	if net_credited <= 0:
		return

	original_allocation_name = existing_entries[0].transaction_name
	historical_leave_type = existing_entries[0].leave_type
	company = att.company or existing_entries[0].company

	reversal_entry = frappe.get_doc(
		{
			"doctype": "Leave Ledger Entry",
			"employee": att.employee,
			"employee_name": att.employee_name or frappe.db.get_value("Employee", att.employee, "employee_name"),
			"leave_type": historical_leave_type,
			"transaction_type": "Leave Allocation",
			"transaction_name": original_allocation_name,
			"custom_attendance": att.name,
			"company": company,
			"leaves": -flt(net_credited),
			"from_date": att.attendance_date,
			"to_date": att.attendance_date,
			"is_carry_forward": 0,
			"is_expired": 0,
		}
	)
	reversal_entry.insert(ignore_permissions=True)
	reversal_entry.submit()

	if frappe.db.exists("Leave Allocation", original_allocation_name):
		alloc = frappe.get_doc("Leave Allocation", original_allocation_name)
		new_alloc_total = flt(alloc.total_leaves_allocated) - flt(net_credited)
		alloc.db_set("total_leaves_allocated", new_alloc_total, update_modified=False)
		alloc.add_comment(
			text=_(
				"Reversed {0} Comp Off on cancellation of Attendance {1} for date {2}."
			).format(net_credited, att.name, att.attendance_date)
		)


def process_comp_off_earning(from_date, to_date, employee=None):
	"""
	Batch process Comp Off earning for submitted Attendance records across a date range.
	"""
	filters = {
		"docstatus": 1,
		"attendance_date": ["between", [from_date, to_date]],
	}
	if employee:
		filters["employee"] = employee

	attendances = frappe.get_all("Attendance", filters=filters, pluck="name")
	for att_name in attendances:
		try:
			process_comp_off_for_attendance(att_name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Comp Off Earning failed for Attendance {att_name}")

	return {"processed": len(attendances), "attendances": attendances}


def run_daily_comp_off_earning():
	"""
	Scheduled task entry point. Runs daily after Attendance off-day processing for yesterday's records.
	"""
	yesterday = add_days(today(), -1)
	return process_comp_off_earning(from_date=yesterday, to_date=yesterday)


def run():
	"""Manual entry point for bench execute."""
	return run_daily_comp_off_earning()


def on_attendance_submit(doc, method=None):
	"""Doc event hook: Automatically credit Comp Off on Attendance submission."""
	if not _is_auto_credit_enabled():
		return
	process_comp_off_for_attendance(doc)


def on_attendance_update_after_submit(doc, method=None):
	"""Doc event hook: Automatically reprocess Comp Off on Attendance amendment."""
	if not _is_auto_credit_enabled():
		return
	process_comp_off_for_attendance(doc)


def on_attendance_cancel(doc, method=None):
	"""Doc event hook: Automatically reverse Comp Off on Attendance cancellation."""
	reverse_comp_off_for_attendance(doc)


def _is_auto_credit_enabled():
	comp_off_enabled = cint(
		frappe.db.get_single_value("Attendance Settings", "comp_off_enabled")
	)
	comp_off_auto_credit = cint(
		frappe.db.get_single_value("Attendance Settings", "comp_off_auto_credit")
	)
	return bool(comp_off_enabled and comp_off_auto_credit)


def _ensure_comp_off_allocation(employee, leave_type, attendance_date, company=None):
	"""
	Find existing active submitted Leave Allocation or create a new submitted Leave Allocation.
	"""
	att_date = getdate(attendance_date)

	existing_alloc = frappe.db.get_value(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ["<=", att_date],
			"to_date": [">=", att_date],
		},
		"name",
	)
	if existing_alloc:
		return frappe.get_doc("Leave Allocation", existing_alloc)

	company = company or frappe.db.get_value("Employee", employee, "company")
	from_date = f"{att_date.year}-01-01"
	to_date = f"{att_date.year}-12-31"

	try:
		from hrms.hr.utils import get_leave_period

		periods = get_leave_period(att_date, att_date, company)
		if periods:
			from_date = periods[0].from_date
			to_date = periods[0].to_date
	except Exception:
		pass

	alloc = frappe.get_doc(
		{
			"doctype": "Leave Allocation",
			"employee": employee,
			"leave_type": leave_type,
			"company": company,
			"from_date": from_date,
			"to_date": to_date,
			"new_leaves_allocated": 0.0,
			"total_leaves_allocated": 0.0,
			"carry_forward": 0,
			"description": _("Auto-created for Compensatory Off Earning"),
		}
	)
	alloc.insert(ignore_permissions=True)
	alloc.submit()
	return alloc
