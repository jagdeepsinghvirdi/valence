frappe.ui.form.on("Shift Schedule", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Bulk Assign to Employees"), () => {
			open_bulk_assign_dialog(frm);
		});
	},
});

function open_bulk_assign_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Assign Shift Schedule to Employees"),
		fields: [
			{
				fieldname: "company",
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				reqd: 1,
				default: frappe.defaults.get_default("company"),
			},
			{
				fieldname: "create_shifts_after",
				fieldtype: "Date",
				label: __("Create Shifts After"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "shift_location",
				fieldtype: "Link",
				options: "Shift Location",
				label: __("Shift Location"),
			},
			{
				fieldname: "employees",
				fieldtype: "MultiSelectList",
				label: __("Employees"),
				reqd: 1,
				get_data: function (txt) {
					return frappe.db.get_link_options("Employee", txt);
				},
			},
		],
		primary_action_label: __("Assign"),
		primary_action(values) {
			frappe.call({
				method: "valence.valence.override.whitelisted_method.shift_schedule_assignment.bulk_create_shift_schedule_assignment",
				args: {
					employees: values.employees,
					shift_schedule: frm.doc.name,
					company: values.company,
					create_shifts_after: values.create_shifts_after,
					shift_location: values.shift_location,
				},
				freeze: true,
				freeze_message: __("Creating Shift Schedule Assignments..."),
				callback: function (r) {
					if (!r.message) return;
					dialog.hide();
					frappe.msgprint(
						__("Created {0} assignment(s). Skipped {1} (already enrolled).", [
							r.message.created_count,
							r.message.skipped_count,
						])
					);
				},
			});
		},
	});

	dialog.show();
}