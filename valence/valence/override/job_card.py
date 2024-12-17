import frappe
from erpnext.manufacturing.doctype.job_card.job_card import JobCard as _JobCard
from frappe.utils import (
	add_days,
	add_to_date,
	cint,
	flt,
	get_datetime,
	get_link_to_form,
	get_time,
	getdate,
	time_diff,
	time_diff_in_hours,
	time_diff_in_seconds,
)
from frappe import _, bold

class OverlapError(frappe.ValidationError):
	pass
class JobCard(_JobCard):
	def validate_time_logs(self):
		self.total_time_in_mins = 0.0
		self.total_completed_qty = 0.0

		if self.get("time_logs"):
			for d in self.get("time_logs"):
				if d.to_time and get_datetime(d.from_time) > get_datetime(d.to_time):
					frappe.throw(_("Row {0}: From time must be less than to time").format(d.idx))

				open_job_cards = []
				if d.get("employee"):
					open_job_cards = self.get_open_job_cards(d.get("employee"))

				data = self.get_overlap_for(d, open_job_cards=open_job_cards)
				doc = frappe.get_doc("Manufacturing Settings")
				if data and not doc.custom_job_card_over_lap_time_not_required:
					frappe.throw(
						_("Row {0}: From Time and To Time of {1} is overlapping with {2}").format(
							d.idx, self.name, data.name
						),
						OverlapError,
					)

				if d.from_time and d.to_time:
					d.time_in_mins = time_diff_in_hours(d.to_time, d.from_time) * 60
					self.total_time_in_mins += d.time_in_mins

				if d.completed_qty and not self.sub_operations:
					self.total_completed_qty += d.completed_qty

			self.total_completed_qty = flt(self.total_completed_qty, self.precision("total_completed_qty"))

		for row in self.sub_operations:
			self.total_completed_qty += row.completed_qty

