frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		frm.trigger("restrict_leave_types_for_resign");
		frm.trigger("show_direct_apply_action");
		frm.trigger("show_comp_off_balance");
	},

	show_direct_apply_action(frm) {
		if (!frm.is_new()) {
			if (frm.save_disabled) {
				frm.enable_save();
			}
			return;
		}

		frm.disable_save();
		frm.page.set_primary_action(__("Apply"), () => {
			frm.enable_save();
			frappe.dom.freeze();

			frm.save()
				.then(() => frm.script_manager.trigger("before_workflow_action"))
				.then(() =>
					frappe.xcall("frappe.model.workflow.apply_workflow", {
						doc: frm.doc,
						action: "Apply",
					})
				)
				.then((doc) => {
					frappe.model.sync(doc);
					frm.refresh();
					frm.script_manager.trigger("after_workflow_action");
				})
				.catch(() => {
					frm.refresh();
				})
				.finally(() => {
					frappe.dom.unfreeze();
				});
		});
	},

	employee(frm) {
		frm.resignation_restricted = false;
		frm.trigger("restrict_leave_types_for_resign");
		frm.trigger("show_comp_off_balance");
	},

	leave_type(frm) {
		frm.trigger("show_comp_off_balance");
	},

	from_date(frm) {
		frm.trigger("show_comp_off_balance");
	},

	make_dashboard(frm) {
		frm.trigger("restrict_leave_types_for_resign");
	},

	update_form_intro(frm, comp_off_message) {
		if (frm.resignation_restricted) {
			frm.set_intro(
				__("During resignation / notice period only Sick Leave and Leave Without Pay can be applied."),
				"blue"
			);
		} else if (comp_off_message) {
			frm.set_intro(comp_off_message, "blue");
		} else {
			frm.set_intro();
		}
	},

	show_comp_off_balance(frm) {
		if (!frm.doc.leave_type || !frm.doc.employee) {
			frm.trigger("update_form_intro");
			return;
		}

		frappe.db.get_single_value("Attendance Settings", "comp_off_leave_type").then((comp_off_type) => {
			if (comp_off_type && frm.doc.leave_type === comp_off_type) {
				frappe.call({
					method: "valence.valence.doc_events.comp_off_usage.get_comp_off_balance",
					args: {
						employee: frm.doc.employee,
						on_date: frm.doc.from_date || frappe.datetime.get_today(),
					},
					callback(r) {
						if (r.message !== undefined && r.message !== null) {
							const msg = __("Available Comp Off Balance: {0} days", [r.message]);
							frm.events.update_form_intro(frm, msg);
						} else {
							frm.events.update_form_intro(frm);
						}
					},
				});
			} else {
				frm.events.update_form_intro(frm);
			}
		});
	},

	restrict_leave_types_for_resign(frm) {
		if (!frm.doc.employee) {
			frm.resignation_restricted = false;
			frm.set_query("leave_type", () => ({}));
			frm.events.update_form_intro(frm);
			return;
		}

		frappe.call({
			method: "valence.valence.doc_events.leave_application.get_leave_type_filter_for_employee",
			args: { employee: frm.doc.employee },
			callback(r) {
				const allowed = r.message;
				if (!allowed || !allowed.length) {
					frm.resignation_restricted = false;
					frm.set_query("leave_type", () => ({}));
					frm.events.update_form_intro(frm);
					return;
				}

				frm.resignation_restricted = true;

				frm.set_query("leave_type", () => ({
					filters: [["leave_type_name", "in", allowed]],
				}));

				if (frm.doc.leave_type && !allowed.includes(frm.doc.leave_type)) {
					frm.set_value("leave_type", "");
				}

				frm.events.update_form_intro(frm);
			},
		});
	},
});
