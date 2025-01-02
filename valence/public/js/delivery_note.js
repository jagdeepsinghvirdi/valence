cur_frm.cscript.onload = function (frm) {
    cur_frm.set_query("batch_no", "items", function (doc, cdt, cdn) {
        let d = locals[cdt][cdn];
        if (!d.item_code) {
            frappe.throw(__("Please enter Item Code to get batch no"));
        }
        else {
            return {
                query: "valence.valence.override.whitelisted_method.query.get_batch_no",
                filters: {
                    'item_code': d.item_code,
                    'warehouse': d.warehouse,
                }
            }
        }
    });
}