"""Shared constants and data models for textbook conversion scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

NUM_OPEN_SOURCE_COLS = 4

BOOK_STRUCTURE_COLUMNS = {
	"chapter": "Chapter (Substrand)",
	"section": "Section",
	"ptx_file": "PTX File",
}

TOC_COLUMNS = [
	"collection_title",
	"chapter_order",
	"chapter_title",
	"subcollection_path",
	"module_order",
	"module_id",
	"module_title",
	"row_type",
	"section_order",
	"section_level",
	"section_id",
	"section_title",
	"source_path",
]

SECTION_TAGS = {"section", "subsection", "subsubsection"}
EXERCISE_SECTION_TITLES = {"practice makes perfect", "section exercises", "homework"}
ALLOWED_XML_TAGS = {
	"book",
	"caption",
	"c",
	"cell",
	"convention",
	"em",
	"example",
	"exercise",
	"exercises",
	"figure",
	"image",
	"insight",
	"introduction",
	"latex-image",
	"li",
	"m",
	"md",
	"me",
	"objectives",
	"ol",
	"p",
	"paragraphs",
	"row",
	"section",
	"solution",
	"statement",
	"subsection",
	"subsubsection",
	"tabular",
	"table",
	"term",
	"title",
	"ul",
	"url",
	"xref",
}

INVALID_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")

CP1252_CONTROL_MAP = {
	0x80: "€",
	0x82: "‚",
	0x83: "ƒ",
	0x84: "„",
	0x85: "…",
	0x86: "†",
	0x87: "‡",
	0x88: "ˆ",
	0x89: "‰",
	0x8A: "Š",
	0x8B: "‹",
	0x8C: "Œ",
	0x8E: "Ž",
	0x91: "‘",
	0x92: "’",
	0x93: "“",
	0x94: "”",
	0x95: "•",
	0x96: "–",
	0x97: "—",
	0x98: "˜",
	0x99: "™",
	0x9A: "š",
	0x9B: "›",
	0x9C: "œ",
	0x9E: "ž",
	0x9F: "Ÿ",
}


@dataclass
class ReferenceMatch:
	"""A matched source reference row resolved from the TOC."""
	label: str
	resource: str
	title: str
	ref_id: str
	row_index: int
	toc_row: pd.Series


@dataclass
class TextbookInfo:
	"""Metadata for one source textbook/resource."""
	abbreviation: str
	textbook_name: str
	source_url: str
	license_name: str
	license_url: str
	is_pretext: bool = False


@dataclass
class AttributionEntry:
	"""Normalized attribution payload for inserted borrowed content."""
	resource: str
	title: str
	original_path: str
	original_url: str
	textbook_name: str
	license_name: str
	license_url: str


LICENSE_URL_MAP = {
	"CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/deed.en",
	"CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/deed.en",
	"CC-BY-NC-SA-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en",
	"GFDL-v1.3": "https://www.gnu.org/licenses/fdl-1.3.en.html",
	"GFDL-v1.2": "https://www.gnu.org/licenses/fdl-1.2.en.html",
}


def local_name(tag: str) -> str:
	"""Return XML local name from a namespaced tag."""
	return tag.split("}", 1)[-1]


def text_or_empty(value: object) -> str:
	"""Return stripped string value or empty string for null/NaN values."""
	if value is None or pd.isna(value):
		return ""
	return str(value).strip()


def is_truthy_text(value: object) -> bool:
	"""Interpret permissive truthy text values from CSV fields."""
	text = text_or_empty(value).casefold()
	return text.startswith("yes") or text in {"true", "1", "y"}


def resolve_input_path(workspace_root: Path, path_arg: Path) -> Path:
	"""Resolve a path argument relative to the workspace root."""
	return (workspace_root / path_arg).resolve() if not path_arg.is_absolute() else path_arg.resolve()


def dedupe_preserve_order(items: Iterable[AttributionEntry]) -> list[AttributionEntry]:
	"""Return unique attribution entries preserving first-seen order."""
	seen: set[tuple[str, str, str, str]] = set()
	out: list[AttributionEntry] = []
	for item in items:
		key = (item.resource, item.title, item.original_url, item.license_name)
		if key in seen:
			continue
		seen.add(key)
		out.append(item)
	return out
