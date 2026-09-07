frappe.ui.form.on("Work Order", {
	after_submit: function (frm) {
		frm.reload_doc();
	},
	refresh: function (frm) {
		if (frm.doc.docstatus == 1) {
			frm.set_df_property("operations", "cannot_add_rows", true);
		}
		// ERPNext hides Finish / Material Consumption when header
		// material_transferred_for_manufacturing is 0 (pick-list / partial transfer
		// min-fraction), even though item-level transferred_qty > 0 and Start still shows.
		valence.work_order.ensure_finish_and_consumption_buttons(frm);
	},
});

frappe.provide("valence.work_order");

/*
Verify on a WO that shows Start but not Finish (e.g. MFG-WO-2026-00734):
1. Required Items: note transferred_qty / consumed_qty / required_qty per row.
2. Header: material_transferred_for_manufacturing (often 0 after partial pick-list).
3. Manufacturing Settings: material_consumption must be 1 for Consumption button.
4. After bench build / clear-cache + hard refresh: Finish should appear if any
   transferred_qty > 0 and produced_qty is still below effective transferred qty;
   Material Consumption if setting on and any item still has unconsumed transfer.
*/

valence.work_order = {
	has_item_level_transfer: function (frm) {
		return (frm.doc.required_items || []).some((item) => flt(item.transferred_qty) > 0);
	},

	has_actual_material_transfer: function (frm) {
		return (
			flt(frm.doc.material_transferred_for_manufacturing) > 0 ||
			cint(frm.doc.skip_transfer) ||
			this.has_item_level_transfer(frm)
		);
	},

	/** Effective FG qty transferable when header field is stuck at 0 after partial pick-list. */
	get_effective_material_transferred: function (frm) {
		let mt = flt(frm.doc.material_transferred_for_manufacturing);
		if (mt > 0) {
			return mt;
		}
		if (cint(frm.doc.skip_transfer) || this.has_item_level_transfer(frm)) {
			return flt(frm.doc.qty);
		}
		return 0;
	},

	has_pending_consumption: function (frm) {
		return (frm.doc.required_items || []).some((item) => {
			let wo_item_qty = flt(item.transferred_qty) || flt(item.required_qty);
			return wo_item_qty > flt(item.consumed_qty);
		});
	},

	button_exists: function (frm, label) {
		let $btn = frm.page.inner_toolbar
			? frm.page.inner_toolbar.find(`button:contains("${label}")`)
			: $();
		if ($btn.length) {
			return true;
		}
		// Also check custom button group / menu
		return !!(frm.custom_buttons && frm.custom_buttons[label]);
	},

	ensure_finish_and_consumption_buttons: function (frm) {
		let doc = frm.doc;
		if (doc.docstatus !== 1 || ["Closed", "Completed", "Stopped"].includes(doc.status)) {
			return;
		}
		if (!this.has_actual_material_transfer(frm)) {
			return;
		}

		let effective_mt = this.get_effective_material_transferred(frm);

		// Material Consumption — ERPNext only checks header mt / skip_transfer
		if (
			frm.doc.__onload &&
			cint(frm.doc.__onload.material_consumption) === 1 &&
			this.has_pending_consumption(frm) &&
			!this.button_exists(frm, __("Material Consumption"))
		) {
			let consumption_btn = frm.add_custom_button(__("Material Consumption"), function () {
				valence.work_order.make_consumption_se(frm);
			});
			consumption_btn.addClass("btn-primary");
		}

		// Finish — ERPNext requires material_transferred_for_manufacturing > 0
		let produced = flt(doc.produced_qty);
		let can_finish = false;
		if (cint(doc.skip_transfer)) {
			can_finish = produced < flt(doc.qty);
		} else if (effective_mt > 0 && produced < effective_mt) {
			can_finish = true;
		} else if (frm.doc.__onload && flt(frm.doc.__onload.overproduction_percentage) > 0) {
			let allowance = flt(frm.doc.__onload.overproduction_percentage);
			let allowed_qty = flt(doc.qty) + (allowance / 100) * flt(doc.qty);
			can_finish = produced < allowed_qty && effective_mt > 0;
		}

		if (can_finish && !this.button_exists(frm, __("Finish"))) {
			let finish_btn = frm.add_custom_button(__("Finish"), function () {
				valence.work_order.make_finish_se(frm);
			});
			if (effective_mt >= flt(doc.qty) || cint(doc.skip_transfer)) {
				finish_btn.addClass("btn-primary");
			}
			frm.has_finish_btn = true;
		}
	},

	get_max_finish_qty: function (frm) {
		if (cint(frm.doc.skip_transfer)) {
			return flt(frm.doc.qty) - flt(frm.doc.produced_qty);
		}
		return (
			this.get_effective_material_transferred(frm) - flt(frm.doc.produced_qty)
		);
	},

	make_finish_se: function (frm) {
		let max = flt(this.get_max_finish_qty(frm), precision("qty"));
		frappe.prompt(
			[
				{
					fieldtype: "Float",
					label: __("Qty for {0}", [__("Manufacture")]),
					fieldname: "qty",
					description: __("Max: {0}", [max]),
					default: max,
					reqd: 1,
				},
			],
			(data) => {
				let allowance =
					(flt(frm.doc.qty) * (flt(frm.doc.__onload?.overproduction_percentage) || 0.0)) /
					100;
				if (flt(data.qty) > max + allowance) {
					frappe.msgprint(__("Quantity must not be more than {0}", [max + allowance]));
					return;
				}
				frappe
					.xcall("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", {
						work_order_id: frm.doc.name,
						purpose: "Manufacture",
						qty: data.qty,
					})
					.then((stock_entry) => {
						frappe.model.sync(stock_entry);
						frappe.set_route("Form", stock_entry.doctype, stock_entry.name);
					});
			},
			__("Select Quantity"),
			__("Create")
		);
	},

	make_consumption_se: function (frm) {
		let backflush = frm.doc.__onload?.backflush_raw_materials_based_on;
		let max = 0;
		if (!cint(frm.doc.skip_transfer)) {
			max =
				backflush === "Material Transferred for Manufacture"
					? this.get_effective_material_transferred(frm) - flt(frm.doc.produced_qty)
					: flt(frm.doc.qty) - flt(frm.doc.produced_qty);
		} else {
			max = flt(frm.doc.qty) - flt(frm.doc.produced_qty);
		}
		max = flt(max, precision("qty"));
		if (max <= 0) {
			max = flt(frm.doc.qty) - flt(frm.doc.produced_qty);
		}

		frappe.call({
			method: "erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
			args: {
				work_order_id: frm.doc.name,
				purpose: "Material Consumption for Manufacture",
				qty: max,
			},
			callback: function (r) {
				if (!r.message) {
					return;
				}
				let doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			},
		});
	},
};
