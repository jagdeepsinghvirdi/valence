import frappe

def get_batch_and_lot_number_from_serial_and_batch_bundle(serial_nos):
    if not serial_nos:
        return ""
    
    sbe = frappe.qb.DocType("Serial and Batch Entry")
    batch = frappe.qb.DocType("Batch")

    data = (
        frappe.qb.select(
            sbe.batch_no,
            batch.ar_no,
        ).
        from_(sbe).
        join(batch).
        on(sbe.batch_no == batch.name)
        .where(
            (sbe.parenttype == "Serial and Batch Bundle") &
            (sbe.parent.isin(serial_nos))
        ).groupby(sbe.batch_no)
    ).run(as_dict=True)

    lot_list = []

    for row in data:
        if row.ar_no:
            lot_list.append(f"{row.batch_no} - {row.ar_no}")
        else:
            lot_list.append(f"{row.batch_no}")

    return ", ".join(lot_list)