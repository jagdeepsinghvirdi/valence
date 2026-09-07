from frappe.utils import flt

from valence.valence.attendance_code import LEAVE_CODES, LWP_CODE

MISPUNCH_CODE = "MP"
ABSENT_CODE = "A"

SUMMARY_FIELDS = (
	"ab",
	"wd",
	"wo",
	"nh",
	"pday",
	"ot",
	"dd",
	"rot",
	"paid_leaves",
	"present_days",
	"co",
	"lwp",
	"leave_absent",
)

COMP_OFF_CODE = "CO"

PAID_LEAVE_CODES = tuple(
	sorted({code for code in LEAVE_CODES.values() if code not in (LWP_CODE, COMP_OFF_CODE)})
)

FULL_CODES = {
	"P": {"wd": 1.0, "present_days": 1.0},
	"TT": {"wd": 1.0, "present_days": 1.0},
	ABSENT_CODE: {"ab": 1.0},
	"2P": {"wd": 1.0, "present_days": 1.0, "dd": 1.0, "ot": 1.0},
	"2P/A": {"wd": 1.0, "present_days": 1.0, "ot": 0.5},
	COMP_OFF_CODE: {"wd": 1.0, "co": 1.0, "ot": -1.0},
	LWP_CODE: {"lwp": 1.0},
	"WO": {"wo": 1.0},
	"PWO": {"wo": 1.0, "rot": 1.0, "ot": 1.0},
	"PAW": {"wo": 1.0, "ot": 0.5},
	"2PWO": {"wo": 1.0, "dd": 1.0, "ot": 2.0},
	"2PAW": {"wo": 1.0, "ot": 1.5},
	"H": {"nh": 1.0},
	"HP": {"nh": 1.0, "ot": 1.0},
	"HP/A": {"nh": 1.0, "ot": 0.5},
	"2HP": {"nh": 1.0, "ot": 2.0},
	"2HP/A": {"nh": 1.0, "ot": 1.5},
	MISPUNCH_CODE: {},
}

HALF_CODES = {
	"P": {"wd": 0.5, "present_days": 0.5},
	"TT": {"wd": 0.5, "present_days": 0.5},
	ABSENT_CODE: {"ab": 0.5},
	COMP_OFF_CODE: {"wd": 0.5, "co": 0.5, "ot": -0.5},
	LWP_CODE: {"lwp": 0.5},
	"H": {"nh": 1.0},
}

for _leave_code in PAID_LEAVE_CODES:
	FULL_CODES.setdefault(_leave_code, {"wd": 1.0, "paid_leaves": 1.0})
	HALF_CODES.setdefault(_leave_code, {"wd": 0.5, "paid_leaves": 0.5})


def split_code(code):
	if not code:
		return []

	code = str(code).strip()
	if not code:
		return []

	if code in FULL_CODES:
		return [(code, "full")]

	if "/" in code:
		return [(part.strip(), "half") for part in code.split("/", 1) if part.strip()]

	return [(code, "full")]


def empty_summary():
	return {field: 0.0 for field in SUMMARY_FIELDS}


def score_codes(codes):
	totals = empty_summary()

	for code in codes or []:
		for token, kind in split_code(code):
			table = FULL_CODES if kind == "full" else HALF_CODES
			for field, value in table.get(token, {}).items():
				totals[field] = flt(totals[field]) + value

	totals["pday"] = totals["wd"] + totals["wo"] + totals["nh"]
	totals["leave_absent"] = totals["ab"] + totals["paid_leaves"] + totals["lwp"]

	return {field: round(flt(totals[field]), 2) for field in SUMMARY_FIELDS}
