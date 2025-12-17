app_name = "valence"
app_title = "Valence"
app_publisher = "finbyz tech"
app_description = "Valence lab"
app_email = "info@finbyz.tech"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "valence",
# 		"logo": "/assets/valence/logo.png",
# 		"title": "Valence",
# 		"route": "/valence",
# 		"has_permission": "valence.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/valence/css/valence.css"
app_include_js = [
	"valence.bundle.js"
]
# include js, css files in header of web template
# web_include_css = "/assets/valence/css/valence.css"
# web_include_js = "/assets/valence/js/valence.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "valence/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"Work Order" : "public/js/work_order.js",
			"Production Plan":"public/js/production_plan.js",
			"Sales Invoice":"public/js/sales_invoice.js",
			"Delivery Note":"public/js/delivery_note.js",
			"Stock Entry":"public/js/stock_entry.js",
            "Attendance":"public/js/attendance.js",
            "Batch":"public/js/batch.js",
            "Quality Inspection":"public/js/quality_inspection.js",
			
}
doctype_list_js = {"Batch":"public/js/batch_list.js",
                   "Attendance":"public/js/attendance_list.js",}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}
doctype_calendar_js = {"Shift Assignment" : "public/js/shift_assignment_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "valence/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
	"methods": ["valence.valence.jinja.get_batch_and_lot_number_from_serial_and_batch_bundle"],
	# "filters": "valence.utils.jinja_filters"
}

# Installation
# ------------

# before_install = "valence.install.before_install"
# after_install = "valence.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "valence.uninstall.before_uninstall"
# after_uninstall = "valence.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "valence.utils.before_app_install"
# after_app_install = "valence.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "valence.utils.before_app_uninstall"
# after_app_uninstall = "valence.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "valence.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Job Card": "valence.valence.override.job_card.JobCard",
	"Production Plan":"valence.valence.override.production_plan.ProductionPlan",
	"Work Order":"valence.valence.override.work_order.WorkOrder",
	"Stock Entry":"valence.valence.override.stock_entry.StockEntry",
	"Batch":"valence.valence.override.batch.Batch",
	"Sales Invoice":"valence.valence.override.sales_invoice.SalesInvoice",
	"Sales Order":"valence.valence.override.sales_order.SalesOrder",
	"Delivery Note":"valence.valence.override.delivery_note.DeliveryNote",
	# "Quality Inspection":"valence.valence.override.quality_inspection.QualityInspection",
    "Attendance":"valence.valence.override.attendance.Attendance",
    "Shift Type":"valence.valence.override.shift_type.ShiftType"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Quality Inspection": {
		"on_submit":[ "valence.valence.doc_events.quality_inspection.on_submit","valence.valence.doc_events.quality_inspection.transfer_material_from_quality_inspection_warehouse"],
		"before_save": "valence.valence.doc_events.quality_inspection.before_save",
		"before_submit":"valence.valence.doc_events.quality_inspection.before_submit",
	},
    "Stock Entry":{
        "on_submit":["valence.valence.doc_events.stock_entry.on_submit","valence.valence.doc_events.stock_entry.validate_manufacture_entry"],
		# "before_submit":"valence.valence.doc_events.stock_entry.stock_entry_quality_inspection_validation",
		"on_cancel":"valence.valence.doc_events.stock_entry.on_cancel_manufacture_entry",
		"validate":"valence.valence.doc_events.stock_entry.validate"

    },
    "Work Order": {
		"on_submit": "valence.valence.doc_events.work_order.on_submit",
		"on_update_after_submit":"valence.valence.doc_events.work_order.on_update_after_submit",
		"validate":"valence.valence.doc_events.work_order.set_batch_serial_check_box",
		"after_submit":"valence.valence.doc_events.work_order.after_submit"
	},
	"Job Card": {
		"on_submit": "valence.valence.doc_events.job_card.on_submit",
		"before_submit":"valence.valence.doc_events.job_card.before_submit",
		"after_submit":"valence.valence.doc_events.job_card.after_submit",
	},
	"Item":{
		"validate":"valence.valence.doc_events.item.validate",
	},
	"Item Group":{
		"validate":"valence.valence.doc_events.item_group.set_abbr_for_item_group"
	},
	"Purchase Receipt":{
		"before_submit":"valence.valence.doc_events.purchase_receipt.before_submit"
	},
	("Material Request","Purchase Order","Stock Entry","Quality Inspection","Test Requisition Form") :{
      "before_insert": "valence.valence.doc_events.workflow_state_change.before_insert",
      "before_validate": "valence.valence.doc_events.workflow_state_change.before_validate",
  },
  "Attendance":{
      "validate":"valence.valence.doc_events.attendance.set_status",
      "after_insert":"valence.valence.doc_events.attendance.set_short_leave_count",
      "on_update_after_submit": "valence.valence.doc_events.attendance.set_short_leave_count"
    #   "on_cancel": "valence.valence.doc_events.attendance.cleanup_related_docs",
    #   "on_trash": "valence.valence.doc_events.attendance.cleanup_related_docs"      
  }

}

from erpnext.stock.serial_batch_bundle import SerialBatchCreation
from valence.valence.monkey_patch.serial_batch_bundle import create_batch
SerialBatchCreation.create_batch = create_batch
# Scheduled Tasks
# --------------

scheduler_events = {
	"all":[
		"valence.valence.doc_events.batch.real_time_status_update"
	],
    "cron": {
        "0 0 * * *": [
            "valence.valence.doc_events.quality_inspection.create_qc_for_retest_batches",
            "valence.valence.doc_events.attendance.process_attendance_offdays"
        ],
        "0 4 * * THU": [
			"valence.api.sales_invoice_payment_remainder",
		]
    }
}

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "in", ["Valence"]]]},
    {"dt": "Property Setter", "filters": [["module", "in", ["Valence"]]]}
]
# Testing
# -------

# before_tests = "valence.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"erpnext.controllers.stock_controller.make_quality_inspections": "valence.valence.override.whitelisted_method.stock_controller.make_quality_inspections",
	"chemical.query.get_batch_no":"valence.valence.override.whitelisted_method.query.get_batch_no"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "valence.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["valence.utils.before_request"]
# after_request = ["valence.utils.after_request"]

# Job Events
# ----------
# before_job = ["valence.utils.before_job"]
# after_job = ["valence.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"valence.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

