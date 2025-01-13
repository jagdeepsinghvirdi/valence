frappe.query_reports["Batch Tree"] = {
    "filters": [
        {
            "fieldname": "work_order",
            "label": __("Work Order"),
            "fieldtype": "Link",
            "options": "Work Order",
            // "reqd": 1,
            "get_query": function() {
                return {
                    filters: {
                        docstatus: 1 // Only submitted Work Orders
                    }
                };
            }
        },
        {
            "fieldname": "batch",
            "label": __("Control No"),
            "fieldtype": "Link",
            "options": "Batch",
            // "reqd": 1,
        }
    ],
    "tree": true,
    "parent_field": "parent_item_code",
    "name_field": "item_code",
    "initial_depth": 1,
    
    onload: function(report) {
        report.page.set_title(__('Batch Tree'));
    },
    
    formatter: function(value, row, column, data, default_formatter) {
        if (data && column.fieldname === "item_code") {
            // Don't add margin for root node
            if (!data.is_finished_item) {
                value = `${value || ""}`;
            }
        }
        
        value = default_formatter(value, row, column, data);
        
        if (data && data.is_finished_item) {
            if (column.fieldname === "item_code" || column.fieldname === "item_name") {
                value = $(`<span>${value || ""}</span>`);
                var $value = $(value).css({
                    'font-weight': 'bold',
                    'color': '#2490ef'
                });
                value = $value.wrap("<p></p>").parent().html();
            }
        }
        
        return value || "";
    }
};