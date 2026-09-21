frappe.ui.form.on("Shift Assignment", {
    refresh(frm) {
        valence_apply_left_status(frm);
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
