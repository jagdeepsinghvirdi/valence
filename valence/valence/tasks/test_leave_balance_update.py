"""Automated checks for the quarterly Leave Balance Update job. Run:
  bench --site valence.localhost execute valence.valence.tasks.test_leave_balance_update.run
"""

from __future__ import annotations

import frappe

from valence.valence.tasks.leave_balance_update import credit_leave_for_employee


def run():
	results = []

	def ok(name, cond, detail=""):
		status = "PASS" if cond else "FAIL"
		results.append((status, name, detail))
		print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

	# --- Idempotency guard: credit_leave_for_employee must not double-credit ---
	employee = "HR-EMP-00004"
	leave_type = "Compensatory Off"
	from_date = "2026-04-01"
	to_date = "2026-06-30"

	# Clean slate for this test window
	frappe.db.delete(
		"Leave Ledger Entry",
		{
			"employee": employee,
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"from_date": from_date,
			"to_date": to_date,
		},
	)
	frappe.db.commit()

	# Simulate a prior successful run by inserting the ledger entry it would create
	fake_entry = frappe.get_doc(
		{
			"doctype": "Leave Ledger Entry",
			"employee": employee,
			"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"from_date": from_date,
			"to_date": to_date,
			"leaves": 1,
			"is_carry_forward": 0,
			"is_expired": 0,
		}
	)
	fake_entry.insert(ignore_permissions=True)
	frappe.db.commit()

	before = frappe.db.count(
		"Leave Ledger Entry",
		{"employee": employee, "leave_type": leave_type, "transaction_type": "Leave Allocation"},
	)

	# Calling credit_leave_for_employee again with the same window should be a no-op
	credit_leave_for_employee(employee, None, leave_type, 20, 10, from_date, to_date)

	after = frappe.db.count(
		"Leave Ledger Entry",
		{"employee": employee, "leave_type": leave_type, "transaction_type": "Leave Allocation"},
	)

	ok(
		"credit_leave_for_employee does not double-credit when a ledger entry already exists",
		before == after == 1,
		f"before={before}, after={after}",
	)

	# --- Guard: divisor of 0/None must be a no-op (no exception, no entry created) ---
	frappe.db.delete(
		"Leave Ledger Entry",
		{
			"employee": employee,
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"from_date": "2026-01-01",
			"to_date": "2026-03-31",
		},
	)
	frappe.db.commit()

	count_before_zero_divisor = frappe.db.count(
		"Leave Ledger Entry",
		{
			"employee": employee,
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"from_date": "2026-01-01",
			"to_date": "2026-03-31",
		},
	)
	credit_leave_for_employee(employee, None, leave_type, 0, 10, "2026-01-01", "2026-03-31")
	count_after_zero_divisor = frappe.db.count(
		"Leave Ledger Entry",
		{
			"employee": employee,
			"leave_type": leave_type,
			"transaction_type": "Leave Allocation",
			"from_date": "2026-01-01",
			"to_date": "2026-03-31",
		},
	)
	ok(
		"credit_leave_for_employee is a no-op when divisor is 0",
		count_before_zero_divisor == count_after_zero_divisor == 0,
		f"before={count_before_zero_divisor}, after={count_after_zero_divisor}",
	)

	# --- Cleanup ---
	frappe.delete_doc("Leave Ledger Entry", fake_entry.name, force=True, ignore_permissions=True)
	frappe.db.commit()

	failed = [r for r in results if r[0] == "FAIL"]
	print(f"\n{len(results) - len(failed)}/{len(results)} passed")
	if failed:
		print("FAILURES:")
		for status, name, detail in failed:
			print(f"  - {name}: {detail}")

	return results
