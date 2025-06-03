frappe.ui.form.on('Label Requisition Form', {
     no_of_packages(frm) {
        let total_containers = frm.doc.no_of_packages;

        if (total_containers && total_containers > 0) {
            frm.clear_table("label_details");

            for (let i = 1; i <= total_containers; i++) {
                let row = frm.add_child("label_details");
                row.drum_no = `${String(i).padStart(2, '0')}/${total_containers}`;
            }

            frm.refresh_field("label_details");
        }
    }
});
