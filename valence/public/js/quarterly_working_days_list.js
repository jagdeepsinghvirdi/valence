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
				onchange: () => maybe_load_preview(dialog),
			},
			{
				fieldname: "leave_type",
				fieldtype: "Link",
				options: "Leave Type",
				label: __("Leave Type"),
				reqd: 1,
				onchange: () => maybe_load_preview(dialog),
			},
			{
				fieldname: "quarter_start_date",
				fieldtype: "Date",
				label: __("Quarter Start Date"),
				reqd: 1,
				onchange: () => maybe_load_preview(dialog),
			},
			{
				fieldname: "quarter_end_date",
				fieldtype: "Date",
				label: __("Quarter End Date"),
				reqd: 1,
				onchange: () => maybe_load_preview(dialog),
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
				frappe.msgprint(__("No employees to save."));
				return;
			}
			frappe.call({
				method: "valence.valence.override.whitelisted_method.quarterly_working_days.bulk_create_quarterly_working_days",
				args: {
					entries: entries,
					company: values.company,
					leave_type: values.leave_type,
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

function maybe_load_preview(dialog) {
	const company = dialog.get_value("company");
	const leave_type = dialog.get_value("leave_type");
	const start = dialog.get_value("quarter_start_date");
	const end = dialog.get_value("quarter_end_date");

	if (!company || !leave_type || !start || !end) return;

	frappe.call({
		method: "valence.valence.override.whitelisted_method.quarterly_working_days.get_working_days_preview",
		args: { company: company, quarter_start_date: start, quarter_end_date: end },
		freeze: true,
		freeze_message: __("Loading employees..."),
		callback: function (r) {
			render_working_days_table(dialog, r.message || []);
		},
	});
}

function render_working_days_table(dialog, employees) {
	const wrapper = dialog.fields_dict.working_days_table_html.$wrapper;

	if (!employees.length) {
		wrapper.html(`<p class="text-muted">${__("No active employees found.")}</p>`);
		return;
	}

	let rows = employees
		.map((emp) => {
			const hasData = emp.working_days !== null && emp.working_days !== undefined;
			const valueAttr = hasData ? `value="${emp.working_days}"` : "";
			const rowClass = hasData ? "" : "qwd-no-data-row";
			return `
			<tr class="${rowClass}">
				<td style="padding:4px 8px;">${frappe.utils.escape_html(emp.employee_name)} (${frappe.utils.escape_html(emp.employee)})</td>
				<td style="padding:4px 8px;">
					<input type="number" step="0.01" class="form-control qwd-working-days-input"
						data-employee="${frappe.utils.escape_html(emp.employee)}"
						${valueAttr}
						placeholder="${hasData ? "" : __("No attendance data")}">
					${!hasData ? `<div class="text-muted" style="font-size:11px;margin-top:2px;">${__("No Attendance records found for this quarter — enter manually if needed")}</div>` : ""}
				</td>
			</tr>`;
		})
		.join("");

	wrapper.html(`
		<style>
			.qwd-no-data-row td { background-color: #fff8e6; }
		</style>
		<table class="table table-bordered" style="margin-top:10px;">
			<thead><tr><th>${__("Employee")}</th><th>${__("Working Days (from Attendance)")}</th></tr></thead>
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