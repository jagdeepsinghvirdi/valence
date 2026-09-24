const VALENCE_REBUILD_MONTHS = [
    { value: 1, label: "January" },
    { value: 2, label: "February" },
    { value: 3, label: "March" },
    { value: 4, label: "April" },
    { value: 5, label: "May" },
    { value: 6, label: "June" },
    { value: 7, label: "July" },
    { value: 8, label: "August" },
    { value: 9, label: "September" },
    { value: 10, label: "October" },
    { value: 11, label: "November" },
    { value: 12, label: "December" },
];

function valence_period_fields() {
    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());

    return [
        {
            fieldname: "employee",
            label: __("Employee"),
            fieldtype: "Link",
            options: "Employee",
            description: __("Leave blank to use Department"),
        },
        {
            fieldname: "department",
            label: __("Department"),
            fieldtype: "Link",
            options: "Department",
            description: __("Includes sub departments"),
        },
        { fieldtype: "Section Break" },
        {
            fieldname: "month",
            label: __("Month"),
            fieldtype: "Select",
            options: VALENCE_REBUILD_MONTHS.map((m) => ({ value: m.value, label: __(m.label) })),
            default: today.getMonth() + 1,
            reqd: 1,
        },
        {
            fieldname: "year",
            label: __("Year"),
            fieldtype: "Int",
            default: today.getFullYear(),
            reqd: 1,
        },
    ];
}

function valence_validate_scope(values) {
    if (!values.employee && !values.department) {
        frappe.msgprint(__("Please select an Employee or a Department."));
        return false;
    }
    return true;
}

function valence_open_rebuild_dialog(on_done) {
    const dialog = new frappe.ui.Dialog({
        title: __("Fetch Month Check-ins"),
        fields: valence_period_fields().concat([
            {
                fieldname: "missing_only",
                label: __("Only missing dates"),
                fieldtype: "Check",
                default: 1,
                description: __("Dates that already have Attendance are left untouched"),
            },
        ]),
        primary_action_label: __("Fetch"),
        primary_action(values) {
            if (!valence_validate_scope(values)) {
                return;
            }
            dialog.hide();
            frappe.call({
                method: "valence.valence.doc_events.attendance_rebuild.rebuild_month",
                args: values,
                freeze: true,
                freeze_message: __("Rebuilding attendance..."),
                callback: (r) => {
                    if (!r.message) {
                        return;
                    }
                    valence_show_rebuild_result(r.message);
                    if (on_done) {
                        on_done();
                    }
                },
            });
        },
    });

    dialog.show();
}

function valence_open_fetch_shifts_dialog(on_done) {
    const dialog = new frappe.ui.Dialog({
        title: __("Fetch Shifts for Month"),
        fields: valence_period_fields(),
        primary_action_label: __("Fetch Shifts"),
        primary_action(values) {
            if (!valence_validate_scope(values)) {
                return;
            }
            dialog.hide();
            frappe.call({
                method: "valence.valence.doc_events.attendance_rebuild.fetch_month_shifts",
                args: values,
                freeze: true,
                freeze_message: __("Matching check-ins to shifts..."),
                callback: (r) => {
                    if (!r.message) {
                        return;
                    }
                    valence_show_fetch_shifts_result(r.message);
                    if (on_done) {
                        on_done();
                    }
                },
            });
        },
    });

    dialog.show();
}

function valence_result_title(result) {
    if (result.employee_count === 1 && result.employees && result.employees.length) {
        const only = result.employees[0];
        return `${only.employee_name || only.employee} - ${result.month}/${result.year}`;
    }
    return __("{0} employees - {1}/{2}", [result.employee_count, result.month, result.year]);
}

function valence_show_rebuild_result(result) {
    const header = `<p>${__("Created")}: <b>${result.created}</b> &nbsp; ${__("Updated")}: <b>${
        result.updated
    }</b> &nbsp; ${__("Unchanged")}: <b>${result.skipped}</b></p>`;

    let table = "";

    if (result.rows && result.rows.length) {
        const rows = result.rows
            .map((row) => {
                const colour =
                    { created: "green", updated: "blue", skipped: "gray" }[row.action] || "gray";
                return `
                    <tr>
                        <td>${frappe.datetime.str_to_user(row.date)}</td>
                        <td>${row.status ? frappe.utils.escape_html(row.status) : "-"}</td>
                        <td><span class="indicator ${colour}">${__(row.action)}</span></td>
                        <td>${frappe.utils.escape_html(row.note || "")}</td>
                    </tr>
                `;
            })
            .join("");

        table = `
            <table class="table table-bordered" style="font-size: 12px;">
                <thead><tr>
                    <th>${__("Date")}</th><th>${__("Status")}</th><th>${__("Action")}</th><th>${__("Note")}</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    } else {
        const rows = (result.employees || [])
            .map(
                (row) => `
                    <tr>
                        <td>${frappe.utils.escape_html(row.employee_name || row.employee)}</td>
                        <td>${row.created}</td>
                        <td>${row.updated}</td>
                        <td>${row.skipped}</td>
                    </tr>
                `
            )
            .join("");

        table = `
            <table class="table table-bordered" style="font-size: 12px;">
                <thead><tr>
                    <th>${__("Employee")}</th><th>${__("Created")}</th><th>${__("Updated")}</th><th>${__("Unchanged")}</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    frappe.msgprint({
        title: valence_result_title(result),
        indicator: "blue",
        message: header + table,
    });
}

function valence_show_fetch_shifts_result(result) {
    const rows = (result.employees || [])
        .map(
            (row) => `
                <tr>
                    <td>${frappe.utils.escape_html(row.employee_name || row.employee)}</td>
                    <td>${row.checkins}</td>
                    <td>${row.matched}</td>
                    <td>${row.unmatched}</td>
                </tr>
            `
        )
        .join("");

    frappe.msgprint({
        title: valence_result_title(result),
        indicator: result.unmatched ? "orange" : "green",
        message: `
            <p>${__("Check-ins")}: <b>${result.checkins}</b> &nbsp; ${__("Matched to a shift")}: <b>${
            result.matched
        }</b> &nbsp; ${__("Unmatched")}: <b>${result.unmatched}</b></p>
            <table class="table table-bordered" style="font-size: 12px;">
                <thead><tr>
                    <th>${__("Employee")}</th><th>${__("Check-ins")}</th><th>${__("Matched")}</th><th>${__("Unmatched")}</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
            <p style="margin-top:8px;color:#6b7280;font-size:12px;">${__(
                "Unmatched check-ins fall outside every assigned shift window for that date."
            )}</p>
        `,
    });
}

const VALENCE_LIST_BUTTONS = {
    "Employee Checkin": {
        label: "Fetch Shifts for Month",
        open: () => valence_open_fetch_shifts_dialog(() => cur_list && cur_list.refresh()),
    },
    Attendance: {
        label: "Fetch Month Check-ins",
        open: () => valence_open_rebuild_dialog(() => cur_list && cur_list.refresh()),
    },
};

function valence_mount_list_button() {
    const route = frappe.get_route ? frappe.get_route() : null;
    if (!route || route[0] !== "List") {
        return;
    }

    const config = VALENCE_LIST_BUTTONS[route[1]];
    if (!config || !window.cur_list || cur_list.doctype !== route[1] || !cur_list.page) {
        return;
    }

    const label = __(config.label);
    const toolbar = cur_list.page.inner_toolbar;
    if (toolbar && toolbar.find("button").filter((_, el) => $(el).text().trim() === label).length) {
        return;
    }

    cur_list.page.add_inner_button(label, config.open);
}

function valence_watch_list_routes() {
    const mount = () => setTimeout(valence_mount_list_button, 400);

    if (frappe.router && frappe.router.on) {
        frappe.router.on("change", mount);
    }
    $(document).on("list_view_loaded", mount);
    mount();
}

$(document).ready(valence_watch_list_routes);

window.valence_open_rebuild_dialog = valence_open_rebuild_dialog;
window.valence_open_fetch_shifts_dialog = valence_open_fetch_shifts_dialog;
window.valence_show_rebuild_result = valence_show_rebuild_result;
window.valence_show_fetch_shifts_result = valence_show_fetch_shifts_result;
