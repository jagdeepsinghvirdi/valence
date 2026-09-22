frappe.ui.form.on("Shift Assignment", {
    refresh(frm) {
        valence_apply_left_status(frm);
        valence_apply_undo_left(frm);
    },

    status(frm) {
        valence_apply_left_status(frm);
    },
});

function valence_apply_left_status(frm) {
    const blocked_fields = ["shift_type", "shift_location", "custom_off_day"];
    const has_left = frm.doc.status === "Left";

    if (has_left) {
        blocked_fields.forEach((field) => {
            if (frm.fields_dict[field] && frm.doc[field]) {
                frm.set_value(field, null);
            }
        });
    }

    blocked_fields.forEach((field) => {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "read_only", has_left ? 1 : 0);
        }
    });

    frm.toggle_reqd("shift_type", !has_left);
    frm.refresh_fields(blocked_fields);
}

function valence_apply_undo_left(frm) {
    if (frm.doc.docstatus !== 1 || frm.doc.status !== "Left") {
        return;
    }

    frm.set_df_property("status", "read_only", 1);
    frm.refresh_field("status");

    frm.add_custom_button(__("Undo Left"), () => {
        frappe.confirm(
            __(
                "This will cancel this Left assignment. {0} will stop showing as Left in the Roster.",
                [frm.doc.employee_name || frm.doc.employee]
            ),
            () => frm.savecancel()
        );
    }).addClass("btn-danger");
}
