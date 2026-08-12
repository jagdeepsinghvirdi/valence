frappe.listview_settings["Quarterly Working Days"] = {
	onload: function (listview) {
		listview.page.add_inner_button(__("Bulk Add Entries"), () => {
			open_bulk_entry_dialog();
		});
	},
};

function open_bulk_entry_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Add Quarterly Working Days"),
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
				fieldname: "quarter_start_date",
				fieldtype: "Date",
				label: __("Quarter Start Date"),
				reqd: 1,
			},
			{
				fieldname: "quarter_end_date",
				fieldtype: "Date",
				label: __("Quarter End Date"),
				reqd: 1,
			},
			{
				fieldname: "employees",
				fieldtype: "MultiSelectList",
				label: __("Employees"),
				reqd: 1,
				get_data: function (txt) {
					return frappe.db.get_link_options("Employee", txt);
				},
				onchange: () => render_working_days_table(dialog),
			},
			{
				fieldname: "working_days_table_html",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Save All"),
		primary_action(values) {
			const entries = get_entries_from_table(dialog);
			if (!entries.length) {
				frappe.msgprint(__("Enter working days for at least one employee."));
				return;
			}
			frappe.call({
				method: "valence.valence.override.whitelisted_method.quarterly_working_days.bulk_create_quarterly_working_days",
				args: {
					entries: entries,
					company: values.company,
					quarter_start_date: values.quarter_start_date,
					quarter_end_date: values.quarter_end_date,
				},
				freeze: true,
				freeze_message: __("Saving..."),
				callback: function (r) {
					if (!r.message) return;
					dialog.hide();
					frappe.msgprint(
						__("Created {0}, updated {1} record(s).", [
							r.message.created_count,
							r.message.updated_count,
						])
					);
					cur_list.refresh();
				},
			});
		},
	});

	dialog.show();
}

function render_working_days_table(dialog) {
	const employees = dialog.get_value("employees") || [];
	const wrapper = dialog.fields_dict.working_days_table_html.$wrapper;

	if (!employees.length) {
		wrapper.html("");
		return;
	}

	let rows = employees
		.map(
			(emp) => `
			<tr>
				<td style="padding:4px 8px;">${frappe.utils.escape_html(emp)}</td>
				<td style="padding:4px 8px;">
					<input type="number" step="0.01" class="form-control qwd-working-days-input"
						data-employee="${frappe.utils.escape_html(emp)}" placeholder="Working days">
				</td>
			</tr>`
		)
		.join("");

	wrapper.html(`
		<table class="table table-bordered" style="margin-top:10px;">
			<thead><tr><th>${__("Employee")}</th><th>${__("Working Days")}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table>
	`);
}

function get_entries_from_table(dialog) {
	const wrapper = dialog.fields_dict.working_days_table_html.$wrapper;
	const entries = [];
	wrapper.find(".qwd-working-days-input").each(function () {
		const employee = $(this).data("employee");
		const working_days = $(this).val();
		if (employee && working_days) {
			entries.push({ employee: employee, working_days: parseFloat(working_days) });
		}
	});
	return entries;
}