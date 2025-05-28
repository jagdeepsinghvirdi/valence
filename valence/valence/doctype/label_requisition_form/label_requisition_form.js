frappe.ui.form.on('Label Requisition Form', {
    production_item: function (frm) {
        if (!frm.doc.production_item) {
            frm.set_df_property('spec', 'hidden', 1);
            return;
        }

        // Step 1: Get item_group of selected Item
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Item",
                filters: { name: frm.doc.production_item },
                fieldname: "item_group"
            },
            callback: function (item_res) {
                if (item_res.message) {
                    console.log(item_res);
                    let item_group = item_res.message.item_group;

                    // Step 2: Get parent_item_group of the item_group
                    frappe.call({
                        method: "frappe.client.get_value",
                        args: {
                            doctype: "Item Group",
                            filters: { name: item_group },
                            fieldname: "parent_item_group"
                        },
                        callback: function (group_res) {
                            console.log(group_res);
                            let parent_group = group_res.message ? group_res.message.parent_item_group : null;

                            if (item_group === "Finished Goods" || parent_group === "Finished Goods") {
                                frm.set_df_property('spec', 'hidden', 0);
                            } else {
                                frm.set_df_property('spec', 'hidden', 1);
                            }
                        }
                    });
                }
            }
        });
    },

    onload: function (frm) {
        frm.trigger('production_item');
    }
});
