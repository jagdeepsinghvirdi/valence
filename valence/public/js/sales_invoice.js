cur_frm.cscript.onload = function (frm) {
    cur_frm.set_query("batch_no", "items", function (doc, cdt, cdn) {
        let d = locals[cdt][cdn];
        if (!d.item_code) {
            frappe.throw(__("Please enter Item Code to get batch no"));
        }
        else {
            if (d.item_group == "Finished Products"){
                return {
                    query: "valence.valence.override.whitelisted_method.query.get_batch_no",
                    filters: {
                        'item_code': d.item_code,
                        'warehouse': d.warehouse,
                    }
                }
            } else {
                return {
                    query: "valence.valence.override.whitelisted_method.query.get_batch_no",
                    filters: {
                        'item_code': d.item_code,
                        'warehouse': d.warehouse
                    }
                }
            }
        }
    });
}

frappe.ui.form.on('Sales Invoice Item', {

    item_code: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];

        if (!row.item_code) return;

        // Step 1: Fetch item_group of selected item
        frappe.db.get_value('Item', row.item_code, 'item_group').then(res => {
            const item_group = res.message.item_group;

            if (item_group === 'Finished Goods') {
                render_dialog_with_visibility(frm, cdn, true); // keep visible
            } else {
                // Step 2: Fetch parent_item_group
                frappe.db.get_value('Item Group', item_group, 'parent_item_group').then(r => {
                const parent_group = r.message.parent_item_group;
                if (parent_group === 'Finished Goods') {
                    render_dialog_with_visibility(frm, cdn, true); // Visible
                } else {
                    render_dialog_with_visibility(frm, cdn, false); // Not visible
                }
            });
            }
        });
    },

    custom_lrf_reference_name: function(frm, cdt, cdn) {       
        console.log("Custom LRF Reference Name changed");
        const row = locals[cdt][cdn];
        if (!row.custom_lrf_reference_name) return;

        frappe.call({
            method: "valence.api.fetch_lrf_details",
            args: {
                lrf_name: row.custom_lrf_reference_name
            },
             callback: function(r) {
                if (r.message && Array.isArray(r.message)) {
                    
                    const seal_nos = r.message.map(d => d.seal_no).filter(Boolean).join(', ');
                    const drum_nos = r.message.map(d => d.drum_no).filter(Boolean).join(', ');
                    const batch_no = r.message[0].batch_no;
                    const released_batch_no = r.message[0].released_batch_no;

                    frappe.model.set_value(cdt, cdn, "seal_no", seal_nos);
                    frappe.model.set_value(cdt, cdn, "pack_size", drum_nos);
                    frappe.model.set_value(cdt, cdn, "batch_item", batch_no);
                    frappe.model.set_value(cdt, cdn, "custom_released_b_no", released_batch_no);


                    if (batch_no) {
                        frappe.call({
                            method: "frappe.client.get",
                            args: {
                                doctype: "Batch",
                                name: batch_no
                            },
                            callback: function(res) {
                                if (res.message) {
                                    const batch = res.message;
                                    const formatMMMYY = (dateStr) => {
                                        const date = frappe.datetime.str_to_obj(dateStr);
                                        const month = date.toLocaleString('default', { month: 'short' }).toUpperCase();
                                        const year = date.getFullYear().toString().slice(-2);
                                        return `${month}-${year}`;
                                    };

                                    if (batch.manufacturing_date) {
                                        frappe.model.set_value(cdt, cdn, "mfg_date", formatMMMYY(batch.manufacturing_date));
                                    }
                                    if (batch.retest_date) {
                                        frappe.model.set_value(cdt, cdn, "date_expiry", formatMMMYY(batch.retest_date));
                                    }
                                }
                            }
                        });
                    }
                }
            }
        });
    },

    custom_grade:function(frm, cdt, cdn) {
        console.log("Please check that we are using grade...............")
        const row = locals[cdt][cdn];

        frappe.call({
            method: "valence.api.checking_item_grade",
            args: {
                item_code: row.item_code,
                item_name: row.item_name,
                lrf_name: row.custom_lrf_reference_name,
                grade_name: row.custom_grade
            } ,
            callback: function(r){
            }

        })
    }
});

function render_dialog_with_visibility(frm, cdn, show) {
    const grid = frm.fields_dict["items"].grid;
    const row = grid.grid_rows_by_docname[cdn];
    if (!row) return;

    row.toggle_view(true); // Open dialog

    // Wait for the form to render
    setTimeout(() => {
        const grid_form = row.grid_form;
        if (!grid_form) return;

        ['custom_lrf_reference_name','custom_grade','custom_released_b_no'].forEach(fieldname => {
            const field = grid_form.fields_dict[fieldname];
            if (field) {
                field.df.hidden = !show;
                field.refresh();
            }
        });
    }, 1000);
}



