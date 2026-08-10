"""
MariaDB 12+ compatibility helpers.

MariaDB 12 introduced TO_DATE() and treats bare `to_date` as that function, so
ERPNext/HRMS raw SQL that uses the common Frappe column name `to_date` without
backticks fails with syntax errors near `>=` / `from` / etc.

This patches frappe.db.sql once to quote bare `to_date` identifiers while leaving
placeholders (%(to_date)s), already-quoted identifiers, and string literals alone.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"%\([^)]*\)s")
_BACKTICKED_RE = re.compile(r"`[^`]*`")
_SINGLE_QUOTED_RE = re.compile(r"'(?:\\'|[^'])*'")
_DOUBLE_QUOTED_RE = re.compile(r'"(?:\\"|[^"])*"')
_BARE_TO_DATE_RE = re.compile(r"\bto_date\b")

_PATCH_ATTR = "_valence_mariadb_to_date_patched"


def quote_to_date_identifiers(query: str) -> str:
	"""Return SQL with bare `to_date` column refs rewritten as `` `to_date` ``."""
	if "to_date" not in query:
		return query

	protected: list[str] = []

	def _protect(match: re.Match[str]) -> str:
		protected.append(match.group(0))
		return f"\0V{len(protected) - 1}\0"

	out = _PLACEHOLDER_RE.sub(_protect, query)
	out = _BACKTICKED_RE.sub(_protect, out)
	out = _SINGLE_QUOTED_RE.sub(_protect, out)
	out = _DOUBLE_QUOTED_RE.sub(_protect, out)
	out = _BARE_TO_DATE_RE.sub("`to_date`", out)

	for i, original in enumerate(protected):
		out = out.replace(f"\0V{i}\0", original)
	return out


def apply_mariadb_compat_patches() -> None:
	"""Wrap Database.sql so bare to_date identifiers are safe on MariaDB 12+."""
	from frappe.database.database import Database

	if getattr(Database.sql, _PATCH_ATTR, False):
		return

	original_sql = Database.sql

	def sql(self: Any, query: Any, *args: Any, **kwargs: Any) -> Any:
		if isinstance(query, str):
			query = quote_to_date_identifiers(query)
		return original_sql(self, query, *args, **kwargs)

	setattr(sql, _PATCH_ATTR, True)
	Database.sql = sql  # type: ignore[method-assign]
