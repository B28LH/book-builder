"""Catalog and matching helpers for imported textbook content.

Responsibilities include:
- loading textbook metadata from `Open Textbooks.csv`
- normalizing CNXML and PreTeXt TOC exports into a shared schema
- matching Book Structure rows to source references
- generating attribution metadata for inserted content
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from slugify import slugify

from book_builder.populator.models import (
    NUM_OPEN_SOURCE_COLS,
    BOOK_STRUCTURE_COLUMNS,
    EXERCISE_SECTION_TITLES,
    LICENSE_URL_MAP,
    ReferenceMatch,
    TextbookInfo,
    AttributionEntry,
    is_truthy_text,
    text_or_empty,
)


def load_open_textbooks(open_textbooks_csv: Path) -> dict[str, TextbookInfo]:
    """Load textbook metadata keyed by uppercase resource abbreviation."""
    df = pd.read_csv(open_textbooks_csv)
    mapping: dict[str, TextbookInfo] = {}

    for _, row in df.iterrows():
        abbreviation = text_or_empty(row.get("Abbreviation")).upper()
        if not abbreviation:
            continue

        license_name = text_or_empty(row.get("License"))
        mapping[abbreviation] = TextbookInfo(
            abbreviation=abbreviation,
            textbook_name=text_or_empty(row.get("Textbook Name")),
            source_url=text_or_empty(row.get("Source URL")),
            license_name=license_name,
            license_url=LICENSE_URL_MAP.get(license_name, ""),
            is_pretext=is_truthy_text(row.get("Pretext?")),
        )

    return mapping


def build_original_url(source_path: str, source_url_base: str) -> str:
    """Build a browser URL for a source item from TOC path and source base URL."""
    source_path = text_or_empty(source_path)
    source_url_base = text_or_empty(source_url_base)
    if not source_path or not source_url_base:
        return ""

    path_parts = source_path.split("/", 1)
    suffix = path_parts[1] if len(path_parts) > 1 else ""
    base = source_url_base.rstrip("/")
    return f"{base}/{suffix}" if suffix else base


def build_chapter_folder_map(book_df: pd.DataFrame) -> dict[str, str]:
    """Map chapter titles from Book Structure to numbered output folders."""
    chapter_map: dict[str, str] = {}
    chapter_num = 1
    seen: set[str] = set()

    for chapter_title in book_df[BOOK_STRUCTURE_COLUMNS["chapter"]].fillna(""):
        chapter_title = text_or_empty(chapter_title)
        if not chapter_title or chapter_title in seen:
            continue
        seen.add(chapter_title)
        chapter_map[chapter_title] = f"{chapter_num:02d}-{slugify(chapter_title)}"
        chapter_num += 1

    return chapter_map


def enrich_toc_dataframe(toc_df: pd.DataFrame, textbooks: dict[str, TextbookInfo]) -> pd.DataFrame:
    """Normalize legacy CNXML TOC exports into the internal matching schema."""
    df = toc_df.copy()
    df["Open Source Resource"] = df["source_path"].fillna("").astype(str).str.split("/").str[0]
    section_id = df["section_id"].fillna("").astype(str).str.strip()
    module_id = df["module_id"].fillna("").astype(str).str.strip()
    df["ID"] = section_id.where(section_id != "", module_id)
    df["ID_resource"] = df["Open Source Resource"].astype(str) + "-" + df["ID"].astype(str)
    df["section_level"] = pd.to_numeric(df["section_level"], errors="coerce").fillna(0).astype(int)

    df["Textbook Name"] = df["Open Source Resource"].map(
        lambda value: textbooks.get(text_or_empty(value).upper(), TextbookInfo("", "", "", "", "")).textbook_name
    )
    df["Source URL"] = df["Open Source Resource"].map(
        lambda value: textbooks.get(text_or_empty(value).upper(), TextbookInfo("", "", "", "", "")).source_url
    )
    df["License"] = df["Open Source Resource"].map(
        lambda value: textbooks.get(text_or_empty(value).upper(), TextbookInfo("", "", "", "", "")).license_name
    )
    df["License URL"] = df["Open Source Resource"].map(
        lambda value: textbooks.get(text_or_empty(value).upper(), TextbookInfo("", "", "", "", "")).license_url
    )
    df["Original URL"] = df.apply(
        lambda row: build_original_url(text_or_empty(row.get("source_path")), text_or_empty(row.get("Source URL"))),
        axis=1,
    )

    def attribution_title(row: pd.Series) -> str:
        row_type = text_or_empty(row.get("row_type"))
        section_title = text_or_empty(row.get("section_title"))
        module_title = text_or_empty(row.get("module_title"))
        if row_type == "module":
            return module_title
        return section_title or module_title

    df["Attribution Title"] = df.apply(attribution_title, axis=1)
    return df


def normalize_pretext_toc_dataframe(
    toc_df: pd.DataFrame,
    resource_abbr: str,
    source_url: str,
    textbook_name: str,
    license_name: str,
    license_url: str,
    legacy_map_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normalize a PreTeXt TOC export into the shared matching schema."""
    df = toc_df.copy()
    required = {"node_id", "node_type", "source_path"}
    missing = required.difference(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"TOC CSV must contain {missing_list} columns")

    def chapter_id_from_row(row: pd.Series) -> str:
        for depth in range(1, 9):
            type_col = f"level_{depth}_type"
            id_col = f"level_{depth}_id"
            if type_col in row and id_col in row and text_or_empty(row.get(type_col)).lower() == "chapter":
                return text_or_empty(row.get(id_col))
        return ""

    def build_original_url(path: str) -> str:
        clean_path = text_or_empty(path)
        base = text_or_empty(source_url).rstrip("/")
        if not clean_path or not base:
            return ""
        return f"{base}/{clean_path}"

    clean_resource = text_or_empty(resource_abbr).upper()
    df["Open Source Resource"] = clean_resource
    df["ID"] = df["node_id"].fillna("").astype(str).str.strip()
    df["Legacy ID"] = ""
    if "original_id" in df.columns:
        df["Legacy ID"] = df["original_id"].fillna("").astype(str).str.strip()
    elif legacy_map_df is not None and {"original_id", "new_id"}.issubset(legacy_map_df.columns):
        compact = legacy_map_df[["original_id", "new_id"]].copy()
        compact["original_id"] = compact["original_id"].fillna("").astype(str).str.strip()
        compact["new_id"] = compact["new_id"].fillna("").astype(str).str.strip()
        compact = compact[compact["new_id"] != ""]
        compact = compact.drop_duplicates(subset=["new_id"], keep="first")
        legacy_lookup = dict(zip(compact["new_id"], compact["original_id"]))
        df["Legacy ID"] = df["ID"].map(lambda value: legacy_lookup.get(text_or_empty(value), ""))

    df["row_type"] = df["node_type"].fillna("").astype(str).str.strip().str.lower()
    df["section_title"] = df["node_title"].fillna("").astype(str)
    df["module_title"] = df["node_title"].fillna("").astype(str)
    df["module_id"] = df.apply(chapter_id_from_row, axis=1)
    df["ID_resource"] = df["Open Source Resource"].astype(str) + "-" + df["ID"].astype(str)
    df["ID_resource_legacy"] = df["Open Source Resource"].astype(str) + "-" + df["Legacy ID"].astype(str)
    df["Textbook Name"] = textbook_name
    df["Source URL"] = source_url
    df["License"] = license_name
    df["License URL"] = license_url
    df["Original URL"] = df["source_path"].map(build_original_url)
    df["Attribution Title"] = df["section_title"]
    return df


def reference_attribution(reference: ReferenceMatch, textbooks: dict[str, TextbookInfo]) -> AttributionEntry:
    """Build a normalized attribution record for one matched source reference."""
    resource = text_or_empty(reference.resource).upper()
    info = textbooks.get(resource)

    original_url = text_or_empty(reference.toc_row.get("Original URL"))
    if not original_url and info is not None:
        original_url = build_original_url(
            text_or_empty(reference.toc_row.get("source_path")),
            info.source_url,
        )

    title = text_or_empty(reference.toc_row.get("Attribution Title")) or reference.title or reference.ref_id
    textbook_name = info.textbook_name if info else resource
    license_name = info.license_name if info else ""
    license_url = info.license_url if info else ""

    return AttributionEntry(
        resource=resource,
        title=title,
        original_path=text_or_empty(reference.toc_row.get("source_path")),
        original_url=original_url,
        textbook_name=textbook_name,
        license_name=license_name,
        license_url=license_url,
    )


def resolve_target_file(
    book_row: pd.Series,
    reference_dir: Path,
    chapter_folder_map: dict[str, str],
) -> Path:
    """Resolve the destination section file path for a Book Structure row."""
    ptx_value = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["ptx_file"]))
    if ptx_value and ptx_value not in {"#REF!", "nan"}:
        candidate = Path(ptx_value)
        if not candidate.is_absolute():
            if candidate.parts and candidate.parts[0] in {"source-borrowed", "reference"}:
                candidate = reference_dir.parent / candidate
            else:
                candidate = reference_dir / candidate
        return candidate

    chapter_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["chapter"]))
    section_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["section"]))
    chapter_folder = chapter_folder_map[chapter_title]
    return reference_dir / chapter_folder / f"sec-{slugify(section_title)}.ptx"


def find_section_exercises(toc_df: pd.DataFrame, id_resource: str) -> pd.Series | None:
    """Return the exercises row immediately following a section/module row, if present."""
    start_row = toc_df[toc_df.ID_resource == id_resource]
    if start_row.empty:
        return None

    start_index = start_row.index[0]
    start_module_id = text_or_empty(start_row.iloc[0].get("module_id"))

    for idx in range(start_index + 1, len(toc_df)):
        sec_title = toc_df.at[idx, "section_title"]
        if isinstance(sec_title, str) and sec_title.lower() in EXERCISE_SECTION_TITLES:
            return toc_df.iloc[idx]
        if text_or_empty(toc_df.at[idx, "module_id"]) != start_module_id:
            return None
    return None


def collect_references(book_row: pd.Series, toc_df: pd.DataFrame) -> list[ReferenceMatch]:
    """Resolve up to four reference slots from Book Structure into TOC matches."""

    def first_non_empty(*column_names: str) -> str:
        for column_name in column_names:
            value = text_or_empty(book_row.get(column_name))
            if value:
                return value
        return ""

    id_resource_series_upper = toc_df["ID_resource"].fillna("").astype(str).str.upper()
    legacy_id_series_upper = (
        toc_df["ID_resource_legacy"].fillna("").astype(str).str.upper()
        if "ID_resource_legacy" in toc_df.columns
        else None
    )

    def lookup_match_index(resource: str, ref_id: str) -> int | None:
        match_key = f"{resource}-{ref_id}"
        exact = toc_df.index[toc_df["ID_resource"] == match_key].tolist()
        if exact:
            return exact[0]

        if "ID_resource_legacy" in toc_df.columns:
            exact_legacy = toc_df.index[toc_df["ID_resource_legacy"] == match_key].tolist()
            if exact_legacy:
                return exact_legacy[0]

        upper_key = match_key.upper()
        ci = toc_df.index[id_resource_series_upper == upper_key].tolist()
        if ci:
            return ci[0]

        if legacy_id_series_upper is not None:
            ci_legacy = toc_df.index[legacy_id_series_upper == upper_key].tolist()
            if ci_legacy:
                return ci_legacy[0]

        return None

    refs: list[ReferenceMatch] = []
    for i in range(1, NUM_OPEN_SOURCE_COLS + 1): # iteratre throw all the referneces
        
        resource = book_row[f"Open Source Resource {i}"]
        ref_id = book_row[f"Open Source ID {i}"]
        title = book_row[f"Open Source Title {i}"]
        
        if resource == "" or ref_id == "" or title=="":
            continue

        row_index = lookup_match_index(resource, ref_id)
        if row_index is None and title:
            row_index = lookup_match_index(resource, title)
            if row_index is not None:
                ref_id = title

        if row_index is None:
            continue

        match_key = f"{resource}-{ref_id}"
        main_ref = ReferenceMatch(
            label=f"ref_{i}",
            resource=resource,
            title=title or ref_id,
            ref_id=ref_id,
            row_index=row_index,
            toc_row=toc_df.iloc[row_index],
        )
        refs.append(main_ref)

        if main_ref.toc_row.row_type != "module":
            ex_row = find_section_exercises(toc_df, match_key)
            if ex_row is not None:
                exercise_ref_id = text_or_empty(ex_row.get("ID")) or ref_id
                refs.append(
                    ReferenceMatch(
                        label="exercise",
                        resource=resource,
                        title=text_or_empty(ex_row.get("section_title")) or "Exercises",
                        ref_id=exercise_ref_id,
                        row_index=ex_row.index[0],
                        toc_row=ex_row,
                    )
                )

    return refs
