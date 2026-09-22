import os
import re

import frappe
from markupsafe import Markup

ASSET_PATTERN = re.compile(
	r"<(?:script|link)\b[^>]*?/assets/hrms/roster/assets/[^>]*?>(?:</script>)?",
	re.IGNORECASE,
)


def get_context(context):
	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()  # nosemgrep

	context = frappe._dict()
	context.csrf_token = csrf_token
	context.roster_assets = get_roster_assets()
	return context


def get_roster_assets():
	source = read_hrms_roster_page()
	if not source:
		return Markup("")

	return Markup("\n\t\t".join(ASSET_PATTERN.findall(source)))


def read_hrms_roster_page():
	try:
		path = os.path.join(frappe.get_app_path("hrms"), "www", "roster.html")
	except Exception:
		return ""

	if not os.path.exists(path):
		return ""

	with open(path, encoding="utf-8") as handle:
		return handle.read()
