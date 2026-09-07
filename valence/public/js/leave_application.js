frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		frm.trigger("restrict_leave_types_for_resign");
		frm.trigger("show_direct_apply_action");
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
