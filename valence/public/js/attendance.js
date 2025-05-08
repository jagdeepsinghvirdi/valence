frappe.ui.form.on('Attendance', {
    refresh: function(frm) {
        frm.add_custom_button(__('Fetch Time'), function() {
            frappe.call({
                method: "valence.api.get_employee_checkin_entries",
                args: {
                    employee: frm.doc.employee,
                    attendance_date: frm.doc.attendance_date
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("Response from backend:", r.message);

                        const inTime = r.message.in_time;
                        const outTime = r.message.out_time;

                        // Only set the fields if at least one value is available
                        if (inTime || outTime) {
                            if (inTime) {
                                frm.set_value("in_time", inTime);
                            }
                            if (outTime) {
                                frm.set_value("out_time", outTime);
                            }
                            frm.refresh_fields();
                            frappe.msgprint("Employee check-in entries fetched successfully.");
                        } else {
                            frappe.call({
                                method: "valence.api.get_offday_status",
                                args: {
                                    employee: frm.doc.employee,
                                    attendance_date: frm.doc.attendance_date,
                                    attendance: frm.doc.name
                                },
                                callback: function(r) {
                                    console.log("checking for response",r.message)
                                    setTimeout(() => {
                                        frm.reload_doc().then(() => {
                                            if (
                                                frm.doc.status !== "Holiday" &&
                                                frm.doc.status !== "Weekly Off"
                                            ) {
                                                frappe.msgprint("No check-in entries found for the given date.");
                                            }
                                        });
                                    }, 1000); // Delay to allow backend update
                                }
                            });
                        }
                    } else {
                        frappe.msgprint(__("No data returned from server."));
                    }
                }
            });
        });
    }
});
