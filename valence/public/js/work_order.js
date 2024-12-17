frappe.ui.form.on('Work Order', {
    after_submit:function(frm){
        frm.reload_doc()
    },
    refresh:function(frm){
        if(frm.doc.docstatus == 1){
            frm.set_df_property("operations", "cannot_add_rows", true);
        }
    }
});
