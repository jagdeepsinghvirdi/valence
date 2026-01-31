frappe.listview_settings["Attendance"] = {
    add_fields: ["status", "attendance_date"],

    get_indicator: function (doc) {
		if (["Present", "Work From Home","On Duty"].includes(doc.status)) {
			return [__(doc.status), "green", "status,=," + doc.status];
		} else if (["Absent", "On Leave"].includes(doc.status)) {
			return [__(doc.status), "red", "status,=," + doc.status];
		} else if (doc.status == "Half Day") {
			return [__(doc.status), "orange", "status,=," + doc.status];
		}else if (["Mispunch"].includes(doc.status)) {
			return [__(doc.status), "blue", "status,=," + doc.status];
		} else if (doc.status == "No punch") {
			return [__(doc.status), "gray", "status,=," + doc.status];
		} else if (doc.status == "Present With Short Leave") {
		return [__(doc.status), "yellow", "status,=," + doc.status];
		} else if (["Holiday", "Weekly Off"].includes(doc.status)) {
		return [__(doc.status), "red", "status,=," + doc.status];
	    }else if (["On Duty", "Weekly Off"].includes(doc.status)) {
		return [__(doc.status), "gray", "status,=," + doc.status];
	    }
	},
	onload(listview) {
        listview.page.add_action_item(__('Fetch Time'), () => {
            const selected_docs = listview.get_checked_items();

            if (!selected_docs.length) {
                frappe.msgprint(__('Please select at least one Attendance record.'));
                return;
            }

            let messages = [];
            let calls = [];

            selected_docs.forEach(doc => {
                if (doc.status === 'No punch') {
                    calls.push(
                        frappe.call({
                            method: "valence.api.get_employee_checkin_entries_multiple",
                            args: {
                                employee: doc.employee,
                                attendance_date: doc.attendance_date,
                                attendance: doc.name
                            }
                        }).then(r => {
                            if (r.message) {
                                messages.push(r.message.message);
                            }
                        })
                    );
                }
            });

            if (!calls.length) {
                frappe.msgprint(__('No selected records with status "No punch".'));
                return;
            }

            Promise.all(calls).then(() => {
                frappe.msgprint({
                    title: __('Fetch Time Results'),
                    message: messages.join('<br>'),
                    indicator: 'blue'
                });

                listview.refresh();
            });
        });
    },

    refresh(listview) {
        const has_selection = listview.get_checked_items().length > 0;
        listview.page.actions.find(a => a.label === 'Fetch Time')?.toggle(has_selection);
    }
};
