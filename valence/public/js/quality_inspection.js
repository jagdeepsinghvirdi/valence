frappe.ui.form.on('Quality Inspection', {
    item_code: function (frm) {
        if (!frm.doc.item_code) {
            frm.set_df_property('custom_spec', 'hidden', 1);
            return;
        }

        // Step 1: Get item_group of selected Item
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Item",
                filters: { name: frm.doc.item_code },
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
                                frm.set_df_property('custom_spec', 'hidden', 0);
                            } else {
                                frm.set_df_property('custom_spec', 'hidden', 1);
                            }
                        }
                    });
                }
            }
        });
    },

    onload: function (frm) {
        frm.trigger('item_code');
    }
});
