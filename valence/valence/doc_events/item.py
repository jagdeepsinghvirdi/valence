import frappe

def validate(self,method):
	item_group = frappe.get_all("Item Group",fields=["item_group_name","abbr"])
	item_group_prefixes = {item["item_group_name"]: item["abbr"] for item in item_group if item["abbr"]}
	prefix = None
	if frappe.db.get_value("Item Group",self.item_group,"parent_item_group") != "All Item Groups":
		prefix = item_group_prefixes[frappe.db.get_value("Item Group",self.item_group,"parent_item_group")]
		self.abbr = prefix
	else:
		prefix = item_group_prefixes[self.item_group]
		self.abbr = prefix