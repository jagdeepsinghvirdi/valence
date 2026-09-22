import os

import frappe
from frappe.sessions import get_csrf_token
from frappe.website.page_renderers.base_renderer import BaseRenderer

VALENCE_SCRIPT_PATH = "/assets/valence/js/roster_left.js"


class RosterPageRenderer(BaseRenderer):
	def can_render(self):
		if not is_roster_path(self.path) and not is_roster_path(get_request_path()):
			return False

		return bool(read_hrms_roster_page())

	def render(self):
		return self.build_response(build_roster_html())


def is_roster_path(path):
	path = (path or "").strip("/ ")
	return path in ("hr", "roster") or path.startswith("hr/")


def get_request_path():
	request = getattr(frappe.local, "request", None)
	return getattr(request, "path", "") or ""


def build_roster_html():
	html = read_hrms_roster_page()
	if not html:
		return ""

	html = html.replace("{{ csrf_token }}", get_csrf_token())

	if VALENCE_SCRIPT_PATH in html:
		return html

	script = f'<script src="{VALENCE_SCRIPT_PATH}?v={get_script_version()}"></script>'

	if "</body>" in html:
		return html.replace("</body>", f"\t\t{script}\n\t</body>", 1)

	return html + script


def get_script_version():
	try:
		path = os.path.join(frappe.get_app_path("valence"), "public", "js", "roster_left.js")
		return int(os.path.getmtime(path))
	except Exception:
		return 0


def read_hrms_roster_page():
	try:
		path = os.path.join(frappe.get_app_path("hrms"), "www", "roster.html")
	except Exception:
		return ""

	if not os.path.exists(path):
		return ""

	with open(path, encoding="utf-8") as handle:
		return handle.read()
