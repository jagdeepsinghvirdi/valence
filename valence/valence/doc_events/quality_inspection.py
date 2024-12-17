import frappe

def on_submit(self, method):
    if self.reference_type == "Purchase Receipt":
        ref_doctype = frappe.get_doc(self.reference_type, self.reference_name)
        for row in ref_doctype.items:
            if self.item_code == row.item_code:
                row.lot_no = self.lot_no
        ref_doctype.save()

            
            
      