"""File I/O and structural cleanup utilities for imported reference content.

This module owns all in-place edits to generated PreTeXt files, including
content injection, attribution updates, xref normalization, and exercise/
webwork cleanup passes.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

from slugify import slugify

from book_builder.populator.models import AttributionEntry, dedupe_preserve_order, text_or_empty


def inject_content_into_target(target_file: Path, fragment_blocks: list[str], append: bool = False) -> None:
    """Insert borrowed content into a target section or exercise file."""
    content = target_file.read_text(encoding="utf-8")
    cleaned_blocks = [
        re.sub(r"(?m)^\s*</?attribution\b[^>]*>\s*$", "", block).strip()
        for block in fragment_blocks
    ]
    cleaned_blocks = [block for block in cleaned_blocks if block]
    indented_body = "\n\n".join(cleaned_blocks).replace("\n", "\n  ")
    wrapped_body = (
        "<!-- BEGIN BORROWED CONTENT -->\n\n"
        f"{indented_body}\n\n"
        "  <!-- END BORROWED CONTENT -->"
    )
    placeholder_pattern = re.compile(r"\n\s*<!-- TODO: add section content\. -->\s*\n", re.MULTILINE)
    marked_block_pattern = re.compile(
        r"\n\s*<!-- BEGIN BORROWED CONTENT -->.*?<!-- END BORROWED CONTENT -->\s*\n",
        re.MULTILINE | re.DOTALL,
    )
    legacy_borrowed_pattern = re.compile(
        r"\n\s*<!-- Borrowed from .*?(?=\n</section>\s*$)",
        re.MULTILINE | re.DOTALL,
    )

    if append and marked_block_pattern.search(content):
        existing_match = marked_block_pattern.search(content)
        assert existing_match is not None
        existing_block = existing_match.group(0)
        existing_inner = re.sub(r"^\s*<!-- BEGIN BORROWED CONTENT -->\s*", "", existing_block.strip())
        existing_inner = re.sub(r"\s*<!-- END BORROWED CONTENT -->\s*$", "", existing_inner)
        existing_inner = existing_inner.strip()

        if existing_inner:
            merged_inner = f"{existing_inner}\n\n{indented_body}" if indented_body else existing_inner
        else:
            merged_inner = indented_body

        merged_body = (
            "<!-- BEGIN BORROWED CONTENT -->\n\n"
            f"{merged_inner}\n\n"
            "  <!-- END BORROWED CONTENT -->"
        )
        updated = marked_block_pattern.sub(lambda _match: f"\n\n  {merged_body}\n", content, count=1)
    elif marked_block_pattern.search(content):
        updated = marked_block_pattern.sub(lambda _match: f"\n\n  {wrapped_body}\n", content, count=1)
    elif placeholder_pattern.search(content):
        updated = placeholder_pattern.sub(lambda _match: f"\n\n  {wrapped_body}\n", content, count=1)
    elif legacy_borrowed_pattern.search(content):
        updated = legacy_borrowed_pattern.sub(lambda _match: f"\n\n  {wrapped_body}\n", content, count=1)
    else:
        closing_pattern = re.compile(r"\n</section>\s*$")
        updated = closing_pattern.sub(lambda _match: f"\n\n  {wrapped_body}\n</section>\n", content, count=1)
    target_file.write_text(updated, encoding="utf-8")


def read_section_id(target_file: Path) -> str:
    """Read and return the top-level section `xml:id` from a PTX file."""
    text = target_file.read_text(encoding="utf-8")
    match = re.search(r'<section\s+xml:id="([^"]+)"', text)
    if not match:
        raise ValueError(f"Could not find section xml:id in {target_file}")
    return match.group(1)


def write_borrowed_section_file(
    target_file: Path,
    section_id: str,
    title: str,
    fragment_blocks: list[str],
    attributions: list[AttributionEntry],
    wrap_in_exercises: bool = False,
) -> None:
    """Write a standalone borrowed-content section file to disk."""
    rendered_blocks = fragment_blocks
    if wrap_in_exercises and fragment_blocks:
        rendered_blocks = ["<exercises>"] + [f"  {block}" for block in fragment_blocks] + ["</exercises>"]

    borrowed_body = "\n\n".join(rendered_blocks).replace("\n", "\n  ") if rendered_blocks else ""
    primary = attributions[0] if attributions else None
    section_attrs = [f'xml:id="{html.escape(section_id)}"']
    if primary and primary.original_path:
        section_attrs.append(f'original="{html.escape(primary.original_path)}"')
    if primary and primary.license_name:
        section_attrs.append(f'license="{html.escape(primary.license_name)}"')
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "",
        f"<section {' '.join(section_attrs)}>",
        f"  <title>{html.escape(title)}</title>",
        "",
        "  <!-- BEGIN BORROWED CONTENT -->",
    ]
    if borrowed_body:
        lines.extend(["", f"  {borrowed_body}"])
    lines.extend(["", "  <!-- END BORROWED CONTENT -->"])

    if attributions:
        lines.extend(["", build_convention_block(section_id, attributions)])

    lines.extend(["</section>", ""])
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("\n".join(lines), encoding="utf-8")


def find_chapter_file_for_section(section_file: Path) -> Path | None:
    """Return the chapter file (`ch-*.ptx`) adjacent to a section file, if any."""
    chapter_candidates = sorted(section_file.parent.glob("ch-*.ptx"))
    return chapter_candidates[0] if chapter_candidates else None


def find_exercise_file_for_section(section_file: Path) -> Path | None:
    """Return the chapter exercise file (`ex-*.ptx`) adjacent to a section file, if any."""
    candidates = sorted(section_file.parent.glob("ex-*.ptx"))
    return candidates[0] if candidates else None


def ensure_chapter_includes_file(chapter_file: Path, include_href: str) -> None:
    """Ensure a chapter has an `<xi:include>` for a generated section/exercise file."""
    content = chapter_file.read_text(encoding="utf-8")
    include_line = f'  <xi:include href="{include_href}" />'
    if include_line in content:
        return

    closing = re.search(r"\n\s*</chapter>\s*$", content)
    if closing:
        updated = content[: closing.start()] + f"\n{include_line}\n" + content[closing.start() :]
    else:
        updated = content.rstrip() + f"\n{include_line}\n"

    chapter_file.write_text(updated, encoding="utf-8")


def build_convention_block(section_id: str, attributions: list[AttributionEntry]) -> str:
    """Build the attribution convention block appended to adapted sections."""
    lines = ["  <!-- BEGIN ATTRIBUTION CONVENTION -->", "  <convention>"]
    for index, item in enumerate(dedupe_preserve_order(attributions)):
        title_text = html.escape(item.title)
        book_text = html.escape(item.textbook_name or item.resource)
        license_text = html.escape(item.license_name or "license")
        if item.original_url:
            source_text = f'"<url href="{html.escape(item.original_url)}">{title_text}</url>"'
        else:
            source_text = f'"{title_text}"'
        if item.license_url:
            license_part = f'<url href="{html.escape(item.license_url)}">{license_text}</url>'
        else:
            license_part = license_text

        if index == 0:
            prefix = f'This section <xref ref="{html.escape(section_id)}" text="title"/> is adapted from '
        else:
            prefix = "This section also includes material adapted from "

        lines.append(f"    <p>{prefix}{source_text} in {book_text}, used under {license_part}.</p>")

    lines.extend(["  </convention>", "  <!-- END ATTRIBUTION CONVENTION -->"])
    return "\n".join(lines)


def build_source_convention_block(section_id: str, attributions: list[AttributionEntry]) -> str:
    """Build a convention block for one contiguous source run."""
    entries = dedupe_preserve_order(attributions)
    if not entries:
        return ""

    resource = text_or_empty(entries[0].resource).upper()
    if resource == "ORCCA":
        first = entries[0]
        title_text = html.escape(first.title)
        source_url = html.escape(first.original_url or "https://spot.pcc.edu/math/orcca/ed2/html/orcca.html")
        lines = [
            "<convention>",
            (
                f'  <p> This section <xref ref="{html.escape(section_id)}" text="title"/> '
                f'is adapted from <url href="{source_url}"> {title_text} </url> in '
                '<url href="https://spot.pcc.edu/math/orcca/ed2/html/orcca.html"> '
                'Open Resources for Community College Algebra </url> by Portland Community College Faculty, '
                'used under <url href="https://creativecommons.org/licenses/by/4.0/"> CC BY 4.0</url>. '
                'Original source material, products with readable and accessible math content, '
                'and other information freely available at <url href="https://pcc.edu/orcca"/>. </p>'
            ),
            "</convention>",
        ]
        return "\n".join(lines)

    # Fallback: keep the existing generic convention wording.
    return build_convention_block(section_id, entries).replace("  <!-- BEGIN ATTRIBUTION CONVENTION -->\n", "").replace("\n  <!-- END ATTRIBUTION CONVENTION -->", "")


def update_section_attributes_and_convention(
    target_file: Path,
    section_id: str,
    attributions: list[AttributionEntry],
    include_convention: bool = True,
) -> None:
    """Update section metadata attributes and replace/insert attribution convention."""
    if not attributions:
        return

    content = target_file.read_text(encoding="utf-8")
    primary = attributions[0]

    section_match = re.search(r"<section\b([^>]*)>", content)
    if section_match:
        attrs = section_match.group(1)
        attrs = re.sub(r'\s+original="[^"]*"', "", attrs)
        attrs = re.sub(r'\s+license="[^"]*"', "", attrs)
        attrs = re.sub(r"\s+", " ", attrs).rstrip()
        opening = f"<section{attrs}"
        if primary.original_path:
            opening += f' original="{html.escape(primary.original_path)}"'
        if primary.license_name:
            opening += f' license="{html.escape(primary.license_name)}"'
        opening += ">"
        content = content[: section_match.start()] + opening + content[section_match.end() :]

    content = re.sub(r"(?m)^\s*<attribution\b[^>]*>\s*\n?", "", content)
    content = re.sub(r"(?m)^\s*</attribution>\s*\n?", "", content)

    convention_pattern = re.compile(
        r"\n\s*<!-- BEGIN ATTRIBUTION CONVENTION -->.*?<!-- END ATTRIBUTION CONVENTION -->\s*\n",
        re.DOTALL,
    )
    if include_convention:
        convention_block = build_convention_block(section_id, attributions)
        if convention_pattern.search(content):
            content = convention_pattern.sub(f"\n\n{convention_block}\n\n", content, count=1)
        else:
            content = re.sub(r"\n</section>\s*$", f"\n\n{convention_block}\n</section>\n", content, count=1)
    else:
        content = convention_pattern.sub("\n", content)

    target_file.write_text(content, encoding="utf-8")


def normalize_latex_images_in_target_file(target_file: Path) -> bool:
    """Normalize latex-image arrow tokens in a PTX file."""
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(r"(<latex-image\b[^>]*>)(.*?)(</latex-image>)", re.DOTALL)

    changed = False

    def replacer(match: re.Match[str]) -> str:
        nonlocal changed
        opening, body, closing = match.groups()
        normalized = body.replace("&lt;", "<").replace("&gt;", ">")
        normalized = normalized.replace("<->", "{Kite}-{Kite}")
        normalized = normalized.replace("<-", "{Kite}-")
        normalized = normalized.replace("->", "-{Kite}")
        if normalized != body:
            changed = True
        return f"{opening}{normalized}{closing}"

    updated = pattern.sub(replacer, content)
    if changed:
        target_file.write_text(updated, encoding="utf-8")
    return changed


def collect_project_xml_ids(reference_dir: Path, source_dir: Path | None = None) -> set[str]:
    ids: set[str] = set()
    id_pattern = re.compile(r'\bxml:id="([^"]+)"')

    def _scan_file(path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        ids.update(id_pattern.findall(text))

    if reference_dir.exists():
        for ptx in reference_dir.rglob("*.ptx"):
            _scan_file(ptx)

    if source_dir and source_dir.exists():
        for ptx in source_dir.glob("*.ptx"):
            _scan_file(ptx)

    return ids


def deduplicate_xml_ids_in_tree(root_dir: Path) -> int:
    """Ensure `xml:id` values are unique across all PTX files under `root_dir`.

    For repeated IDs, the first occurrence is kept unchanged and later
    occurrences become `<id>-v2`, `<id>-v3`, ... .

    Local xref attributes (`ref`, `first`, `last`, `provisional`) in the same
    file are rewritten when they target one of the renamed IDs.
    """

    file_paths = sorted(root_dir.rglob("*.ptx"))
    id_attr_pattern = re.compile(r'\bxml:id="([^"]+)"')

    occurrences: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    per_file_ids: dict[Path, list[str]] = {}
    for path in file_paths:
        text = path.read_text(encoding="utf-8")
        ids = [match.group(1) for match in id_attr_pattern.finditer(text)]
        per_file_ids[path] = ids
        for idx, xml_id in enumerate(ids):
            occurrences[xml_id].append((path, idx))

    used_ids = set(occurrences.keys())
    per_file_renames_by_index: dict[Path, dict[int, str]] = defaultdict(dict)
    per_file_renames: dict[Path, dict[str, str]] = defaultdict(dict)

    for xml_id, refs in sorted(occurrences.items()):
        if len(refs) <= 1:
            continue

        version = 2
        # Keep first occurrence unchanged; rename all later occurrences.
        for path, local_idx in refs[1:]:
            candidate = f"{xml_id}-v{version}"
            while candidate in used_ids:
                version += 1
                candidate = f"{xml_id}-v{version}"
            used_ids.add(candidate)
            per_file_renames_by_index[path][local_idx] = candidate
            per_file_renames[path][xml_id] = candidate
            version += 1

    if not per_file_renames_by_index:
        return 0

    xref_open_tag_pattern = re.compile(r"<xref\b([^<>]*?)(/?)>")

    def _replace_attr_tokens(attrs: str, attr_name: str, rename_map: dict[str, str]) -> str:
        attr_pattern = re.compile(rf'\b{attr_name}="([^"]*)"')
        match = attr_pattern.search(attrs)
        if not match:
            return attrs

        raw = match.group(1)
        tokens = [token for token in re.split(r"([\s,]+)", raw)]
        changed = False
        for i, token in enumerate(tokens):
            stripped = token.strip()
            if not stripped or stripped in {",", " ", "\t", "\n"}:
                continue
            new_token = rename_map.get(stripped)
            if new_token and new_token != stripped:
                if token == stripped:
                    tokens[i] = new_token
                else:
                    tokens[i] = token.replace(stripped, new_token)
                changed = True

        if not changed:
            return attrs

        updated = "".join(tokens)
        return attrs[: match.start(1)] + updated + attrs[match.end(1) :]

    changed_files = 0
    for path in file_paths:
        index_map = per_file_renames_by_index.get(path)
        if not index_map:
            continue

        rename_map = per_file_renames[path]
        text = path.read_text(encoding="utf-8")

        # Rewrite xml:id occurrences by per-file occurrence index.
        counter = {"idx": -1}

        def _rewrite_xml_id(match: re.Match[str]) -> str:
            counter["idx"] += 1
            idx = counter["idx"]
            new_id = index_map.get(idx)
            if not new_id:
                return match.group(0)
            return f'xml:id="{new_id}"'

        updated = id_attr_pattern.sub(_rewrite_xml_id, text)

        # Rewrite local xref targets for renamed IDs in this same file.
        def _rewrite_xref(match: re.Match[str]) -> str:
            attrs = match.group(1)
            slash = match.group(2)
            closing = " />" if slash == "/" else ">"

            new_attrs = attrs
            for attr_name in ("ref", "first", "last", "provisional"):
                new_attrs = _replace_attr_tokens(new_attrs, attr_name, rename_map)

            new_attrs = re.sub(r"\s+", " ", new_attrs).strip()
            if new_attrs:
                return f"<xref {new_attrs}{closing}"
            return f"<xref{closing}"

        updated = xref_open_tag_pattern.sub(_rewrite_xref, updated)

        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1

    return changed_files


def provisionalize_unresolved_xrefs_in_target_file(target_file: Path, known_ids: set[str]) -> int:
    content = target_file.read_text(encoding="utf-8")
    xref_open_tag_pattern = re.compile(r"<xref\b([^<>]*?)(/?)>")
    replacements = 0
    alias_cache: dict[str, str | None] = {}

    def _split_ref_candidates(raw: str) -> list[str]:
        value = text_or_empty(raw)
        if not value:
            return []
        return [token.strip() for token in re.split(r"[\s,]+", value) if token.strip()]

    def _resolve_converted_id_alias(raw_ref: str) -> str | None:
        cached = alias_cache.get(raw_ref)
        if raw_ref in alias_cache:
            return cached

        ref = text_or_empty(raw_ref)
        if not ref:
            alias_cache[raw_ref] = None
            return None

        if ref in known_ids:
            alias_cache[raw_ref] = ref
            return ref

        slug_ref = slugify(ref)
        if not slug_ref:
            alias_cache[raw_ref] = None
            return None

        candidates = [candidate for candidate in known_ids if candidate == slug_ref or candidate.endswith(f"-{slug_ref}")]
        if len(candidates) == 1:
            alias_cache[raw_ref] = candidates[0]
            return candidates[0]

        alias_cache[raw_ref] = None
        return None

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacements
        attrs = match.group(1)
        self_closing = match.group(2) == "/"
        closing = " />" if self_closing else ">"

        provisional_match = re.search(r'\bprovisional="([^"]*)"', attrs)
        if provisional_match:
            raw_provisional_values = _split_ref_candidates(provisional_match.group(1))
            resolved_values: list[str] = []
            unresolved_values: list[str] = []
            for value in raw_provisional_values:
                resolved = _resolve_converted_id_alias(value)
                if resolved is None:
                    unresolved_values.append(value)
                else:
                    resolved_values.append(resolved)

            if not raw_provisional_values or unresolved_values:
                return match.group(0)

            new_attrs = re.sub(r'\s*\bprovisional="[^"]*"', "", attrs)
            new_attrs = re.sub(r'\s*\bref="[^"]*"', "", new_attrs)
            new_attrs = re.sub(r'\s*\bfirst="[^"]*"', "", new_attrs)
            new_attrs = re.sub(r'\s*\blast="[^"]*"', "", new_attrs)

            if len(resolved_values) == 1:
                target_attrs = f'ref="{html.escape(resolved_values[0], quote=True)}"'
            elif len(resolved_values) == 2:
                target_attrs = (
                    f'first="{html.escape(resolved_values[0], quote=True)}" '
                    f'last="{html.escape(resolved_values[1], quote=True)}"'
                )
            else:
                target_attrs = f'ref="{html.escape(" ".join(resolved_values), quote=True)}"'

            new_attrs = re.sub(r"\s+", " ", new_attrs).strip()
            replacements += 1
            if new_attrs:
                return f"<xref {new_attrs} {target_attrs}{closing}"
            return f"<xref {target_attrs}{closing}"

        unresolved_values: list[str] = []
        remapped_attrs = attrs
        remapped_any = False

        ref_match = re.search(r'\bref="([^"]+)"', attrs)
        if ref_match:
            raw_ref_values = _split_ref_candidates(ref_match.group(1))
            resolved_ref_values: list[str] = []
            for value in raw_ref_values:
                resolved = _resolve_converted_id_alias(value)
                if resolved is None:
                    unresolved_values.append(value)
                else:
                    resolved_ref_values.append(resolved)
                    if resolved != value:
                        remapped_any = True

            if raw_ref_values and not unresolved_values:
                remapped_ref = " ".join(resolved_ref_values)
                remapped_attrs = re.sub(r'\bref="[^"]+"', f'ref="{html.escape(remapped_ref, quote=True)}"', remapped_attrs)

        first_match = re.search(r'\bfirst="([^"]+)"', attrs)
        if first_match:
            raw_first_values = _split_ref_candidates(first_match.group(1))
            resolved_first_values: list[str] = []
            unresolved_first: list[str] = []
            for value in raw_first_values:
                resolved = _resolve_converted_id_alias(value)
                if resolved is None:
                    unresolved_first.append(value)
                else:
                    resolved_first_values.append(resolved)
                    if resolved != value:
                        remapped_any = True
            unresolved_values.extend(unresolved_first)
            if raw_first_values and not unresolved_first:
                remapped_first = " ".join(resolved_first_values)
                remapped_attrs = re.sub(r'\bfirst="[^"]+"', f'first="{html.escape(remapped_first, quote=True)}"', remapped_attrs)

        last_match = re.search(r'\blast="([^"]+)"', attrs)
        if last_match:
            raw_last_values = _split_ref_candidates(last_match.group(1))
            resolved_last_values: list[str] = []
            unresolved_last: list[str] = []
            for value in raw_last_values:
                resolved = _resolve_converted_id_alias(value)
                if resolved is None:
                    unresolved_last.append(value)
                else:
                    resolved_last_values.append(resolved)
                    if resolved != value:
                        remapped_any = True
            unresolved_values.extend(unresolved_last)
            if raw_last_values and not unresolved_last:
                remapped_last = " ".join(resolved_last_values)
                remapped_attrs = re.sub(r'\blast="[^"]+"', f'last="{html.escape(remapped_last, quote=True)}"', remapped_attrs)

        if not unresolved_values:
            if remapped_any:
                replacements += 1
                remapped_attrs = re.sub(r"\s+", " ", remapped_attrs).strip()
                if remapped_attrs:
                    return f"<xref {remapped_attrs}{closing}"
                return f"<xref{closing}"
            return match.group(0)

        unresolved_joined = ", ".join(dict.fromkeys(unresolved_values))
        new_attrs = re.sub(r'\s*\bref="[^"]*"', "", attrs)
        new_attrs = re.sub(r'\s*\bfirst="[^"]*"', "", new_attrs)
        new_attrs = re.sub(r'\s*\blast="[^"]*"', "", new_attrs)
        new_attrs = re.sub(r"\s+", " ", new_attrs).strip()
        provisional_attr = f'provisional="{html.escape(unresolved_joined, quote=True)}"'

        replacements += 1
        if new_attrs:
            return f"<xref {new_attrs} {provisional_attr}{closing}"
        return f"<xref {provisional_attr}{closing}"

    updated = xref_open_tag_pattern.sub(_replace, content)
    if replacements:
        target_file.write_text(updated, encoding="utf-8")
    return replacements


def strip_or_unwrap_webwork_in_target_file(target_file: Path) -> int:
    content = target_file.read_text(encoding="utf-8")
    changes = 0

    def _replace_exercises_with_webwork_placeholder(text: str) -> tuple[str, int]:
        replaced = 0
        webwork_indicator = re.compile(
            r"<webwork\b|webwork\s+activities\s+from\s+the\s+source\s+have\s+been\s+intentionally\s+omitted|\bwebwork\b",
            re.IGNORECASE,
        )
        exercise_pattern = re.compile(r"<exercise\b([^>]*)>(.*?)</exercise>", re.DOTALL)
        placeholder_body = "<statement><p>Webwork Omitted</p></statement>"

        def _replace(match: re.Match[str]) -> str:
            nonlocal replaced
            attrs = match.group(1) or ""
            body = match.group(2) or ""
            if not webwork_indicator.search(body):
                return match.group(0)
            replaced += 1
            return f"<exercise{attrs}>{placeholder_body}</exercise>"

        updated_text = exercise_pattern.sub(_replace, text)
        group_pattern = re.compile(r"<exercisegroup\b[^>]*>.*?</exercisegroup>", re.DOTALL)

        def _replace_group(match: re.Match[str]) -> str:
            nonlocal replaced
            body = match.group(0)
            if not webwork_indicator.search(body):
                return body
            replaced += 1
            return f"<exercise>{placeholder_body}</exercise>"

        updated_text = group_pattern.sub(_replace_group, updated_text)
        return updated_text, replaced

    def _replace_empty_exercises_with_placeholder(text: str) -> tuple[str, int]:
        replaced = 0
        exercise_pattern = re.compile(r"<exercise\b([^>]*)>(.*?)</exercise>", re.DOTALL)
        placeholder_body = "<statement><p>Webwork Omitted</p></statement>"

        def _replace(match: re.Match[str]) -> str:
            nonlocal replaced
            attrs = match.group(1) or ""
            body = match.group(2) or ""
            body_without_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
            if body_without_comments.strip():
                return match.group(0)
            replaced += 1
            return f"<exercise{attrs}>{placeholder_body}</exercise>"

        return exercise_pattern.sub(_replace, text), replaced

    updated, replaced_exercises = _replace_exercises_with_webwork_placeholder(content)
    changes += replaced_exercises

    paired_pattern = re.compile(r"<webwork\b[^>]*>(.*?)</webwork>", re.DOTALL)

    def _paired_repl(match: re.Match[str]) -> str:
        nonlocal changes
        payload = re.sub(r"<pg-code\b[^>]*>.*?</pg-code>", "", match.group(1), flags=re.DOTALL)
        payload = re.sub(r"<var\b[^>]*/>", "", payload)
        payload = re.sub(r"<webwork\b[^>]*/>", "", payload)
        payload = payload.strip()
        changes += 1
        return payload

    updated = paired_pattern.sub(_paired_repl, updated)

    self_pattern = re.compile(r"<webwork\b[^>]*/>")
    self_hits = len(self_pattern.findall(updated))
    if self_hits:
        changes += self_hits
        updated = self_pattern.sub("", updated)

    open_pattern = re.compile(r"<webwork\b[^>]*>")
    open_hits = len(open_pattern.findall(updated))
    if open_hits:
        changes += open_hits
        updated = open_pattern.sub("", updated)

    close_pattern = re.compile(r"</webwork>")
    close_hits = len(close_pattern.findall(updated))
    if close_hits:
        changes += close_hits
        updated = close_pattern.sub("", updated)

    updated, replaced_empty = _replace_empty_exercises_with_placeholder(updated)
    changes += replaced_empty

    updated = re.sub(r"\n\s*<exercise\b[^>]*>\s*</exercise>\s*\n", "\n", updated, flags=re.DOTALL)
    updated = re.sub(r"\n{3,}", "\n\n", updated)

    if changes:
        target_file.write_text(updated, encoding="utf-8")
    return changes


def migrate_top_level_exercises_from_section_file(section_file: Path) -> list[str]:
    content = section_file.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)^  <(?P<tag>exercisegroup|exercises|exercise)\b[^>]*>.*?^\s*</(?P=tag)>\s*$")

    extracted = [match.group(0).strip() for match in pattern.finditer(content)]
    if not extracted:
        return []

    updated = pattern.sub("", content)
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    section_file.write_text(updated, encoding="utf-8")
    return extracted


def wrap_orphan_top_level_exercises_in_target_file(target_file: Path, title: str = "Borrowed exercises") -> int:
    content = target_file.read_text(encoding="utf-8")
    block_pattern = re.compile(r"(?ms)^(?: {0,2})<(?P<tag>exercisegroup|exercise)\b[^>]*>.*?^\s*</(?P=tag)>\s*")

    matches = list(block_pattern.finditer(content))
    if not matches:
        return 0

    blocks = [match.group(0).strip() for match in matches if match.group(0).strip()]
    if not blocks:
        return 0

    content_without_orphans = block_pattern.sub("", content)
    wrapped = ["<exercises>", f"  <title>{html.escape(title)}</title>"]
    wrapped.extend(f"  {block}" for block in blocks)
    wrapped.append("</exercises>")
    wrapped_block = "\n".join(wrapped)

    if "<!-- END BORROWED CONTENT -->" in content_without_orphans:
        updated = content_without_orphans.replace(
            "<!-- END BORROWED CONTENT -->",
            f"{wrapped_block}\n\n  <!-- END BORROWED CONTENT -->",
            1,
        )
    else:
        updated = content_without_orphans + "\n\n" + wrapped_block + "\n"

    updated = re.sub(r"\n{3,}", "\n\n", updated)
    target_file.write_text(updated, encoding="utf-8")
    return len(blocks)


def normalize_orphan_exercise_tail_in_target_file(target_file: Path, title: str = "Borrowed exercises") -> int:
    content = target_file.read_text(encoding="utf-8")
    begin = "<!-- BEGIN BORROWED CONTENT -->"
    end = "<!-- END BORROWED CONTENT -->"
    start_idx = content.find(begin)
    end_idx = content.find(end)
    if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
        return 0

    borrowed = content[start_idx + len(begin):end_idx]
    last_exercises_close = borrowed.rfind("</exercises>")
    if last_exercises_close < 0:
        return 0

    head = borrowed[: last_exercises_close + len("</exercises>")]
    tail = borrowed[last_exercises_close + len("</exercises>"):]
    if not re.search(r"<exercise\b|<exercisegroup\b", tail):
        return 0

    tail = re.sub(r"^\s*</exercisegroup>\s*", "\n", tail)
    tail = re.sub(r"^\s*</exercises>\s*", "\n", tail)
    tail = tail.strip()
    if not tail:
        return 0

    wrapped_tail = "\n".join([
        "<exercises>",
        f"  <title>{html.escape(title)}</title>",
        tail,
        "</exercises>",
    ])

    rebuilt_borrowed = f"{head.strip()}\n\n{wrapped_tail}\n"
    updated = content[: start_idx + len(begin)] + "\n\n" + rebuilt_borrowed + "\n  " + content[end_idx:]
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    target_file.write_text(updated, encoding="utf-8")
    return 1


def remove_stray_top_level_exercise_closers_in_target_file(target_file: Path) -> int:
    content = target_file.read_text(encoding="utf-8")
    begin = "<!-- BEGIN BORROWED CONTENT -->"
    end = "<!-- END BORROWED CONTENT -->"
    start_idx = content.find(begin)
    end_idx = content.find(end)
    if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
        return 0

    prefix = content[: start_idx + len(begin)]
    borrowed = content[start_idx + len(begin):end_idx]
    suffix = content[end_idx:]

    patterns = [
        re.compile(r"(?ms)^\s*</exercisegroup>\s*(?=\n\s*<exercise\b|\n\s*<exercisegroup\b)"),
        re.compile(r"(?ms)^\s*</exercises>\s*(?=\n\s*<exercise\b|\n\s*<exercisegroup\b)"),
    ]

    removed = 0
    updated_borrowed = borrowed
    for pat in patterns:
        hits = len(pat.findall(updated_borrowed))
        if hits:
            removed += hits
            updated_borrowed = pat.sub("\n", updated_borrowed)

    if not removed:
        return 0

    updated = prefix + updated_borrowed + suffix
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    target_file.write_text(updated, encoding="utf-8")
    return removed
