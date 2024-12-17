import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime


def on_submit(self, method):
	for row in self.operations:
		row.db_set("from_time",row.planned_start_time)
		row.db_set("to_time",row.planned_end_time)
	self.reload()


def on_update_after_submit(self, method):
	if self.disable_auto_update:
		return

	if hasattr(self, "_in_update_after_submit"):
		return

	self._in_update_after_submit = True
	bom_doc = frappe.get_doc("BOM",self.bom_no)

	try:

		if bom_doc.routing:
			for i in range(1, len(self.operations)):
				prev_op = self.operations[i - 1]
				current_op = self.operations[i]

				if current_op.from_time and prev_op.to_time:
					if get_datetime(current_op.from_time) < get_datetime(prev_op.to_time):
						frappe.throw(
							_("Row {row}: 'From Time' ({from_time}) must be greater than or equal to 'To Time' ({to_time}) of the previous operation.")
							.format(
								row=i + 1,
								from_time=current_op.from_time,
								to_time=prev_op.to_time
							)
						)

		for row in self.operations:
			job_card_name = frappe.get_value(
				"Job Card",
				filters={"work_order": self.name, "operation": row.operation,"sequence_id": ("=", row.sequence_id)},
				fieldname="name",
			)

			if not job_card_name:
				continue

			job_card = frappe.get_doc("Job Card", job_card_name)
			if not row.from_time or not row.to_time:
				frappe.throw("From time and To time is mandatory")

			row_from_time = get_datetime(row.from_time).replace(microsecond=0)
			row_to_time = get_datetime(row.to_time).replace(microsecond=0)

			existing_log = next(
				(
					log for log in job_card.time_logs
					if get_datetime(log.from_time).replace(microsecond=0) == row_from_time
					and get_datetime(log.to_time).replace(microsecond=0) == row_to_time
				),
				None,
			)

			if existing_log:
				continue

			job_card.append("time_logs", {
				"employee": row.employee or None,
				"from_time": row.from_time,
				"to_time": row.to_time,
				"completed_qty": flt(row.completed_quantity or self.qty),
			})

			job_card.flags.ignore_validate_update_after_submit = True
			job_card.save(ignore_permissions=True)

			if job_card.docstatus == 0:
				job_card.submit()

	finally:
		self._in_update_after_submit = False
		frappe.msgprint(_("Job Cards updated successfully."))
		self.reload()

