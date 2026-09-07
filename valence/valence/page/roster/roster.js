frappe.pages["roster"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Roster"),
		single_column: true,
	});

	window.location.replace("/hr/roster");
};
