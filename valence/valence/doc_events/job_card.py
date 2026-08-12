import frappe

def on_submit(self,method):
	if self.work_order:
		doc = frappe.get_doc("Work Order",self.work_order)
		for row in doc.operations:
			if row.operation == self.operation:
				row.db_set("from_time",self.actual_start_date)
				row.db_set("to_time",self.actual_end_date)
				row.db_set("completed_quantity",self.total_completed_qty)
				employee =  self.time_logs[0].employee
				row.db_set("employee",employee)
				time = self.total_time_in_mins * 60
				row.db_set("total_time",time)
				time_diff = (self.time_required- self.total_time_in_mins)*60
				row.db_set("time_difference",time_diff)

def before_submit(self, method):
	# Prefer db_set over full WO save: Work Order carries Chemical child tables
	# (e.g. Work Order Finish Item). Full save requires that app on the bench and
	# is unnecessary to flip a single flag.
	if self.work_order:
		frappe.db.set_value("Work Order", self.work_order, "disable_auto_update", 1, update_modified=False)

def after_submit(self, method):
	if not self.work_order:
		return
	if frappe.db.get_value("Work Order", self.work_order, "disable_auto_update"):
		frappe.db.set_value("Work Order", self.work_order, "disable_auto_update", 0, update_modified=False)