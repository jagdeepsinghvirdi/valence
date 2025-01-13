import frappe
from frappe import _

def execute(filters):
    if not filters:
        frappe.throw(_("Please select a Work Order or a Batch to proceed."))
        
    work_order = filters.get("work_order")
    batch = filters.get("batch")
    
    # Validate Work Order or Batch
    if work_order and not frappe.db.exists("Work Order", work_order):
        frappe.throw(_("The selected Work Order does not exist."))
    if batch and not frappe.db.exists("Batch", batch):
        frappe.throw(_("The selected Batch does not exist."))
        
    columns = [
        {
            "fieldname": "item_code",
            "label": _("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 200
        },
        {
            "fieldname": "item_name",
            "label": _("Item Name"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "item_group",
            "label": _("Item Group"),
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 120
        },
        {
            "fieldname": "qty",
            "label": _("Quantity"),
            "fieldtype": "Float",
            "precision": 3,
            "width": 100
        },
        {
            "fieldname": "batch_no",
            "label": _("Batch No"),
            "fieldtype": "Link",
            "options": "Batch",
            "width": 150
        }
    ]
    
    def fetch_stock_entries(work_order=None, batch=None, parent_item_code=None, indent=0):
        """Recursively fetch stock entries and related data."""
        tree_data = []
        conditions = []
        params = []

        if work_order:
            conditions.append("se.work_order = %s")
            params.append(work_order)
        if batch:
            conditions.append("IFNULL(sbe.batch_no, '') = %s")
            params.append(batch)
        
        condition_str = " AND ".join(conditions)

        # Fetch finished goods for the given Work Order or Batch
        stock_entries = frappe.db.sql(f""" 
            SELECT 
                se.name AS stock_entry,
                sed.item_code AS finished_item_code,
                sed.item_name AS finished_item_name,
                sed.item_group AS finished_item_group,
                sed.qty AS finished_item_qty,
                IFNULL(sbe.batch_no, '') AS finished_batch_no
            FROM 
                `tabStock Entry` se
            JOIN 
                `tabStock Entry Detail` sed ON se.name = sed.parent
            LEFT JOIN 
                `tabSerial and Batch Entry` sbe ON sbe.parent = sed.serial_and_batch_bundle
            WHERE 
                {condition_str} 
                AND se.stock_entry_type = 'Manufacture'
                AND sed.is_finished_item = 1
            ORDER BY 
                se.posting_date, se.posting_time
        """, tuple(params), as_dict=1)
        
        for stock_entry in stock_entries:
            # Add finished item as a parent node
            parent_node = {
                "item_code": stock_entry.finished_item_code,
                "item_name": stock_entry.finished_item_name,
                "item_group": stock_entry.finished_item_group,
                "qty": stock_entry.finished_item_qty,
                "batch_no": stock_entry.finished_batch_no,
                "parent_item_code": parent_item_code or "",  # Empty for top-level parent
                "is_finished_item": 1,
                "stock_entry": stock_entry.stock_entry,
                "indent": indent  # Root or child level
            }
            tree_data.append(parent_node)
            
            # Get raw materials for this stock entry
            raw_materials = frappe.db.sql(""" 
                SELECT 
                    sed.item_code,
                    sed.item_name,
                    sed.item_group,
                    sed.qty,
                    IFNULL(sbe.batch_no, '') AS batch_no
                FROM 
                    `tabStock Entry` se
                JOIN 
                    `tabStock Entry Detail` sed ON se.name = sed.parent
                LEFT JOIN 
                    `tabSerial and Batch Entry` sbe ON sbe.parent = sed.serial_and_batch_bundle
                WHERE 
                    se.name = %s
                    AND sed.is_finished_item = 0
                ORDER BY 
                    sed.idx
            """, stock_entry.stock_entry, as_dict=1)
            
            for material in raw_materials:
                # Add raw material as child node
                child_node = {
                    "item_code": material.item_code,
                    "item_name": material.item_name,
                    "item_group": material.item_group,
                    "qty": material.qty,
                    "batch_no": material.batch_no,
                    "parent_item_code": stock_entry.finished_item_code,  # Link to parent
                    "is_finished_item": 0,
                    "indent": indent + 1  # Child level
                }
                tree_data.append(child_node)
                
                # Check if this raw material batch is linked to another Work Order
                if material.batch_no:
                    linked_work_order = frappe.db.get_value(
                        "Work Order",
                        {"batch_no": material.batch_no},
                        "name"
                    )
                    if linked_work_order and linked_work_order != work_order:
                        # Recursively fetch stock entries for the linked work order
                        tree_data.extend(
                            fetch_stock_entries(linked_work_order, None, material.item_code, indent + 2)
                        )
        
        return tree_data
    
    tree_data = fetch_stock_entries(work_order, batch)
    return columns, tree_data
