(() => {
  // ../valence/valence/public/js/transaction.js
  erpnext.TransactionController = class TransactionController extends erpnext.TransactionController {
    make_quality_inspection() {
      let data = [];
      const fields = [
        {
          label: "Items",
          fieldtype: "Table",
          fieldname: "items",
          cannot_add_rows: true,
          in_place_edit: true,
          data,
          get_data: () => {
            return data;
          },
          fields: [
            {
              fieldtype: "Data",
              fieldname: "docname",
              hidden: true
            },
            {
              fieldtype: "Read Only",
              fieldname: "item_code",
              label: __("Item Code"),
              in_list_view: true
            },
            {
              fieldtype: "Read Only",
              fieldname: "item_name",
              label: __("Item Name"),
              in_list_view: true
            },
            {
              fieldtype: "Float",
              fieldname: "qty",
              label: __("Accepted Quantity"),
              in_list_view: true,
              read_only: true
            },
            {
              fieldtype: "Float",
              fieldname: "sample_size",
              label: __("Sample Size"),
              reqd: true,
              in_list_view: true
            },
            {
              fieldtype: "Data",
              fieldname: "description",
              label: __("Description"),
              hidden: true
            },
            {
              fieldtype: "Data",
              fieldname: "serial_no",
              label: __("Serial No"),
              hidden: true
            },
            {
              fieldtype: "Data",
              fieldname: "batch_no",
              label: __("Batch No"),
              hidden: true
            },
            {
              fieldtype: "Data",
              fieldname: "ref_item",
              label: __("Ref Item"),
              hidden: true
            },
            {
              fieldname: "concentration",
              fieldtype: "Percent",
              label: __("Concentration"),
              hidden: true
            },
            {
              fieldname: "lot_no",
              fieldtype: "Data",
              label: __("Lot No"),
              hidden: true
            },
            {
              fieldname: "ar_no",
              fieldtype: "Data",
              label: __("AR No"),
              hidden: true
            }
          ]
        }
      ];
      const me = this;
      const dialog = new frappe.ui.Dialog({
        title: __("Select Items for Quality Inspection"),
        fields,
        primary_action: function() {
          const data2 = dialog.get_values();
          frappe.call({
            method: "erpnext.controllers.stock_controller.make_quality_inspections",
            args: {
              doctype: me.frm.doc.doctype,
              docname: me.frm.doc.name,
              items: data2.items
            },
            freeze: true,
            callback: function(r) {
              if (r.message.length > 0) {
                if (r.message.length === 1) {
                  frappe.set_route("Form", "Quality Inspection", r.message[0]);
                } else {
                  frappe.route_options = {
                    "reference_type": me.frm.doc.doctype,
                    "reference_name": me.frm.doc.name
                  };
                  frappe.set_route("List", "Quality Inspection");
                }
              }
              dialog.hide();
            }
          });
        },
        primary_action_label: __("Create")
      });
      this.frm.doc.items.forEach((item) => {
        if (this.has_inspection_required(item)) {
          let dialog_items = dialog.fields_dict.items;
          dialog_items.df.data.push({
            "docname": item.name,
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "description": item.description,
            "serial_no": item.serial_no,
            "batch_no": item.batch_no,
            "sample_size": item.sample_quantity,
            "ref_item": item.name,
            "concentration": item.concentration,
            "lot_no": item.lot_no,
            "ar_no": item.ar_no
          });
          dialog_items.grid.refresh();
        }
      });
      data = dialog.fields_dict.items.df.data;
      if (!data.length) {
        frappe.msgprint(__("All items in this document already have a linked Quality Inspection."));
      } else {
        dialog.show();
      }
    }
  };

  // ../valence/valence/public/js/workflow_approval.js
  (function() {
    const DOCTYPES = /* @__PURE__ */ new Set(["Leave Application", "Attendance Request"]);
    const APPROVAL_ACTIONS = /* @__PURE__ */ new Set(["Approve", "Reject"]);
    const States = frappe.ui.form.States;
    if (!States || States._valence_hierarchy_patched) {
      return;
    }
    const original_show_actions = States.prototype.show_actions;
    States.prototype.show_actions = function() {
      const frm = this.frm;
      if (!DOCTYPES.has(frm.doctype)) {
        return original_show_actions.call(this);
      }
      if (frm.doc.__unsaved === 1) {
        return;
      }
      let added = false;
      const me = this;
      function has_approval_access(transition) {
        const user = frappe.session.user;
        if (user === "Administrator" || transition.allow_self_approval || APPROVAL_ACTIONS.has(transition.action)) {
          return true;
        }
        return user !== frm.doc.owner;
      }
      frappe.workflow.get_transitions(frm.doc).then((transitions) => {
        frm.page.clear_actions_menu();
        transitions.forEach((transition) => {
          if (frappe.user_roles.includes(transition.allowed) && has_approval_access(transition)) {
            added = true;
            frm.page.add_action_item(__(transition.action), function() {
              frappe.dom.freeze();
              frm.selected_workflow_action = transition.action;
              if (!frappe.ui.form.check_mandatory(frm)) {
                return frappe.dom.unfreeze();
              }
              frm.script_manager.trigger("before_workflow_action").then(() => {
                frappe.xcall("frappe.model.workflow.apply_workflow", {
                  doc: frm.doc,
                  action: transition.action
                }).then((doc) => {
                  frappe.model.sync(doc);
                  me.frm.refresh();
                  frm.selected_workflow_action = null;
                  frm.script_manager.trigger("after_workflow_action");
                }).finally(() => {
                  frappe.dom.unfreeze();
                });
              });
            });
          }
        });
        me.setup_btn(added);
      });
    };
    States._valence_hierarchy_patched = true;
  })();
})();
//# sourceMappingURL=valence.bundle.YV3WDCXU.js.map
