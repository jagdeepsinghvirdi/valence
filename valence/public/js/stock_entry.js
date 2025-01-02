frappe.ui.form.on("Stock Entry", {
    onload: function(frm){
        frappe.db.get_value("Company", frm.doc.company, "maintain_as_is_new", function(c) {
            if(!c.maintain_as_is_new) {
                frm.set_query("batch_no", "items", function (doc, cdt, cdn) {
                    let d = locals[cdt][cdn];
                    if (!d.item_code) {
                        frappe.msgprint(__("Please select Item Code"));
                    }
                    else if (!d.s_warehouse) {
                        frappe.msgprint(__("Please select source warehouse"));
                    }
                    else {
                        return {
                            query: "valence.valence.override.whitelisted_method.query.get_batch_no",
                            filters: {
                                'item_code': d.item_code,
                                'warehouse': d.s_warehouse
                            }
                        }
                    }
                })
                if(frm.doc.__islocal){

                    frm.doc.items.forEach(function (d){
                        if (d.qty && d.quantity == 0) {
                            frappe.model.set_value(d.doctype, d.name, "quantity", d.qty);
                        }
                        if(d.basic_rate && d.price == 0){
                            frappe.model.set_value(d.doctype, d.name, "price", d.basic_rate);
                        }
                    });
                    frm.refresh_field('items');
                }

                if(frm.doc.work_order){
                    frappe.db.get_value("Work Order", frm.doc.work_order, 'skip_transfer', function (r) {
                        if (r.skip_transfer == 1) {
                            cur_frm.set_df_property("get_raw_materials", "hidden", 0);
                        }
                    });
                }
            } else {
                //
            }
        })
    },
})