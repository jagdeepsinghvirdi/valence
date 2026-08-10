import frappe


def set_abbr_for_item_group(self, method):
	if not self.meta.has_field("abbr"):
		return

	if not self.get("abbr"):
		words = (self.item_group_name or "").split()
		abbreviation = "".join([w[0].upper() for w in words if w])
		self.abbr = abbreviation
