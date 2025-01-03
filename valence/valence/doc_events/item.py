import frappe

def validate(self,method):
	item_group_prefixes = {
		'Consumable': 'CU',
		'Engineering': 'EG',
		'EHS': 'EH',
		'Electrical': 'EL',
		'Finished Goods': 'FG',
		'IT & INFRA': 'IT',
		'Key Starting Material (KSM)': 'KM',
		'Lab Chemicals': 'LC104',  # Modified prefix for Lab Chemicals
		'Lab Equipments': 'LE',
		'Intermediates': 'IM',
		'Packing Materials': 'PM',
		'Raw Material': 'RM',
		'Solvent': 'SL100',  # Modified prefix for Solvent
		'Mixture Solvent': 'MS',
		'Recover Solvent': 'RS',
		'Printing & Stationery': 'ST',
		'WIP BUILDING': 'WP'
	}
	prefix = None
	if frappe.db.get_value("Item Group",self.item_group,"parent_item_group") != "All Item Groups":
		prefix = item_group_prefixes[frappe.db.get_value("Item Group",self.item_group,"parent_item_group")]
		self.abbr = prefix
	else:
		prefix = item_group_prefixes[self.item_group]
		self.abbr = prefix