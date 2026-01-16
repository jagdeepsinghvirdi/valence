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
    }
});
