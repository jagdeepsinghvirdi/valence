import frappe


def validate(self, method):
	if self.meta.has_field("abbr") and frappe.get_meta("Item Group").has_field("abbr"):
		item_groups = frappe.get_all("Item Group", fields=["item_group_name", "abbr"])
		item_group_prefixes = {
			item["item_group_name"]: item["abbr"]
			for item in item_groups
			if item.get("abbr")
		}
		parent_item_group = frappe.db.get_value(
			"Item Group", self.item_group, "parent_item_group"
		)
		if parent_item_group and parent_item_group != "All Item Groups":
			prefix = item_group_prefixes.get(parent_item_group)
		else:
			prefix = item_group_prefixes.get(self.item_group)

		if prefix:
			self.abbr = prefix

	if self.get("custom_is_final_stage"):
		if (self.get("custom_item_stage") or 0) <= 0:
			frappe.throw("Item Stage cannot be 0 or less than 0")
