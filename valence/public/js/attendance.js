frappe.ui.form.on('Attendance', {
    refresh: function(frm) {
        frm.add_custom_button(__('Fetch Time'), function() {
            frappe.call({
                method: "valence.api.get_employee_checkin_entries",
                args: {
                    employee: frm.doc.employee,
                    attendance_date: frm.doc.attendance_date,
                    doc: frm.doc.name
                },
                callback: function(r) {
                    // 1. Always reload first so the user sees the DB changes
                    frm.reload_doc().then(() => {
                        if (r.message) {
                            if (r.message.in_time || r.message.out_time) {
                                frappe.show_alert({
                                    message: __("Check-in entries updated successfully"),
                                    indicator: 'green'
                                });
                            } else {
                                frappe.msgprint(__("No check-in entries found for this date. Status updated to: " + frm.doc.status));
                            }
                        }
                    });
                }
            });
        });

        valence_bind_connection_actions(frm);
        frm.trigger("show_leave_connections");
    },

    show_leave_connections: function(frm) {
        if (frm.is_new() || !frm.doc.employee || !frm.doc.attendance_date) {
            return;
        }

        frappe.call({
            method: "valence.api.get_attendance_connections",
            args: {
                employee: frm.doc.employee,
                attendance_date: frm.doc.attendance_date
            },
            callback: function(r) {
                const data = r.message || {};
                const leaves = data.leave_applications || [];
                const short_leaves = data.short_leave_applications || [];

                const render = (doctype, rows, subtitle_field) => {
                    if (!rows.length) {
                        return `<div class="text-muted">${__("None")}</div>`;
                    }
                    return rows.map(row => {
                        const route = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(row.name)}`;
                        const label = frappe.utils.escape_html(row.name);
                        const subtitle = row[subtitle_field]
                            ? ` <span class="text-muted">${frappe.utils.escape_html(row[subtitle_field])}</span>`
                            : "";
                        return `<div><a href="${route}">${label}</a>${subtitle}</div>`;
                    }).join("");
                };

                const add_btn = (doctype) =>
                    `<button type="button" class="btn btn-xs btn-default valence-conn-add" data-doctype="${doctype}"
                        style="margin-left:6px;padding:0 6px;line-height:1.4">+</button>`;

                const html = `
                    <div class="valence-leave-connections row">
                        <div class="col-sm-6">
                            <h6>${__("Leave Application")}${add_btn("Leave Application")}</h6>
                            ${render("Leave Application", leaves, "leave_type")}
                        </div>
                        <div class="col-sm-6">
                            <h6>${__("Short Leave")}${add_btn("Short Leave Application")}</h6>
                            ${render("Short Leave Application", short_leaves, "short_leave_type")}
                        </div>
                    </div>
                `;

                try {
                    if (frm.dashboard && frm.dashboard.wrapper) {
                        $(frm.dashboard.wrapper).find(".valence-leave-connections").closest(".form-dashboard-section").remove();
                    }

                    if (frm.dashboard && typeof frm.dashboard.add_section === "function") {
                        frm.dashboard.add_section(html, __("Leave Connections"));
                    } else if (frm.dashboard && frm.dashboard.wrapper) {
                        $(frm.dashboard.wrapper).append(html);
                    }

                    valence_bind_connection_actions(frm);
                } catch (e) {
                    console.error("Valence: could not render attendance connections", e);
                }
            }
        });
    }
});

function valence_new_attendance_linked_doc(frm, doctype) {
    const date = frm.doc.attendance_date;
    const values = {
        employee: frm.doc.employee,
        company: frm.doc.company,
    };

    if (doctype === "Leave Application") {
        values.from_date = date;
        values.to_date = date;
    } else if (doctype === "Short Leave Application") {
        values.date = date;
    }

    frappe.new_doc(doctype, values);
}

function valence_bind_connection_actions(frm) {
    if (frm.__valence_conn_bound) {
        return;
    }
    frm.__valence_conn_bound = true;

    $(frm.wrapper).on("click", ".valence-conn-add", function (e) {
        e.preventDefault();
        e.stopPropagation();
        valence_new_attendance_linked_doc(frm, $(this).attr("data-doctype"));
    });
}
