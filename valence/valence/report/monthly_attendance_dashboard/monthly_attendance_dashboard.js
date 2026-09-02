const VALENCE_MONTHS = [
	{ value: 1, label: __("January") },
	{ value: 2, label: __("February") },
	{ value: 3, label: __("March") },
	{ value: 4, label: __("April") },
	{ value: 5, label: __("May") },
	{ value: 6, label: __("June") },
	{ value: 7, label: __("July") },
	{ value: 8, label: __("August") },
	{ value: 9, label: __("September") },
	{ value: 10, label: __("October") },
	{ value: 11, label: __("November") },
	{ value: 12, label: __("December") },
];

const VALENCE_STATUS_CLASS = {
	"Work From Home": "valence-att-wfh",
	"Present With Short Leave": "valence-att-short-leave",
	Mispunch: "valence-att-mispunch",
};

const VALENCE_CODE_CLASS = {
	A: "valence-att-absent",
	MP: "valence-att-mispunch",
	WO: "valence-att-weekly-off",
	H: "valence-att-holiday",
	HP: "valence-att-holiday-worked",
	"HP/A": "valence-att-holiday-worked",
	"2HP": "valence-att-holiday-worked",
	"2HP/A": "valence-att-holiday-worked",
	PWO: "valence-att-weekly-off-worked",
	PAW: "valence-att-weekly-off-worked",
	"2PWO": "valence-att-weekly-off-worked",
	"2PAW": "valence-att-weekly-off-worked",
	"2P": "valence-att-double",
	"2P/A": "valence-att-double",
	TT: "valence-att-on-duty",
};

function valence_current_month() {
	return frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth() + 1;
}

function valence_current_year() {
	return frappe.datetime.str_to_obj(frappe.datetime.get_today()).getFullYear();
}

frappe.query_reports["Monthly Attendance Dashboard"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: VALENCE_MONTHS.map((m) => ({ value: m.value, label: m.label })),
			default: valence_current_month(),
			reqd: 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: valence_current_year(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "function",
			label: __("Function"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "module",
			label: __("Module"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "status",
			label: __("Employee Status"),
			fieldtype: "Select",
			options: ["", "Active", "Inactive", "Suspended", "Left"],
		},
	],

	formatter(value, row, column, data, default_formatter) {
		const day_match = column.fieldname && column.fieldname.match(/^d(\d+)$/);

		if (day_match && value) {
			const status = data ? data[`${column.fieldname}_status`] : null;
			const css =
				VALENCE_STATUS_CLASS[status] || VALENCE_CODE_CLASS[value] || "valence-att-present";
			return `<span class="valence-att-code ${css}">${frappe.utils.escape_html(
				String(value)
			)}</span>`;
		}

		return default_formatter(value, row, column, data);
	},

	onload(report) {
		valence_inject_styles();

		report._valence_active_row = null;
		$(report.page.wrapper).on("click", ".dt-cell", function () {
			const index = $(this).attr("data-row-index");
			if (index !== undefined) {
				report._valence_active_row = parseInt(index, 10);
			}
		});

		report.page.add_inner_button(__("Edit Hold / Remarks"), () => {
			valence_edit_remark_dialog(report);
		});
	},
};

function valence_inject_styles() {
	if (document.getElementById("valence-attendance-dashboard-styles")) {
		return;
	}

	const style = document.createElement("style");
	style.id = "valence-attendance-dashboard-styles";
	style.textContent = `
		.valence-att-code { display:inline-block; min-width:34px; text-align:center;
			padding:1px 4px; border-radius:3px; font-weight:600; font-size:11px; }
		.valence-att-present { background:#e6f4ea; color:#137333; }
		.valence-att-wfh { background:#e8f0fe; color:#1a56db; }
		.valence-att-short-leave { background:#fef7e0; color:#8a6100; }
		.valence-att-absent { background:#fce8e6; color:#b3261e; }
		.valence-att-mispunch { background:#e8eaed; color:#3c4043; }
		.valence-att-weekly-off { background:#f1f3f4; color:#5f6368; }
		.valence-att-weekly-off-worked { background:#e0f7fa; color:#00696e; }
		.valence-att-holiday { background:#f3e8fd; color:#6b21a8; }
		.valence-att-holiday-worked { background:#ede0fb; color:#4a148c; }
		.valence-att-double { background:#fff0e0; color:#9a3412; }
		.valence-att-on-duty { background:#e0f2f1; color:#00695c; }
	`;
	document.head.appendChild(style);
}

function valence_edit_remark_dialog(report) {
	const data = report.data || [];
	let index = report._valence_active_row;

	const checked =
		report.datatable && report.datatable.rowmanager
			? report.datatable.rowmanager.getCheckedRows()
			: [];

	if (checked && checked.length === 1) {
		index = parseInt(checked[0], 10);
	} else if (checked && checked.length > 1) {
		frappe.msgprint(__("Please select only one employee row."));
		return;
	}

	if (index === null || index === undefined || !data[index]) {
		frappe.msgprint(__("Click any cell in an employee row first, then choose Edit Hold / Remarks."));
		return;
	}

	const record = data[index];
	if (!record || !record.employee) {
		frappe.msgprint(__("Could not determine the selected employee."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Hold / Remarks for {0}", [record.employee_name || record.employee]),
		fields: [
			{
				fieldname: "hold",
				label: __("Hold"),
				fieldtype: "Select",
				options: ["", "Left", "Resignation", "Leave Not Approved"],
				default: record.hold || "",
			},
			{
				fieldname: "remarks",
				label: __("Remarks"),
				fieldtype: "Small Text",
				default: record.remarks || "",
			},
			{
				fieldname: "hr_remarks",
				label: __("HR Remarks"),
				fieldtype: "Small Text",
				default: record.hr_remarks || "",
			},
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			frappe
				.xcall(
					"valence.valence.report.monthly_attendance_dashboard.monthly_attendance_dashboard.save_month_remark",
					{
						employee: record.employee,
						month: report.get_filter_value("month"),
						year: report.get_filter_value("year"),
						hold: values.hold,
						remarks: values.remarks,
						hr_remarks: values.hr_remarks,
					}
				)
				.then(() => {
					dialog.hide();
					frappe.show_alert({
						message: __("Remarks saved"),
						indicator: "green",
					});
					report.refresh();
				});
		},
	});

	dialog.show();
}
