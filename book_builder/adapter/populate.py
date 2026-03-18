"""Population orchestrator for CNXML and PreTeXt import flows.

This module coordinates matching, conversion, injection, and post-processing
for all supported source formats through one public API: `run_population()`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from book_builder.adapter.catalog import (
    build_chapter_folder_map,
    collect_references,
    enrich_toc_dataframe,
    load_open_textbooks,
    normalize_pretext_toc_dataframe,
    reference_attribution,
    resolve_target_file,
)
from book_builder.adapter.cnxml_adapter import convert_reference_to_fragments
from book_builder.adapter.document_io import (
    build_source_convention_block,
    collect_project_xml_ids,
    deduplicate_xml_ids_in_tree,
    ensure_chapter_includes_file,
    find_chapter_file_for_section,
    find_exercise_file_for_section,
    inject_content_into_target,
    migrate_top_level_exercises_from_section_file,
    normalize_latex_images_in_target_file,
    normalize_orphan_exercise_tail_in_target_file,
    provisionalize_unresolved_xrefs_in_target_file,
    read_section_id,
    strip_or_unwrap_webwork_in_target_file,
    update_section_attributes_and_convention,
    write_borrowed_section_file,
)
from book_builder.adapter.fragments import separate_exercise_fragments
from book_builder.adapter.models import NUM_OPEN_SOURCE_COLS, AttributionEntry, BOOK_STRUCTURE_COLUMNS, TOC_COLUMNS, resolve_input_path, text_or_empty
from book_builder.adapter.pretext_adapter import convert_pretext_reference_to_fragments
from book_builder.adapter.scoped_ids import ScopedIdRegistry


@dataclass(slots=True)
class PopulationOptions:
    """Runtime options controlling one population run."""
    source_format: Literal["auto", "cnxml", "pretext"]
    workspace_root: Path = Path(".")
    book_csv: Path = Path("input/Book Structure.csv")
    toc_csv: Path = Path("input/stax-toc.csv")
    reference_dir: Path = Path("reference")
    open_textbooks_csv: Path = Path("input/Open Textbooks.csv")
    enriched_toc_output: Path | None = None
    resource: str | None = None
    limit: int | None = None
    no_copy_images: bool = False
    dry_run: bool = False
    allowed_resources: tuple[str, ...] | None = None


@dataclass(slots=True)
class PopulationResult:
    """Summary of one population run."""
    processed: int
    matched: int
    warnings: list[str]
    enriched_toc_output: Path | None = None


def _load_inputs(options: PopulationOptions) -> tuple[Path, pd.DataFrame, pd.DataFrame, Path, dict]:
    """Load core input datasets for a single-format run."""
    workspace_root = options.workspace_root.resolve()
    book_csv = resolve_input_path(workspace_root, options.book_csv)
    toc_csv_arg = options.toc_csv
    if options.source_format == "pretext" and options.resource and toc_csv_arg == Path("input/stax-toc.csv"):
        toc_csv_arg = _discover_pretext_toc_csv(workspace_root, options.resource) or toc_csv_arg
    toc_csv = resolve_input_path(workspace_root, toc_csv_arg)
    reference_dir = resolve_input_path(workspace_root, options.reference_dir)
    open_textbooks_csv = resolve_input_path(workspace_root, options.open_textbooks_csv)

    book_df = pd.read_csv(book_csv)
    textbooks = load_open_textbooks(open_textbooks_csv)
    toc_raw_df = pd.read_csv(toc_csv)
    return reference_dir, book_df, toc_raw_df, workspace_root, textbooks


def _load_book_and_textbooks(options: PopulationOptions) -> tuple[pd.DataFrame, Path, dict]:
    """Load Book Structure and textbook metadata only."""
    workspace_root = options.workspace_root.resolve()
    book_csv = resolve_input_path(workspace_root, options.book_csv)
    open_textbooks_csv = resolve_input_path(workspace_root, options.open_textbooks_csv)
    return pd.read_csv(book_csv), workspace_root, load_open_textbooks(open_textbooks_csv)


def _prepare_toc_dataframe(options: PopulationOptions, toc_raw_df: pd.DataFrame, textbooks: dict) -> pd.DataFrame:
    """Normalize TOC data according to the selected source format."""
    if options.source_format == "cnxml":
        toc_df = toc_raw_df.copy()
        toc_df.columns = TOC_COLUMNS
        return enrich_toc_dataframe(toc_df, textbooks)

    resource_key = text_or_empty(options.resource).upper()
    if not resource_key:
        raise ValueError("--resource is required when source-format is 'pretext'")

    info = textbooks.get(resource_key)
    if info is None:
        raise ValueError(f"Resource '{resource_key}' not found in Open Textbooks CSV")

    legacy_map_df: pd.DataFrame | None = None
    legacy_map_path = _discover_pretext_legacy_map_csv(options.workspace_root.resolve(), resource_key)
    if legacy_map_path is not None and legacy_map_path.exists():
        legacy_map_df = pd.read_csv(legacy_map_path)

    return normalize_pretext_toc_dataframe(
        toc_raw_df,
        resource_key,
        info.source_url,
        info.textbook_name,
        info.license_name,
        info.license_url,
        legacy_map_df=legacy_map_df,
    )


def _convert_blocks_for_reference(
    options: PopulationOptions,
    reference,
    workspace_root: Path,
    target_file: Path,
    target_section_id: str,
    resource_key: str,
    scoped_id_registry: ScopedIdRegistry | None = None,
) -> list[str]:
    """Convert one matched reference into fragment blocks using the active adapter."""
    if options.source_format == "cnxml":
        return convert_reference_to_fragments(
            reference,
            workspace_root,
            target_file,
            target_section_id,
            options.no_copy_images,
            resource_key,
            scoped_id_registry,
        )
    return convert_pretext_reference_to_fragments(
        reference,
        workspace_root,
        target_section_id,
        scoped_id_registry=scoped_id_registry,
        target_file=target_file,
    )


def _interleave_source_conventions(
    section_id: str,
    chunks: list[tuple[str, list[str], AttributionEntry]],
) -> list[str]:
    """Insert `<convention>` blocks when borrowed content source changes."""
    if not chunks:
        return []

    output: list[str] = []
    run_resource = ""
    run_attributions: list[AttributionEntry] = []

    def flush_run() -> None:
        if not run_attributions:
            return
        convention = build_source_convention_block(section_id, run_attributions)
        if convention:
            output.append(convention)

    for resource_key, blocks, attribution in chunks:
        if run_resource and resource_key != run_resource:
            flush_run()
            run_attributions = []

        run_resource = resource_key
        run_attributions.append(attribution)
        output.extend(blocks)

    flush_run()
    return output


def _should_keep_reference(options: PopulationOptions, reference) -> bool:
    """Apply source/resource filters for a matched reference."""
    if options.allowed_resources:
        allowed = {item.upper() for item in options.allowed_resources}
        if text_or_empty(reference.resource).upper() not in allowed:
            return False
    if options.source_format == "pretext" and options.resource:
        return text_or_empty(reference.resource).upper() == text_or_empty(options.resource).upper()
    return True


def _collect_referenced_resources(book_df: pd.DataFrame, limit: int | None = None) -> set[str]:
    """Collect unique referenced resource abbreviations from Book Structure rows."""
    resource_columns = [
        f"Open Source Resource {i}" for i in range(1, NUM_OPEN_SOURCE_COLS + 1)]
    resources: set[str] = set()
    scanned = 0

    for _, row in book_df.iterrows():
        chapter_title = text_or_empty(row.get(BOOK_STRUCTURE_COLUMNS["chapter"]))
        section_title = text_or_empty(row.get(BOOK_STRUCTURE_COLUMNS["section"]))
        if not chapter_title or not section_title:
            continue

        if limit is not None and scanned >= limit:
            break

        for column_name in resource_columns:
            resource = text_or_empty(row.get(column_name)).upper()
            if resource:
                resources.add(resource)
        scanned += 1

    return resources


def _row_mentions_allowed_resource(book_row: pd.Series, allowed_resources: tuple[str, ...] | None) -> bool:
    """Return whether a row references one of the allowed resources."""
    if not allowed_resources:
        return True

    resource_columns = [
        BOOK_STRUCTURE_COLUMNS["resource"],
        "Open Source Resource 2",
        "Open Source Resource 3",
        "Open Source Resource 4",
    ]
    allowed = {item.upper() for item in allowed_resources}
    for column_name in resource_columns:
        if text_or_empty(book_row.get(column_name)).upper() in allowed:
            return True
    return False


def _count_book_rows(book_df: pd.DataFrame, limit: int | None = None) -> int:
    """Count processable Book Structure rows under the optional `limit`."""
    count = 0
    for _, row in book_df.iterrows():
        chapter_title = text_or_empty(row.get(BOOK_STRUCTURE_COLUMNS["chapter"]))
        section_title = text_or_empty(row.get(BOOK_STRUCTURE_COLUMNS["section"]))
        if not chapter_title or not section_title:
            continue
        if limit is not None and count >= limit:
            break
        count += 1
    return count


def _discover_pretext_toc_csv(workspace_root: Path, resource: str) -> Path | None:
    """Best-effort discovery of a resource-specific PreTeXt TOC CSV."""
    input_dir = workspace_root / "input"
    resource_key = text_or_empty(resource).lower()
    direct_match = input_dir / f"{resource_key}-toc.csv"
    if direct_match.exists():
        return direct_match

    matches = sorted(
        path
        for path in input_dir.glob("*toc*.csv")
        if resource_key in path.stem.lower() and not path.name.endswith(".enriched.csv")
    )
    if len(matches) == 1:
        return matches[0]
    return None


def _discover_pretext_legacy_map_csv(workspace_root: Path, resource: str) -> Path | None:
    """Best-effort discovery of a resource-specific legacy ID map CSV."""
    input_dir = workspace_root / "input"
    resource_key = text_or_empty(resource).lower()

    direct_matches = [
        input_dir / f"{resource_key}-toc-legacy-id-map.csv",
        input_dir / f"{resource_key}-legacy-id-map.csv",
        input_dir / f"{resource_key}-id-mapping.csv",
    ]
    for candidate in direct_matches:
        if candidate.exists():
            return candidate

    matches = sorted(
        path
        for path in input_dir.glob("*id*map*.csv")
        if resource_key in path.stem.lower()
    )
    if len(matches) == 1:
        return matches[0]
    return None


def _run_auto_population(options: PopulationOptions) -> PopulationResult:
    """Auto-dispatch population by inspecting each referenced resource type."""
    book_df, workspace_root, textbooks = _load_book_and_textbooks(options)
    referenced_resources = _collect_referenced_resources(book_df, options.limit)
    processed_rows = _count_book_rows(book_df, options.limit)
    warnings: list[str] = []
    matched = 0
    enriched_toc_output: Path | None = None

    pretext_resources: list[str] = []
    cnxml_resources: list[str] = []

    for resource in sorted(referenced_resources):
        info = textbooks.get(resource)
        if info is None:
            warnings.append(f"Resource '{resource}' not found in Open Textbooks CSV; treating it as CNXML")
            cnxml_resources.append(resource)
            continue

        if info.is_pretext:
            pretext_resources.append(resource)
        else:
            cnxml_resources.append(resource)

    if cnxml_resources:
        cnxml_result = run_population(
            PopulationOptions(
                source_format="cnxml",
                workspace_root=options.workspace_root,
                book_csv=options.book_csv,
                toc_csv=options.toc_csv,
                reference_dir=options.reference_dir,
                open_textbooks_csv=options.open_textbooks_csv,
                enriched_toc_output=options.enriched_toc_output,
                limit=options.limit,
                no_copy_images=options.no_copy_images,
                dry_run=options.dry_run,
                allowed_resources=tuple(cnxml_resources),
            )
        )
        matched += cnxml_result.matched
        warnings.extend(cnxml_result.warnings)
        enriched_toc_output = cnxml_result.enriched_toc_output

    for resource in pretext_resources:
        toc_csv = _discover_pretext_toc_csv(workspace_root, resource)
        if toc_csv is None:
            warnings.append(
                f"Skipping PreTeXt resource '{resource}': no TOC CSV found at input/{resource.lower()}-toc.csv"
            )
            continue

        pretext_result = run_population(
            PopulationOptions(
                source_format="pretext",
                workspace_root=options.workspace_root,
                book_csv=options.book_csv,
                toc_csv=toc_csv,
                reference_dir=options.reference_dir,
                open_textbooks_csv=options.open_textbooks_csv,
                resource=resource,
                limit=options.limit,
                no_copy_images=options.no_copy_images,
                dry_run=options.dry_run,
                allowed_resources=(resource,),
            )
        )
        matched += pretext_result.matched
        warnings.extend(pretext_result.warnings)

    return PopulationResult(
        processed=processed_rows,
        matched=matched,
        warnings=warnings,
        enriched_toc_output=enriched_toc_output,
    )


def _run_cnxml_population(
    options: PopulationOptions,
    workspace_root: Path,
    reference_dir: Path,
    book_df: pd.DataFrame,
    toc_df: pd.DataFrame,
    textbooks: dict,
) -> PopulationResult:
    """Run the CNXML conversion/injection flow."""
    chapter_folder_map = build_chapter_folder_map(book_df)
    known_ids = collect_project_xml_ids(reference_dir, workspace_root / "source")
    scoped_id_registry = ScopedIdRegistry.load(workspace_root / "input" / "cnxml-scoped-id-map.json", known_ids)

    processed = 0
    matched = 0
    warnings: list[str] = []
    chapter_exercises: dict[Path, dict[str, object]] = {}

    for _, book_row in book_df.iterrows():
        if options.limit is not None and processed >= options.limit:
            break

        chapter_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["chapter"]))
        section_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["section"]))
        if not chapter_title or not section_title:
            continue

        target_file = resolve_target_file(book_row, reference_dir, chapter_folder_map)
        if not target_file.exists():
            warnings.append(f"Missing target file: {target_file}")
            processed += 1
            continue

        references = [ref for ref in collect_references(book_row, toc_df) if _should_keep_reference(options, ref)]
        if not references:
            if _row_mentions_allowed_resource(book_row, options.allowed_resources):
                warnings.append(f"No TOC match for {chapter_title} / {section_title}")
            processed += 1
            continue

        target_section_id = read_section_id(target_file)
        chapter_file = find_chapter_file_for_section(target_file)
        chapter_ex_file: Path | None = None
        chapter_ex_section_id = ""
        if chapter_file is not None:
            chapter_slug = chapter_file.stem.removeprefix("ch-")
            chapter_ex_file = chapter_file.parent / f"ex-{chapter_slug}.ptx"
            chapter_ex_section_id = chapter_ex_file.stem

        section_chunks: list[tuple[str, list[str], AttributionEntry]] = []
        attribution_entries: list[AttributionEntry] = []
        seen_section_reference_keys: set[tuple[str, str, str]] = set()

        for reference in references:
            try:
                converted_blocks = _convert_blocks_for_reference(
                    options,
                    reference,
                    workspace_root,
                    target_file,
                    target_section_id,
                    text_or_empty(reference.resource),
                    scoped_id_registry,
                )
            except (ET.ParseError, ValueError, FileNotFoundError) as exc:
                warnings.append(
                    f"Failed converting {chapter_title} / {section_title} from {reference.resource}-{reference.ref_id}: {exc}"
                )
                continue

            if not converted_blocks:
                continue

            non_exercise_blocks, exercise_blocks = separate_exercise_fragments(converted_blocks)
            header = f"<!-- Borrowed from {reference.resource} {reference.ref_id}: {reference.title} -->"
            dedupe_key = (
                text_or_empty(reference.resource).upper(),
                text_or_empty(reference.toc_row.get("ID")),
                text_or_empty(reference.toc_row.get("source_path")),
            )

            if non_exercise_blocks and reference.label != "exercise" and dedupe_key not in seen_section_reference_keys:
                seen_section_reference_keys.add(dedupe_key)
                source_attr = reference_attribution(reference, textbooks)
                chunk_blocks = [header, *non_exercise_blocks]
                section_chunks.append((text_or_empty(reference.resource).upper(), chunk_blocks, source_attr))
                attribution_entries.append(source_attr)

            if chapter_ex_file is not None and chapter_file is not None and exercise_blocks:
                payload = chapter_exercises.setdefault(
                    chapter_ex_file,
                    {
                        "chapter_file": chapter_file,
                        "section_id": chapter_ex_section_id,
                        "title": f"{chapter_title} Exercises",
                        "fragment_blocks": [],
                        "attributions": [],
                        "seen_keys": set(),
                    },
                )
                seen_keys = payload["seen_keys"]
                if dedupe_key not in seen_keys:
                    seen_keys.add(dedupe_key)
                    payload["fragment_blocks"].extend(exercise_blocks)
                    payload["attributions"].append(reference_attribution(reference, textbooks))

            matched += 1

        section_fragment_blocks = _interleave_source_conventions(target_section_id, section_chunks)
        if references and section_fragment_blocks and not options.dry_run:
            inject_content_into_target(target_file, section_fragment_blocks)
            if attribution_entries:
                update_section_attributes_and_convention(
                    target_file,
                    target_section_id,
                    attribution_entries,
                    include_convention=False,
                )

        processed += 1

    if not options.dry_run:
        for ex_file, payload in sorted(chapter_exercises.items(), key=lambda item: str(item[0])):
            fragment_blocks = payload["fragment_blocks"]
            if not fragment_blocks:
                continue

            write_borrowed_section_file(
                ex_file,
                str(payload["section_id"]),
                str(payload["title"]),
                fragment_blocks,
                list(payload["attributions"]),
                wrap_in_exercises=True,
            )
            ensure_chapter_includes_file(Path(payload["chapter_file"]), ex_file.name)

    if not options.dry_run:
        scoped_id_registry.save()
        deduplicate_xml_ids_in_tree(reference_dir)

    return PopulationResult(processed=processed, matched=matched, warnings=warnings, enriched_toc_output=options.enriched_toc_output)


def _run_pretext_population(
    options: PopulationOptions,
    workspace_root: Path,
    reference_dir: Path,
    book_df: pd.DataFrame,
    toc_df: pd.DataFrame,
    textbooks: dict,
) -> PopulationResult:
    """Run the PreTeXt conversion/injection flow."""
    chapter_folder_map = build_chapter_folder_map(book_df)
    known_ids = collect_project_xml_ids(reference_dir, workspace_root / "source")
    scoped_id_registry = ScopedIdRegistry.load(workspace_root / "input" / "cnxml-scoped-id-map.json", known_ids)

    processed = 0
    matched = 0
    warnings: list[str] = []
    resource_key = text_or_empty(options.resource).upper()

    for _, book_row in book_df.iterrows():
        if options.limit is not None and processed >= options.limit:
            break

        chapter_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["chapter"]))
        section_title = text_or_empty(book_row.get(BOOK_STRUCTURE_COLUMNS["section"]))
        if not chapter_title or not section_title:
            continue

        target_file = resolve_target_file(book_row, reference_dir, chapter_folder_map)
        if not target_file.exists():
            warnings.append(f"Missing target file: {target_file}")
            processed += 1
            continue

        references = [ref for ref in collect_references(book_row, toc_df) if _should_keep_reference(options, ref)]
        if not references:
            processed += 1
            continue

        target_section_id = read_section_id(target_file)
        existing_content = target_file.read_text(encoding="utf-8")
        exercise_target_file = find_exercise_file_for_section(target_file)

        section_chunks: list[tuple[str, list[str], AttributionEntry]] = []
        chapter_exercise_blocks: list[str] = []
        attribution_entries: list[AttributionEntry] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for reference in references:
            header = f"<!-- Borrowed from {reference.resource} {reference.ref_id}: {reference.title} -->"
            if header in existing_content:
                continue

            try:
                converted_blocks = _convert_blocks_for_reference(
                    options,
                    reference,
                    workspace_root,
                    target_file,
                    target_section_id,
                    resource_key,
                    scoped_id_registry,
                )
            except (ET.ParseError, ValueError, FileNotFoundError) as exc:
                warnings.append(
                    f"Failed converting {chapter_title} / {section_title} from {reference.resource}-{reference.ref_id}: {exc}"
                )
                continue

            if not converted_blocks:
                continue

            non_exercise_blocks, exercise_blocks = separate_exercise_fragments(converted_blocks)
            if not non_exercise_blocks and not exercise_blocks:
                continue

            dedupe_key = (
                text_or_empty(reference.resource).upper(),
                text_or_empty(reference.toc_row.get("ID")),
                text_or_empty(reference.toc_row.get("source_path")),
            )
            if dedupe_key in seen_keys:
                continue

            seen_keys.add(dedupe_key)
            if non_exercise_blocks:
                source_attr = reference_attribution(reference, textbooks)
                chunk_blocks = [header, *non_exercise_blocks]
                section_chunks.append((text_or_empty(reference.resource).upper(), chunk_blocks, source_attr))
            if exercise_blocks:
                source_label = text_or_empty(reference.resource).upper() or resource_key
                chapter_exercise_blocks.append(header)
                grouped_exercises = [
                    "<exercises>",
                    f"  <title>{source_label} exercises</title>",
                ] + [f"  {block}" for block in exercise_blocks] + ["</exercises>"]
                chapter_exercise_blocks.append("\n".join(grouped_exercises))
            attribution_entries.append(reference_attribution(reference, textbooks))
            matched += 1

        section_fragment_blocks = _interleave_source_conventions(target_section_id, section_chunks)
        if section_fragment_blocks and not options.dry_run:
            inject_content_into_target(target_file, section_fragment_blocks, append=True)
            if attribution_entries:
                update_section_attributes_and_convention(
                    target_file,
                    target_section_id,
                    attribution_entries,
                    include_convention=False,
                )

        if chapter_exercise_blocks and not options.dry_run:
            if exercise_target_file is None:
                warnings.append(f"Missing chapter exercise file for section: {target_file}")
            else:
                inject_content_into_target(exercise_target_file, chapter_exercise_blocks, append=True)

        if references and not options.dry_run:
            moved_blocks = migrate_top_level_exercises_from_section_file(target_file)
            if moved_blocks:
                if exercise_target_file is None:
                    warnings.append(f"Could not migrate exercises; missing chapter exercise file for {target_file}")
                else:
                    migrated_title = f"{resource_key} migrated exercises"
                    migrated_wrapper = [
                        "<exercises>",
                        f"  <title>{migrated_title}</title>",
                    ] + [f"  {block}" for block in moved_blocks] + ["</exercises>"]
                    inject_content_into_target(exercise_target_file, ["\n".join(migrated_wrapper)], append=True)

            strip_or_unwrap_webwork_in_target_file(target_file)
            normalize_latex_images_in_target_file(target_file)
            provisionalize_unresolved_xrefs_in_target_file(target_file, known_ids)

            if exercise_target_file is not None and exercise_target_file.exists():
                strip_or_unwrap_webwork_in_target_file(exercise_target_file)
                provisionalize_unresolved_xrefs_in_target_file(exercise_target_file, known_ids)
                normalize_orphan_exercise_tail_in_target_file(exercise_target_file, f"{resource_key} exercises")

            known_ids = collect_project_xml_ids(reference_dir, workspace_root / "source")

        processed += 1

    if not options.dry_run:
        scoped_id_registry.save()
        deduplicate_xml_ids_in_tree(reference_dir)

    if not options.dry_run:
        for sec_file in sorted(reference_dir.rglob("sec-*.ptx")):
            ex_file = find_exercise_file_for_section(sec_file)
            moved_blocks = migrate_top_level_exercises_from_section_file(sec_file)
            if moved_blocks:
                if ex_file is None:
                    warnings.append(f"Could not migrate exercises; missing chapter exercise file for {sec_file}")
                else:
                    migrated_wrapper = [
                        "<exercises>",
                        "  <title>Borrowed migrated exercises</title>",
                    ] + [f"  {block}" for block in moved_blocks] + ["</exercises>"]
                    inject_content_into_target(ex_file, ["\n".join(migrated_wrapper)], append=True)

            strip_or_unwrap_webwork_in_target_file(sec_file)
            normalize_latex_images_in_target_file(sec_file)

            if ex_file is not None and ex_file.exists():
                strip_or_unwrap_webwork_in_target_file(ex_file)
                normalize_orphan_exercise_tail_in_target_file(ex_file, "Borrowed exercises")

        known_ids = collect_project_xml_ids(reference_dir, workspace_root / "source")
        for ptx_file in sorted(reference_dir.rglob("*.ptx")):
            provisionalize_unresolved_xrefs_in_target_file(ptx_file, known_ids)

    return PopulationResult(processed=processed, matched=matched, warnings=warnings, enriched_toc_output=options.enriched_toc_output)


def run_population(options: PopulationOptions) -> PopulationResult:
    """Single entry point for all supported population flows."""
    if options.source_format == "auto":
        return _run_auto_population(options)

    reference_dir, book_df, toc_raw_df, workspace_root, textbooks = _load_inputs(options)
    toc_df = _prepare_toc_dataframe(options, toc_raw_df, textbooks)

    if options.enriched_toc_output is not None and options.source_format == "cnxml":
        enriched_toc_output = resolve_input_path(workspace_root, options.enriched_toc_output)
        enriched_toc_output.parent.mkdir(parents=True, exist_ok=True)
        toc_df.to_csv(enriched_toc_output, index=False)
        options = PopulationOptions(
            source_format=options.source_format,
            workspace_root=options.workspace_root,
            book_csv=options.book_csv,
            toc_csv=options.toc_csv,
            reference_dir=options.reference_dir,
            open_textbooks_csv=options.open_textbooks_csv,
            enriched_toc_output=enriched_toc_output,
            resource=options.resource,
            limit=options.limit,
            no_copy_images=options.no_copy_images,
            dry_run=options.dry_run,
        )

    if options.source_format == "cnxml":
        return _run_cnxml_population(options, workspace_root, reference_dir, book_df, toc_df, textbooks)
    return _run_pretext_population(options, workspace_root, reference_dir, book_df, toc_df, textbooks)
