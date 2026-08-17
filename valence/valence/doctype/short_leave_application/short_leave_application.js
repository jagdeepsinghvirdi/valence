// Copyright (c) 2026, finbyz tech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Short Leave Application", {
	refresh: function (frm) {
		if (frm.doc.duration_hours) {
			frm.dashboard.set_headline_alert(
				__("Duration: {0} hrs", [frm.doc.duration_hours])
			);
		}
	},

	from_time: function (frm) {
		compute_duration(frm);
	},

	to_time: function (frm) {
		compute_duration(frm);
	},

	employee: function (frm) {
		if (!frm.doc.employee) return;
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Employee",
				filters: { name: frm.doc.employee },
				fieldname: ["department", "company"],
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value("department", r.message.department);
					frm.set_value("company", r.message.company);
				}
			},
		});
	},
});

function compute_duration(frm) {
	if (frm.doc.from_time && frm.doc.to_time) {
		let from = frappe.datetime.str_to_obj("2000-01-01 " + frm.doc.from_time);
		let to = frappe.datetime.str_to_obj("2000-01-01 " + frm.doc.to_time);
		let hrs = (to - from) / (1000 * 60 * 60);
		frm.set_value("duration_hours", hrs > 0 ? Math.round(hrs * 100) / 100 : 0);
	}
}