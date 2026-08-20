frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		frm.trigger("restrict_leave_types_for_resign");
	},

	employee(frm) {
		frm.trigger("restrict_leave_types_for_resign");
	},

	make_dashboard(frm) {
		frm.trigger("restrict_leave_types_for_resign");
	},

	restrict_leave_types_for_resign(frm) {
		if (!frm.doc.employee) {
			return;
		}

		frappe.call({
			method: "valence.valence.doc_events.leave_application.get_leave_type_filter_for_employee",
			args: { employee: frm.doc.employee },
			callback(r) {
				const allowed = r.message;
				if (!allowed || !allowed.length) {
					return;
				}

				frm.set_query("leave_type", () => ({
					filters: [["leave_type_name", "in", allowed]],
				}));

				if (frm.doc.leave_type && !allowed.includes(frm.doc.leave_type)) {
					frm.set_value("leave_type", "");
				}

				frm.set_intro(
					__("During resignation / notice period only Sick Leave and Leave Without Pay can be applied."),
					"blue"
				);
			},
		});
	},
});
