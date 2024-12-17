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
				
def before_submit(self, method):
	work_order = frappe.get_doc("Work Order", self.work_order)
	work_order.db_set("disable_auto_update" , 1)
	work_order.save(ignore_permissions=True)

def after_submit(self, method):
	work_order = frappe.get_doc("Work Order", self.work_order)
	if work_order.disable_auto_update:
		work_order.db_set("disable_auto_update" , 0)
		work_order.save(ignore_permissions=True)
		work_order.reload()