frappe.listview_settings["Batch"] = {
	add_fields: ["item", "expiry_date", "batch_qty", "disabled","retest_date"],
	get_indicator: (doc) => {
		if (doc.disabled) {
			return [__("Disabled"), "gray", "disabled,=,1"];
		} else if (
			doc.expiry_date &&
			frappe.datetime.get_diff(doc.expiry_date, frappe.datetime.nowdate()) <= 0
		) {
			return [
				__("Expired"),
				"red",
				"expiry_date,not in,|expiry_date,<=,Today|batch_qty,>,0|disabled,=,0",
			];
        
		} 
        else if (
			doc.retest_date &&
			frappe.datetime.get_diff(doc.retest_date, frappe.datetime.nowdate()) <= 0
		) {
			return [
				__("Retest"),
				"yellow",
				"retest_date,not in,|retest_date,<=,Today|batch_qty,>,0|disabled,=,0",
			];
        }else if (!doc.batch_qty) {
			return [__("Empty"), "gray", "batch_qty,=,0|disabled,=,0"];
		} else {
			return [__("Active"), "green", "batch_qty,>,0|disabled,=,0"];
		}
	},
};
