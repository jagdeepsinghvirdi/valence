/**
 * Leave / OD-WFH: show Approve/Reject when the logged-in user is the document
 * creator (owner) but not the leave applicant — e.g. HOD applies for a report.
 *
 * Stock Frappe workflow.js hides Actions when session.user === doc.owner.
 * Server get_transitions already filters by approval_hierarchy.
 */
(function () {
	const DOCTYPES = new Set(["Leave Application", "Attendance Request"]);
	const APPROVAL_ACTIONS = new Set(["Approve", "Reject"]);

	const States = frappe.ui.form.States;
	if (!States || States._valence_hierarchy_patched) {
		return;
	}

	const original_show_actions = States.prototype.show_actions;

	States.prototype.show_actions = function () {
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
			if (
				user === "Administrator" ||
				transition.allow_self_approval ||
				APPROVAL_ACTIONS.has(transition.action)
			) {
				return true;
			}
			return user !== frm.doc.owner;
		}

		frappe.workflow.get_transitions(frm.doc).then((transitions) => {
			frm.page.clear_actions_menu();
			transitions.forEach((transition) => {
				if (frappe.user_roles.includes(transition.allowed) && has_approval_access(transition)) {
					added = true;
					frm.page.add_action_item(__(transition.action), function () {
						frappe.dom.freeze();
						frm.selected_workflow_action = transition.action;
						if (!frappe.ui.form.check_mandatory(frm)) {
							return frappe.dom.unfreeze();
						}
						frm.script_manager.trigger("before_workflow_action").then(() => {
							frappe
								.xcall("frappe.model.workflow.apply_workflow", {
									doc: frm.doc,
									action: transition.action,
								})
								.then((doc) => {
									frappe.model.sync(doc);
									me.frm.refresh();
									frm.selected_workflow_action = null;
									frm.script_manager.trigger("after_workflow_action");
								})
								.finally(() => {
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
