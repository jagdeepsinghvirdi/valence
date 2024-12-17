

frappe.ui.form.on('Production Plan', {
    refresh:function(frm){
        if (frm.doc.po_items && frm.doc.status !== "Closed") {
            frm.add_custom_button(
                __("Work Order with Sub Assembly Items"),
                () => {
                    frm.trigger("make_work_order_for_sub_assembly");
                },
                __("Create")
            );
        }
    },
    make_work_order_for_sub_assembly(frm) {
		frappe.call({
			method: "make_work_order_with_sub_assembly_item",
			freeze: true,
			doc: frm.doc,
			callback: function () {
				frm.reload_doc();
			},
		});
	},
});


