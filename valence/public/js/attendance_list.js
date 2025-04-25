frappe.listview_settings["Attendance"] = {
    add_fields: ["status", "attendance_date"],

    get_indicator: function (doc) {
		if (["Present", "Work From Home"].includes(doc.status)) {
			return [__(doc.status), "green", "status,=," + doc.status];
		} else if (["Absent", "On Leave"].includes(doc.status)) {
			return [__(doc.status), "red", "status,=," + doc.status];
		} else if (doc.status == "Half Day") {
			return [__(doc.status), "orange", "status,=," + doc.status];
		}else if (["In Mispunch", "Out Mispunch"].includes(doc.status)) {
			return [__(doc.status), "blue", "status,=," + doc.status];
		} else if (doc.status == "No punch") {
			return [__(doc.status), "gray", "status,=," + doc.status];
		} else if (doc.status == "Present With Short Leave") {
		return [__(doc.status), "yellow", "status,=," + doc.status];
		} else if (["Holiday", "Weekly Off"].includes(doc.status)) {
		return [__(doc.status), "red", "status,=," + doc.status];
	}
	}
};