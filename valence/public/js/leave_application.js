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
				.then(() => {
					if (frm.is_new() || !frm.doc.name || frm.doc.__islocal) {
						return Promise.reject(new Error("not-saved"));
					}
					return frappe.db.get_doc(frm.doctype, frm.doc.name);
				})
				.then((doc) =>
					frappe.xcall("frappe.model.workflow.apply_workflow", {
						doc: doc,
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
		frm.trigger("leave_type");
	},

	from_date(frm) {
		frm.trigger("leave_type");
	},

	make_dashboard(frm) {
		frm.trigger("restrict_leave_types_for_resign");
	},

	leave_type(frm) {
		frm.set_intro("");

		if (!frm.doc.leave_type || !frm.doc.employee) {
			return;
		}

		frappe.call({
			method: "valence.valence.doc_events.comp_off_usage.get_comp_off_balance_for_leave_type",
			args: {
				employee: frm.doc.employee,
				leave_type: frm.doc.leave_type,
				on_date: frm.doc.from_date,
			},
			callback(r) {
				if (r.message !== undefined && r.message !== null) {
					frm.set_intro(__("Available Comp Off Balance: {0} days", [r.message]), "blue");
				}
			},
		});
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
