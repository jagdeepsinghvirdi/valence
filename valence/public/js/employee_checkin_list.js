frappe.listview_settings["Employee Checkin"] = frappe.listview_settings["Employee Checkin"] || {};

(() => {
    const settings = frappe.listview_settings["Employee Checkin"];
    const existing_onload = settings.onload;

    settings.onload = function (listview) {
        if (existing_onload) {
            existing_onload(listview);
        }
        valence_add_fetch_shifts_action(listview);
    };
})();

function valence_add_fetch_shifts_action(listview) {
    if (listview._valence_fetch_shifts_added) {
        return;
    }
    listview._valence_fetch_shifts_added = true;

    listview.page.add_action_item(__("Fetch Shifts"), () => {
        const checkins = listview.get_checked_items().map((checkin) => checkin.name);

        if (!checkins.length) {
            frappe.msgprint(__("Please select at least one Employee Checkin."));
            return;
        }

        frappe.call({
            method: "hrms.hr.doctype.employee_checkin.employee_checkin.bulk_fetch_shift",
            freeze: true,
            freeze_message: __("Fetching shifts..."),
            args: { checkins },
            callback: () => {
                frappe.show_alert({
                    message: __("Shifts fetched for {0} check-ins", [checkins.length]),
                    indicator: "green",
                });
                listview.refresh();
            },
        });
    });
}
