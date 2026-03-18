#!/usr/bin/env python3
"""Prototype CNXML -> PreTeXt section converter.

This is intentionally conservative and aimed at first-pass migration.
It converts common CNXML structures and leaves unknown tags as TODO comments.
"""

from __future__ import annotations

import argparse
import copy
import random
import re
import string
import xml.etree.ElementTree as ET
from pathlib import Path

from book_builder.adapter.cnxml_shared import (
    clean_text,
    copy_image_to_assets,
    escape_ampersands_in_xml,
    has_matrix_environment,
    local,
    mathml_to_tex,
    maybe_convert_cases,
    normalize_tex_notation,
    render_multiline_math,
    resolve_or_downgrade_xrefs,
    sanitize_angle_operators_outside_math,
    source_origin_path,
)
from book_builder.adapter.scoped_ids import ScopedIdRegistry

NS = {
    "c": "http://cnx.rice.edu/cnxml",
    "m": "http://www.w3.org/1998/Math/MathML",
    "md": "http://cnx.rice.edu/mdml",
}

CIRCLED_LOWER = "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ"
CIRCLED_SET = set(CIRCLED_LOWER)
CURRENT_ID_PREFIX = ""
LOCAL_SOURCE_IDS: set[str] = set()
RANDOMIZE_SCOPED_IDS = False
SCOPED_ID_MAP: dict[str, str] = {}
RANDOM_ID_ALPHABET = string.ascii_letters + string.digits
CURRENT_SOURCE_ORIGINAL = ""
CURRENT_SOURCE_LICENSE = "CC-BY-4.0"
CURRENT_RESOURCE_CODE = "SRC"
CURRENT_TARGET_FILE = ""
CURRENT_TARGET_SECTION_ID = ""
CURRENT_TARGET_EXISTING_IDS: set[str] = set()
CURRENT_SCOPED_ID_REGISTRY: ScopedIdRegistry | None = None


def norm_id(value: str | None, fallback: str = "id") -> str:
    if not value:
        value = fallback
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
    if not re.match(r"^[A-Za-z_]", value):
        value = f"x-{value}"
    return value


def random_id_token(length: int = 8) -> str:
    return "".join(random.choice(RANDOM_ID_ALPHABET) for _ in range(length))


def _read_existing_target_ids(target_file: Path) -> set[str]:
    if not target_file.exists():
        return set()
    text = target_file.read_text(encoding="utf-8")
    return set(re.findall(r'\bxml:id="([^"]+)"', text))


def scoped_id(value: str | None, fallback: str = "id") -> str:
    base = norm_id(value, fallback)
    if CURRENT_ID_PREFIX:
        base = norm_id(f"{CURRENT_ID_PREFIX}-{base}", fallback)

    if not RANDOMIZE_SCOPED_IDS:
        return base

    original_id = (value or "").strip()
    if CURRENT_SCOPED_ID_REGISTRY is not None and original_id:
        scope_key = CURRENT_SCOPED_ID_REGISTRY.make_simple_scope_key(
            source_path=CURRENT_SOURCE_ORIGINAL,
            resource_code=CURRENT_RESOURCE_CODE,
            original_id=original_id,
        )

        cached = SCOPED_ID_MAP.get(scope_key)
        if cached is not None:
            return cached

        resolved = CURRENT_SCOPED_ID_REGISTRY.resolve_simple_code(
            scope_key=scope_key,
            resource_code=CURRENT_RESOURCE_CODE,
            source_path=CURRENT_SOURCE_ORIGINAL,
            target_file=CURRENT_TARGET_FILE,
            target_section_id=CURRENT_TARGET_SECTION_ID,
            original_id=original_id,
            fallback=fallback,
            random_token_factory=random_id_token,
        )
        SCOPED_ID_MAP[scope_key] = resolved
        return resolved

    scope_key = "|".join([CURRENT_SOURCE_ORIGINAL, CURRENT_ID_PREFIX, original_id, fallback])

    cached = SCOPED_ID_MAP.get(scope_key)
    if cached is not None:
        return cached

    if CURRENT_SCOPED_ID_REGISTRY is not None:
        resolved = CURRENT_SCOPED_ID_REGISTRY.resolve(
            scope_key=scope_key,
            base_id=base,
            source_path=CURRENT_SOURCE_ORIGINAL,
            target_file=CURRENT_TARGET_FILE,
            target_section_id=CURRENT_TARGET_SECTION_ID,
            original_id=original_id,
            fallback=fallback,
            existing_target_ids=CURRENT_TARGET_EXISTING_IDS,
            random_token_factory=random_id_token,
        )
        SCOPED_ID_MAP[scope_key] = resolved
        return resolved

    generated = norm_id(f"{base}-{random_id_token(8)}", fallback)
    SCOPED_ID_MAP[scope_key] = generated
    return generated


def scoped_ref(value: str | None, fallback: str = "xref") -> str:
    if value and value.strip() in LOCAL_SOURCE_IDS and CURRENT_ID_PREFIX:
        return scoped_id(value, fallback)
    return norm_id(value, fallback)


def has_class(node: ET.Element, class_name: str) -> bool:
    classes = node.attrib.get("class", "")
    return class_name in classes.split()


def section_title(node: ET.Element) -> str:
    return clean_text(node.findtext("c:title", default="", namespaces=NS))


def provenance_attrs(xml_id: str | None = None, extra_attrs: list[str] | None = None) -> str:
    attrs: list[str] = []
    if xml_id:
        attrs.append(f'xml:id="{xml_id}"')
    if CURRENT_SOURCE_ORIGINAL:
        attrs.append(f'original="{CURRENT_SOURCE_ORIGINAL}"')
    if CURRENT_SOURCE_LICENSE:
        attrs.append(f'license="{CURRENT_SOURCE_LICENSE}"')
    if extra_attrs:
        attrs.extend(extra_attrs)
    return " ".join(attrs)


def render_exercisegroup_with_intro(
    intro_paras: list[ET.Element],
    exercise_nodes: list[ET.Element],
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str,
    title: str | None = None,
    cols: int | None = 2,
) -> list[str]:
    lines: list[str] = [f"{indent}<exercisegroup>"]
    if title:
        lines.append(f"{indent}    <title>{title}</title>")
    lines.append(f"{indent}    <introduction>")
    for para in intro_paras:
        lines.append(convert_para(para, indent + "        "))
    lines.append(f"{indent}    </introduction>")
    lines.extend(
        _convert_exercise_run(
            exercise_nodes,
            input_file,
            output_file,
            workspace_root,
            assets_subdir,
            copy_images,
            indent + "    ",
            cols=cols,
            wrap_container=False,
        )
    )
    lines.append(f"{indent}</exercisegroup>")
    return lines


def script_text(node: ET.Element) -> str:
    """Extract plain text content for a <sup>/<sub> script node."""
    return clean_text("".join(node.itertext()))


def looks_like_italic_math_variable(text: str) -> tuple[str, str] | None:
    """Return (variable, trailing_punctuation) for math-like italic tokens.

    We intentionally only accept a single Latin letter (optionally followed by
    sentence punctuation) to avoid converting normal emphasized words.
    """
    token = clean_text(text)
    m = re.fullmatch(r"([A-Za-z])([,.;:]?)", token)
    if not m:
        return None
    return m.group(1), m.group(2)


def is_mathish_italic_emphasis(parent: ET.Element, index: int) -> bool:
    """Heuristic: detect italicized variable tokens used in prose math."""
    child = list(parent)[index]
    if local(child.tag) != "emphasis":
        return False

    effect = (child.attrib.get("effect") or "").strip().lower()
    if effect and effect != "italics":
        return False

    if list(child):
        return False

    parsed = looks_like_italic_math_variable(child.text or "")
    if not parsed:
        return False

    siblings = list(parent)
    prev_tag = local(siblings[index - 1].tag) if index > 0 else ""
    next_tag = local(siblings[index + 1].tag) if index + 1 < len(siblings) else ""
    if prev_tag in {"math", "sup", "sub"} or next_tag in {"math", "sup", "sub"}:
        return True

    prev_text = parent.text if index == 0 else siblings[index - 1].tail
    next_text = child.tail or ""
    context = f"{(prev_text or '')[-12:]} {(next_text or '')[:12]}"

    # Nearby arithmetic/comparison cues strongly indicate math prose.
    if re.search(r"[0-9=+\-−*/^<>≤≥≠×·]", context):
        return True

    # Parentheses around a variable in prose, e.g. (x), f(x), etc.
    if re.search(r"[\(\[\{]\s*$", prev_text or ""):
        return True
    if re.search(r"^\s*[\)\]\},]", next_text):
        return True

    return False


def render_inline(node: ET.Element) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)

    children = list(node)
    i = 0
    while i < len(children):
        child = children[i]
        tag = local(child.tag)

        if tag == "math":
            tex = normalize_tex_notation(mathml_to_tex(child))
            display = child.attrib.get("display") == "block"
            parts.append(f"<me>{tex}</me>" if display else f"<m>{tex}</m>")
        elif tag == "term":
            parts.append(f"<term>{render_inline(child)}</term>")
        elif tag == "emphasis":
            if is_mathish_italic_emphasis(node, i):
                parsed = looks_like_italic_math_variable(child.text or "")
                assert parsed is not None
                var, trailing_punct = parsed
                tex = var

                # Absorb immediate <sup>/<sub> so x<sup>2</sup> becomes <m>x^2</m>.
                consumed = i
                if i + 1 < len(children):
                    nxt = children[i + 1]
                    nxt_tag = local(nxt.tag)
                    if nxt_tag in {"sup", "sub"}:
                        scr = script_text(nxt)
                        if scr:
                            scr_tex = scr if len(scr) == 1 else "{" + scr + "}"
                            tex += "^" + scr_tex if nxt_tag == "sup" else "_" + scr_tex
                            consumed = i + 1

                parts.append(f"<m>{tex}</m>{trailing_punct}")

                # Use the tail from the last consumed node.
                tail = children[consumed].tail or ""
                if tail:
                    parts.append(tail)

                i = consumed + 1
                continue

            parts.append(f"<em>{render_inline(child)}</em>")
        elif tag == "footnote":
            content = clean_text("".join(child.itertext()))
            if content.startswith("http://") or content.startswith("https://"):
                parts.append(f"<fn><url href=\"{content}\">{content}</url></fn>")
            else:
                parts.append(f"<fn>{content}</fn>")
        elif tag == "link":
            ref = scoped_ref(child.attrib.get("target-id"), "xref")
            parts.append(f"<xref ref=\"{ref}\"/>")
        else:
            txt = clean_text("".join(child.itertext()))
            if txt:
                parts.append(txt)

        if child.tail:
            parts.append(child.tail)

        i += 1

    return clean_text("".join(parts))


def format_inline_paragraph(content: str, indent: str = "") -> str:
    # Paragraphs that encode alpha-labeled items as inline circled letters, e.g.
    # "ⓐ ... ⓑ ...", should become a real ordered list.
    marker_pat = re.compile(f"[{re.escape(CIRCLED_LOWER)}]")
    matches = list(marker_pat.finditer(content))
    if len(matches) >= 2:
        items: list[str] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            item = content[start:end].strip()
            item = re.sub(r"^[\s\)\.-:;]+", "", item)
            item = item.strip()
            if item:
                items.append(item)
        if len(items) >= 2:
            lines = [f"{indent}<ol marker=\"(a)\">"]
            for item in items:
                lines.append(f"{indent}    <li>{item}</li>")
            lines.append(f"{indent}</ol>")
            return "\n".join(lines)

    return f"{indent}<p>{content}</p>"


def strip_circled_prefix(text: str) -> tuple[str, bool]:
    t = text.lstrip()
    if not t:
        return t, False
    if t[0] in CIRCLED_SET:
        t = t[1:]
        t = re.sub(r"^[\s\.)\-:;]+", "", t)
        return t.strip(), True
    return text.strip(), False


def convert_para(node: ET.Element, indent: str = "") -> str:
    # Special case: paragraph that is only a math expression
    children = list(node)
    if len(children) == 1 and local(children[0].tag) == "math":
        math_child = children[0]
        leading_text = clean_text(node.text or "")
        trailing_text = clean_text(math_child.tail or "")
        if not leading_text and not trailing_text:
            tex = normalize_tex_notation(mathml_to_tex(math_child))
            display = math_child.attrib.get("display") == "block"

            # Aligned/multi-row TeX cannot live safely in inline math (<m>);
            # emit display math rows to avoid "misplaced &" rendering errors.
            if (r"\\" in tex or "&" in tex) and not has_matrix_environment(tex):
                cases_tex = maybe_convert_cases(tex)
                if cases_tex:
                    return f"{indent}<p><me>{cases_tex}</me></p>"
                rows = [r.strip() for r in tex.split(r"\\") if r.strip()]
                if len(rows) > 1:
                    return render_multiline_math(tex, indent)

            if display:
                return f"{indent}<p><me>{tex}</me></p>"

            return f"{indent}<p><m>{tex}</m></p>"

    newline_math_children = [child for child in children if local(child.tag) in {"newline", "math"}]
    if len(newline_math_children) == len(children) and sum(local(child.tag) == "math" for child in children) == 1:
        math_child = next(child for child in children if local(child.tag) == "math")
        tex = normalize_tex_notation(mathml_to_tex(math_child))
        multiline_rows = [r.strip() for r in tex.split(r"\\") if r.strip()]
        if (len(multiline_rows) > 1 and not has_matrix_environment(tex)) or math_child.attrib.get("display") == "block":
            before_parts: list[str] = [node.text or ""]
            after_parts: list[str] = []
            seen_math = False

            for child in children:
                if local(child.tag) == "math":
                    seen_math = True
                tail = child.tail or ""
                if seen_math:
                    after_parts.append(tail)
                else:
                    before_parts.append(tail)

            before_text = clean_text("".join(before_parts))
            after_text = clean_text("".join(after_parts))
            lines: list[str] = []
            if before_text:
                lines.append(f"{indent}<p>{before_text}</p>")

            if len(multiline_rows) > 1 and not has_matrix_environment(tex):
                cases_tex = maybe_convert_cases(tex)
                if cases_tex:
                    lines.append(f"{indent}<p><me>{cases_tex}</me></p>")
                else:
                    lines.append(render_multiline_math(tex, indent))
            else:
                lines.append(f"{indent}<p><me>{tex}</me></p>")

            if after_text:
                lines.append(f"{indent}<p>{after_text}</p>")

            return "\n".join(lines)

    # CNXML sometimes places a <list> inside a <para>. Preserve this structure
    # as paragraph text plus a real list block instead of flattening list text.
    if any(local(child.tag) == "list" for child in children):
        lines: list[str] = []
        inline_container = ET.Element("inline")
        inline_container.text = node.text

        def flush_inline() -> None:
            content = render_inline(inline_container)
            if content:
                lines.append(format_inline_paragraph(content, indent))

        for child in children:
            tag = local(child.tag)
            if tag == "list":
                flush_inline()
                lines.append(convert_list(child, indent))
                inline_container = ET.Element("inline")
                inline_container.text = child.tail
            else:
                cloned = copy.deepcopy(child)
                inline_container.append(cloned)

        flush_inline()
        return "\n".join(lines)

    content = render_inline(node)
    return format_inline_paragraph(content, indent)


def convert_list(node: ET.Element, indent: str = "", cols=None) -> str:
    raw_items = [render_inline(item) for item in node.findall("c:item", NS)]

    all_have_circled_prefix = bool(raw_items) and all(
        item.lstrip() and item.lstrip()[0] in CIRCLED_SET for item in raw_items
    )

    list_type = node.attrib.get("list-type", "bulleted")
    ordered_types = {"enumerated", "labeled-item"}
    if list_type in ordered_types:
        marker_attr = ' marker="(a)"' if all_have_circled_prefix else ""
        cols_attr = f' cols="{cols}"' if cols else ""
        lines = [f"{indent}<ol{marker_attr}{cols_attr}>"]
        for item in raw_items:
            content = strip_circled_prefix(item)[0] if all_have_circled_prefix else item
            lines.append(f"{indent}    <li>{content}</li>")
        lines.append(f"{indent}</ol>")
        return "\n".join(lines)

    lines = [f"{indent}<ul>"]
    for item in raw_items:
        lines.append(f"{indent}    <li>{item}</li>")
    lines.append(f"{indent}</ul>")
    return "\n".join(lines)


def convert_block_children(
    parent: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
    cols = None
) -> tuple[list[str], bool]:
    lines: list[str] = []
    has_real_content = False

    children = list(parent)
    i = 0
    while i < len(children):
        child = children[i]
        tag = local(child.tag)
        if tag in {"title", "label"}:
            i += 1
            continue
        if tag == "para":
            grouped_items: list[str] = []
            j = i
            while j < len(children) and local(children[j].tag) == "para":
                rendered = render_inline(children[j])
                stripped, had_circled = strip_circled_prefix(rendered)
                if not had_circled:
                    break
                if stripped:
                    grouped_items.append(stripped)
                j += 1

            if len(grouped_items) >= 2:
                cols_attr = f' cols="{cols}"' if cols else ""
                lines.append(f"{indent}<ol marker=\"(a)\"{cols_attr}>")
                for item in grouped_items:
                    lines.append(f"{indent}    <li>{item}</li>")
                lines.append(f"{indent}</ol>")
                has_real_content = True
                i = j
                continue

            lines.append(convert_para(child, indent))
            has_real_content = True
        elif tag == "list":
            lines.append(convert_list(child, indent, cols))
            has_real_content = True
        elif tag == "equation":
            lines.append(convert_equation(child, indent))
            has_real_content = True
        elif tag == "figure":
            lines.append(
                convert_figure(child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent)
            )
            has_real_content = True
        elif tag == "media":
            lines.append(
                convert_media(child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent)
            )
            has_real_content = True
        elif tag == "table":
            lines.append(convert_table(child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent))
            has_real_content = True
        elif tag == "note":
            lines.append(convert_note(child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent))
            has_real_content = True
        elif tag == "exercise":
            lines.append(
                convert_exercise(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent,
                    cols=cols
                )
            )
            has_real_content = True
        elif tag == "example":
            lines.append(
                convert_example(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent,
                )
            )
            has_real_content = True
        else:
            lines.append(f"{indent}<!-- TODO: unsupported element <{tag}> -->")

        i += 1

    return lines, has_real_content


def convert_equation(node: ET.Element, indent: str = "") -> str:
    math = node.find("m:math", NS)
    tex = normalize_tex_notation(mathml_to_tex(math))
    if (r"\\" in tex or "&" in tex) and not has_matrix_environment(tex):
        cases_tex = maybe_convert_cases(tex)
        if cases_tex:
            return f"{indent}<p><me>{cases_tex}</me></p>"
        rows = [r.strip() for r in tex.split(r"\\") if r.strip()]
        lines = [f"{indent}<p><md>"]
        for row in rows:
            escaped_row = row.replace('&', '&amp;')
            lines.append(f"{indent}    <mrow>{escaped_row}</mrow>")
        lines.append(f"{indent}</md></p>")
        return "\n".join(lines)
    return f"{indent}<p><me>{tex}</me></p>"


def convert_figure(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
) -> str:
    fid = scoped_id(node.attrib.get("id"), "figure")
    image = node.find("c:media/c:image", NS)
    caption = node.find("c:caption", NS)

    src = image.attrib.get("src", "") if image is not None else ""
    alt = node.find("c:media", NS).attrib.get("alt", "") if node.find("c:media", NS) is not None else ""
    mapped_src = (
        copy_image_to_assets(src, input_file, output_file, workspace_root, assets_subdir, copy_images)
        if src
        else ""
    )

    lines = [f"{indent}<figure {provenance_attrs(fid)}>"]
    if caption is not None:
        lines.append(f"{indent}    <caption>{render_inline(caption)}</caption>")
    elif alt:
        lines.append(f"{indent}    <caption>{clean_text(alt)}</caption>")
    else:
        lines.append(f"{indent}    <caption>Figure</caption>")
    lines.append(f"{indent}    <image source=\"{mapped_src}\" width=\"80%\"/>")
    lines.append(f"{indent}</figure>")
    return "\n".join(lines)


def convert_media(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
) -> str:
    mid = scoped_id(node.attrib.get("id"), "media")
    image = node.find("c:image", NS)
    src = image.attrib.get("src", "") if image is not None else ""
    alt = clean_text(node.attrib.get("alt", ""))
    mapped_src = (
        copy_image_to_assets(src, input_file, output_file, workspace_root, assets_subdir, copy_images)
        if src
        else ""
    )

    lines=[f"{indent}<image {provenance_attrs(mid, [f'source=\"{mapped_src}\"', 'width=\"80%\"'])}>"]
    lines.append(f"{indent} <description>")
    lines.append(f"{indent}     {alt}")
    lines.append(f"{indent} </description>")
    lines.append(f"{indent}</image>")
    return "\n".join(lines)


def convert_table(node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
    ) -> str:
    tid = scoped_id(node.attrib.get("id"), "table")
    lines = [f"{indent}<table {provenance_attrs(tid)}>", f"{indent}    <tabular>"]

    for row in node.findall("c:tgroup/c:tbody/c:row", NS):
        lines.append(f"{indent}        <row>")
        for entry in row.findall("c:entry", NS):
            content = render_inline(entry)
            for media in entry.findall("c:media", NS):
                converted = convert_media(
                    media,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "    ",
                )
                content += converted
            lines.append(f"{indent}            <cell>{content}</cell>")
        lines.append(f"{indent}        </row>")

    lines.append(f"{indent}    </tabular>")
    lines.append(f"{indent}</table>")
    return "\n".join(lines)


def convert_exercise(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
    title_override: str | None = None,
    cols = None
) -> str:
    xid = scoped_id(node.attrib.get("id"), "exercise")
    problem = node.find("c:problem", NS)
    solution = node.find("c:solution", NS)
    title = title_override
    if title is None and problem is not None:
        title = clean_text(problem.findtext("c:title", default="", namespaces=NS)) or None

    lines = [f"{indent}<exercise {provenance_attrs(xid)}>"]
    if title:
        lines.append(f"{indent}    <title>{title}</title>")

    lines.append(f"{indent}    <statement>")
    if problem is not None:
        problem_lines, has_problem = convert_block_children(
            problem, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "        ", cols
        )
        lines.extend(problem_lines)
        if not has_problem:
            lines.append(f"{indent}        <!-- TODO: problem pending conversion -->")
    else:
        lines.append(f"{indent}        <!-- TODO: problem pending conversion -->")
    lines.append(f"{indent}    </statement>")

    if solution is not None:
        lines.append(f"{indent}    <solution>")
        solution_lines, has_solution = convert_block_children(
            solution, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "        ", cols
        )
        lines.extend(solution_lines)
        if not has_solution:
            lines.append(f"{indent}        <!-- TODO: solution pending conversion -->")
        lines.append(f"{indent}    </solution>")

    lines.append(f"{indent}</exercise>")
    return "\n".join(lines)


def _unwrap_single_paragraph(xml_lines: list[str]) -> str | None:
    compact = "\n".join(line.strip() for line in xml_lines if line.strip())
    if not compact:
        return None
    match = re.fullmatch(r"<p>(.*)</p>", compact, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _inner_xml(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in list(element):
        parts.append(ET.tostring(child, encoding="unicode"))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def _extract_short_parts(xml_lines: list[str]) -> list[str] | None:
    compact = "\n".join(line.strip() for line in xml_lines if line.strip())
    if not compact:
        return None

    paragraph = _unwrap_single_paragraph(xml_lines)
    if paragraph is not None:
        return [paragraph]

    try:
        wrapper = ET.fromstring(f"<wrapper>{compact}</wrapper>")
    except ET.ParseError:
        return None

    children = list(wrapper)
    if len(children) != 1:
        return None

    first = children[0]
    if local(first.tag) != "ol":
        return None

    items: list[str] = []
    for li in list(first):
        if local(li.tag) != "li":
            return None
        items.append(_inner_xml(li))
    return items if items else None


def _short_exercise_parts(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    cols=None,
) -> tuple[list[str], list[str] | None] | None:
    problem = node.find("c:problem", NS)
    if problem is None:
        return None

    problem_lines, has_problem = convert_block_children(
        problem,
        input_file,
        output_file,
        workspace_root,
        assets_subdir,
        copy_images,
        "",
        cols,
    )
    if not has_problem:
        return None

    problem_items = _extract_short_parts(problem_lines)
    if not problem_items:
        return None

    solution = node.find("c:solution", NS)
    if solution is None:
        return problem_items, None

    solution_lines, has_solution = convert_block_children(
        solution,
        input_file,
        output_file,
        workspace_root,
        assets_subdir,
        copy_images,
        "",
        cols,
    )
    if not has_solution:
        return problem_items, None

    solution_items = _extract_short_parts(solution_lines)
    if not solution_items:
        return problem_items, None

    if len(solution_items) not in {1, len(problem_items)}:
        return None

    if len(solution_items) == 1 and len(problem_items) > 1:
        solution_items = solution_items + [""] * (len(problem_items) - 1)

    return problem_items, solution_items


def _convert_exercise_run(
    exercise_nodes: list[ET.Element],
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str,
    cols=None,
    wrap_container: bool = False,
) -> list[str]:
    if not exercise_nodes:
        return []

    lines: list[str] = []
    item_indent = indent
    if wrap_container:
        lines.append(f"{indent}<exercises>")
        item_indent = indent + "    "
    i = 0

    while i < len(exercise_nodes):
        short_group: list[tuple[ET.Element, list[str], list[str] | None]] = []
        j = i
        while j < len(exercise_nodes):
            parts = _short_exercise_parts(
                exercise_nodes[j],
                input_file,
                output_file,
                workspace_root,
                assets_subdir,
                copy_images,
                cols,
            )
            if parts is None:
                break
            if parts[1] is not None and len(parts[1]) != len(parts[0]):
                break
            short_group.append((exercise_nodes[j], parts[0], parts[1]))
            j += 1

        if len(short_group) >= 2:
            first_id = scoped_id(short_group[0][0].attrib.get("id"), "exercise")
            group_id = norm_id(f"{first_id}-parts", "exercise")
            cols_attr = f' cols="{cols}"' if cols else ""

            statement_items: list[str] = []
            solution_items: list[str] = []
            has_any_solution = False
            for _, statement_parts, maybe_solution_parts in short_group:
                statement_items.extend(statement_parts)
                if maybe_solution_parts is None:
                    solution_items.extend([""] * len(statement_parts))
                else:
                    has_any_solution = True
                    solution_items.extend(maybe_solution_parts)

            lines.append(f"{item_indent}<exercise {provenance_attrs(group_id)}>")
            lines.append(f"{item_indent}    <statement>")
            lines.append(f"{item_indent}        <ol marker=\"(a)\"{cols_attr}>")
            for statement_item in statement_items:
                lines.append(f"{item_indent}            <li>{statement_item}</li>")
            lines.append(f"{item_indent}        </ol>")
            lines.append(f"{item_indent}    </statement>")

            if has_any_solution:
                lines.append(f"{item_indent}    <solution>")
                lines.append(f"{item_indent}        <ol marker=\"(a)\"{cols_attr}>")
                for solution_item in solution_items:
                    lines.append(f"{item_indent}            <li>{solution_item}</li>")
                lines.append(f"{item_indent}        </ol>")
                lines.append(f"{item_indent}    </solution>")

            lines.append(f"{item_indent}</exercise>")
            i = j
            continue

        lines.append(
            convert_exercise(
                exercise_nodes[i],
                input_file,
                output_file,
                workspace_root,
                assets_subdir,
                copy_images,
                item_indent,
                cols=cols,
            )
        )
        i += 1

    if wrap_container:
        lines.append(f"{indent}</exercises>")
    return lines


def convert_example(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
) -> str:
    xid = scoped_id(node.attrib.get("id"), "example")
    nested_exercise = node.find("c:exercise", NS)
    if nested_exercise is not None:
        problem = nested_exercise.find("c:problem", NS)
        solution = nested_exercise.find("c:solution", NS)
        title = ""
        if problem is not None:
            title = clean_text(problem.findtext("c:title", default="", namespaces=NS))

        lines = [f"{indent}<example {provenance_attrs(xid)}>"]
        if title:
            lines.append(f"{indent}    <title>{title}</title>")
        lines.append(f"{indent}    <statement>")
        if problem is not None:
            problem_lines, has_problem = convert_block_children(
                problem, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "        "
            )
            lines.extend(problem_lines)
            if not has_problem:
                lines.append(f"{indent}        <!-- TODO: statement pending conversion -->")
        else:
            lines.append(f"{indent}        <!-- TODO: statement pending conversion -->")
        lines.append(f"{indent}    </statement>")
        if solution is not None:
            lines.append(f"{indent}    <solution>")
            solution_lines, has_solution = convert_block_children(
                solution, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "        "
            )
            lines.extend(solution_lines)
            if not has_solution:
                lines.append(f"{indent}        <!-- TODO: solution pending conversion -->")
            lines.append(f"{indent}    </solution>")
        lines.append(f"{indent}</example>")
        return "\n".join(lines)

    lines = [f"{indent}<example {provenance_attrs(xid)}>"]
    title = clean_text(node.findtext("c:title", default="", namespaces=NS))
    if title:
        lines.append(f"{indent}    <title>{title}</title>")
    body_lines, has_real_content = convert_block_children(
        node, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "    "
    )
    lines.extend(body_lines)
    if not has_real_content:
        lines.append(f"{indent}    <!-- TODO: example pending conversion -->")
    lines.append(f"{indent}</example>")
    return "\n".join(lines)


def extract_note_title_from_leading_emphasis(node: ET.Element) -> tuple[str | None, ET.Element]:
    note_copy = copy.deepcopy(node)

    for child in note_copy:
        if local(child.tag) != "para":
            continue

        if clean_text(child.text or ""):
            return None, note_copy

        para_children = list(child)
        if not para_children or local(para_children[0].tag) != "emphasis":
            return None, note_copy

        title = clean_text(render_inline(child))
        if not title:
            return None, note_copy

        note_copy.remove(child)
        return title, note_copy

    return None, note_copy


def convert_note(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
) -> str:
    nid = scoped_id(node.attrib.get("id"), "note")
    emphasized_title, content_node = extract_note_title_from_leading_emphasis(node)
    title = emphasized_title or clean_text(node.findtext("c:title", default="", namespaces=NS))
    label = clean_text(node.findtext("c:label", default="", namespaces=NS))
    nested_exercise = content_node.find("c:exercise", NS)
    if nested_exercise is not None:
        return convert_exercise(
            nested_exercise,
            input_file,
            output_file,
            workspace_root,
            assets_subdir,
            copy_images,
            indent,
            title_override=label or title,
        )

    lines = [f"{indent}<insight {provenance_attrs(nid)}>", f"{indent}    <title>{title}</title>"]
    has_real_content = False

    content_lines, has_real_content = convert_block_children(
        content_node, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "    "
    )
    lines.extend(content_lines)

    if not has_real_content:
        lines.append(f"{indent}    <!-- TODO: content pending conversion -->")

    lines.append(f"{indent}</insight>")
    return "\n".join(lines)

# Each section is its own <exercises> with a title
# If we are in the practice-perfect section, then if we see a <para> outside an exercise, the first will be the exercise group, the second in the intro. 

def convert_many_exercises(
    section_node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    indent: str = "",
) -> list[str]:
    section_title = clean_text(section_node.findtext("c:title", default="Exercises", namespaces=NS))
    children = [c for c in section_node if local(c.tag) != "title"]
    lines: list[str] = []

    intro_para_buffer: list[ET.Element] = []
    current_group_intro_paras: list[ET.Element] | None = None
    pending_exercises: list[ET.Element] = []

    def para_text(node: ET.Element) -> str:
        return clean_text("".join(node.itertext())).lower()

    def flush_group() -> None:
        nonlocal pending_exercises, current_group_intro_paras
        if not pending_exercises:
            return

        if current_group_intro_paras:
            lines.extend(
                render_exercisegroup_with_intro(
                    current_group_intro_paras,
                    pending_exercises,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent,
                    title=section_title,
                    cols=2,
                )
            )
        else:
            lines.extend(
                _convert_exercise_run(
                    pending_exercises,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent,
                    cols=2,
                    wrap_container=False,
                )
            )

        pending_exercises = []
        current_group_intro_paras = None

    for child in children:
        tag = local(child.tag)

        if tag == "para":
            flush_group()
            intro_para_buffer.append(child)
            if "following" in para_text(child):
                current_group_intro_paras = intro_para_buffer.copy()
                intro_para_buffer = []
            continue

        if tag == "exercise":
            pending_exercises.append(child)
            continue

        # Boundary: any non-para/non-exercise element ends an exercise run.
        flush_group()
        intro_para_buffer = []

    flush_group()
    return lines


def convert_section_exercises(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    tag_name: str = "section",
    indent: str = "",
    original_rel: str | None = None,
    license_name: str = "CC-BY-4.0",
) -> str:
    sid = scoped_id(node.attrib.get("id"), "section")
    title = clean_text(node.findtext("c:title", default="Exercises", namespaces=NS))
    lines = [f"{indent}<{tag_name} {provenance_attrs(sid)}>", f"{indent}    <title>{title}</title>"]

    inner_lines: list[str] = []
    children = [c for c in node if local(c.tag) != "title"]
    i = 0
    while i < len(children):
        child = children[i]
        tag = local(child.tag)
        if tag == "section":
            if local(child[0].tag) == "title" and child[0].text == "Self Check":
                i += 1
                continue
            inner_lines.extend(
                convert_many_exercises(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "        ",
                )
            )
            i += 1

        elif tag == "exercise":
            exercise_nodes: list[ET.Element] = []
            while i < len(children) and local(children[i].tag) == "exercise":
                exercise_nodes.append(children[i])
                i += 1
            inner_lines.extend(
                _convert_exercise_run(
                    exercise_nodes,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "        ",
                    cols=2,
                    wrap_container=False,
                )
            )
        elif tag == "para":
            inner_lines.append(convert_para(child, indent + "        "))
            i += 1
        else:
            inner_lines.append(f"{indent}        <!-- TODO: unsupported section-exercises element <{tag}> -->")
            i += 1

    if any("<exercise " in line for line in inner_lines):
        lines.append(f"{indent}    <exercises>")
        lines.extend(inner_lines)
        lines.append(f"{indent}    </exercises>")
    lines.append(f"{indent}</{tag_name}>")
    return "\n\n".join(lines)


def convert_section(
    node: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    tag_name: str = "section",
    max_children: int | None = None,
    indent: str = "",
    original_rel: str | None = None,
    license_name: str = "CC-BY-4.0",
) -> str:
    if has_class(node, "section-exercises"):
        return convert_section_exercises(
            node,
            input_file,
            output_file,
            workspace_root,
            assets_subdir,
            copy_images,
            tag_name,
            indent,
            original_rel,
            license_name,
        )

    def next_section_tag(current: str) -> str:
        if current == "section":
            return "subsection"
        if current == "subsection":
            return "subsubsection"
        return "subsubsection"

    sid = scoped_id(node.attrib.get("id"), "section")
    title = clean_text(node.findtext("c:title", default="Untitled", namespaces=NS))
    lines = [f"{indent}<{tag_name} {provenance_attrs(sid)}>", f"{indent}    <title>{title}</title>"]
    has_real_content = False

    children = [c for c in node if local(c.tag) != "title"]
    if max_children is not None:
        children = children[:max_children]

    i = 0
    while i < len(children):
        child = children[i]
        tag = local(child.tag)

        if tag == "exercise":
            exercise_nodes: list[ET.Element] = []
            while i < len(children) and local(children[i].tag) == "exercise":
                exercise_nodes.append(children[i])
                i += 1
            lines.extend(
                _convert_exercise_run(
                    exercise_nodes,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "    ",
                    wrap_container=True,
                )
            )
            has_real_content = True
            continue

        if tag == "para":
            lines.append(convert_para(child, indent + "    "))
            has_real_content = True
        elif tag == "list":
            lines.append(convert_list(child, indent + "    "))
            has_real_content = True
        elif tag == "figure":
            lines.append(
                convert_figure(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "    ",
                )
            )
            has_real_content = True
        elif tag == "media":
            lines.append(
                convert_media(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "    ",
                )
            )
            has_real_content = True
        elif tag == "table":
            lines.append(convert_table(child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    indent + "    "))
            has_real_content = True
        elif tag == "equation":
            lines.append(convert_equation(child, indent + "    "))
            has_real_content = True
        elif tag == "note":
            lines.append(
                convert_note(
                    child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "    "
                )
            )
            has_real_content = True
        elif tag == "example":
            lines.append(
                convert_example(
                    child, input_file, output_file, workspace_root, assets_subdir, copy_images, indent + "    "
                )
            )
            has_real_content = True
        elif tag == "section":
            lines.append(
                convert_section(
                    child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    tag_name=next_section_tag(tag_name),
                    max_children=None,
                    indent=indent + "    ",
                    original_rel=original_rel,
                    license_name=license_name,
                )
            )
            has_real_content = True
        else:
            lines.append(f"{indent}    <!-- TODO: unsupported element <{tag}> -->")

        i += 1

    if not has_real_content:
        lines.append(f"{indent}    <!-- TODO: content pending conversion -->")

    lines.append(f"{indent}</{tag_name}>")
    return "\n\n".join(lines)


def build_pretext_section(
    root: ET.Element,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
    max_content_nodes: int | None,
    max_first_section_nodes: int | None,
    section_id: str | None,
    include_attribution: bool,
    local_id_prefix: str | None = None,
    randomize_scoped_ids: bool = False,
    scoped_id_registry: ScopedIdRegistry | None = None,
    registry_target_file: Path | None = None,
) -> str:
    global CURRENT_ID_PREFIX, LOCAL_SOURCE_IDS, RANDOMIZE_SCOPED_IDS, SCOPED_ID_MAP, CURRENT_SOURCE_ORIGINAL, CURRENT_SOURCE_LICENSE
    global CURRENT_RESOURCE_CODE
    global CURRENT_TARGET_FILE, CURRENT_TARGET_SECTION_ID, CURRENT_TARGET_EXISTING_IDS, CURRENT_SCOPED_ID_REGISTRY
    md_title = root.findtext("c:metadata/md:title", default="", namespaces=NS)
    title = clean_text(md_title or root.findtext("c:title", default="Untitled", namespaces=NS))
    content_id = clean_text(root.findtext("c:metadata/md:content-id", default="", namespaces=NS))
    sec_id = norm_id(section_id or output_file.stem or content_id or title.lower().replace(" ", "-"), "section")
    CURRENT_ID_PREFIX = norm_id(local_id_prefix, "id") if local_id_prefix else sec_id
    LOCAL_SOURCE_IDS = {
        node.attrib["id"].strip()
        for node in root.iter()
        if node.attrib.get("id") and node.attrib["id"].strip()
    }
    RANDOMIZE_SCOPED_IDS = randomize_scoped_ids
    SCOPED_ID_MAP = {}
    original_rel = source_origin_path(input_file, workspace_root)
    license_name = "CC-BY-4.0"
    CURRENT_SOURCE_ORIGINAL = original_rel
    CURRENT_SOURCE_LICENSE = license_name
    CURRENT_RESOURCE_CODE = re.sub(r"[^A-Za-z0-9]+", "", (assets_subdir or "SRC").upper()) or "SRC"
    target_registry_file = registry_target_file or output_file
    CURRENT_TARGET_FILE = str(target_registry_file)
    CURRENT_TARGET_SECTION_ID = sec_id
    CURRENT_TARGET_EXISTING_IDS = _read_existing_target_ids(target_registry_file)
    CURRENT_SCOPED_ID_REGISTRY = scoped_id_registry

    lines = [
        f"<section {provenance_attrs(sec_id)}>",
        f"    <title>{title}</title>",
    ]

    lines.extend(["", "    <introduction>"])

    if include_attribution:
        lines.extend(
            [
                "        <convention>",
                f"            <p>This section <xref ref=\"{sec_id}\" text=\"title\"/> is adapted from module <c>{content_id or sec_id}</c> in <url href=\"https://openstax.org/details/books/precalculus-2e\">OpenStax Precalculus 2e</url>, used under <url href=\"https://creativecommons.org/licenses/by/4.0/deed.en\">CC BY 4.0</url>.</p>",
                "        </convention>",
            ]
        )

    content = root.find("c:content", NS)
    if content is not None:
        children = list(content)
        count = 0
        intro_closed = False
        intro_para_buffer: list[ET.Element] = []

        def para_text(node: ET.Element) -> str:
            return clean_text("".join(node.itertext())).lower()

        i = 0
        while i < len(children):
            if max_content_nodes is not None and count >= max_content_nodes:
                break
            child = children[i]
            tag = local(child.tag)
            if tag == "para":
                # If this paragraph stream introduces an exercise run (contains
                # "following" and is followed by exercises), emit an exercisegroup.
                para_nodes: list[ET.Element] = []
                j = i
                while j < len(children) and local(children[j].tag) == "para":
                    para_nodes.append(children[j])
                    j += 1

                if j < len(children) and local(children[j].tag) == "exercise" and any(
                    "following" in para_text(p) for p in para_nodes
                ):
                    if not intro_closed:
                        lines.append("    </introduction>")
                        intro_closed = True

                    intro_for_group = intro_para_buffer + para_nodes
                    intro_para_buffer = []

                    exercise_nodes: list[ET.Element] = []
                    k = j
                    while k < len(children) and local(children[k].tag) == "exercise":
                        exercise_nodes.append(children[k])
                        k += 1

                    lines.append(
                        "\n"
                        + "\n".join(
                            render_exercisegroup_with_intro(
                                intro_for_group,
                                exercise_nodes,
                                input_file,
                                output_file,
                                workspace_root,
                                assets_subdir,
                                copy_images,
                                "    ",
                                title=None,
                                cols=2,
                            )
                        )
                    )
                    i = k
                    count += len(para_nodes) + len(exercise_nodes)
                    continue

                block_indent = "        " if not intro_closed else "    "
                lines.append("\n" + convert_para(child, block_indent))
                if not intro_closed:
                    intro_para_buffer.append(child)
                else:
                    intro_para_buffer = []
                i += 1
            elif tag == "list":
                block_indent = "        " if not intro_closed else "    "
                lines.append("\n" + convert_list(child, block_indent))
                i += 1
            elif tag == "equation":
                block_indent = "        " if not intro_closed else "    "
                lines.append("\n" + convert_equation(child, block_indent))
                i += 1
            elif tag == "figure":
                block_indent = "        " if not intro_closed else "    "
                lines.append(
                    "\n"
                    + convert_figure(
                        child,
                        input_file,
                        output_file,
                        workspace_root,
                        assets_subdir,
                        copy_images,
                        block_indent,
                    )
                )
                i += 1
            elif tag == "media":
                block_indent = "        " if not intro_closed else "    "
                lines.append(
                    "\n"
                    + convert_media(
                        child,
                        input_file,
                        output_file,
                        workspace_root,
                        assets_subdir,
                        copy_images,
                        block_indent,
                    )
                )
                i += 1
            elif tag == "table":
                block_indent = "        " if not intro_closed else "    "
                lines.append("\n" + convert_table(child,
                    input_file,
                    output_file,
                    workspace_root,
                    assets_subdir,
                    copy_images,
                    block_indent))
                i += 1
            elif tag == "note":
                block_indent = "        " if not intro_closed else "    "
                lines.append(
                    "\n"
                    + convert_note(
                        child,
                        input_file,
                        output_file,
                        workspace_root,
                        assets_subdir,
                        copy_images,
                        block_indent,
                    )
                )
                i += 1
            elif tag == "exercise":
                intro_para_buffer = []
                block_indent = "        " if not intro_closed else "    "
                exercise_nodes: list[ET.Element] = []
                while i < len(children) and local(children[i].tag) == "exercise":
                    exercise_nodes.append(children[i])
                    i += 1
                lines.append(
                    "\n"
                    + "\n".join(
                        _convert_exercise_run(
                            exercise_nodes,
                            input_file,
                            output_file,
                            workspace_root,
                            assets_subdir,
                            copy_images,
                            block_indent,
                            cols=2,
                            wrap_container=True,
                        )
                    )
                )
                count += max(len(exercise_nodes) - 1, 0)
            elif tag == "example":
                intro_para_buffer = []
                block_indent = "        " if not intro_closed else "    "
                lines.append(
                    "\n"
                    + convert_example(
                        child,
                        input_file,
                        output_file,
                        workspace_root,
                        assets_subdir,
                        copy_images,
                        block_indent,
                    )
                )
                i += 1
            elif tag == "section":
                intro_para_buffer = []
                if not intro_closed:
                    lines.append("    </introduction>")
                    intro_closed = True
                lines.append(
                    "\n"
                    + convert_section(
                        child,
                        input_file,
                        output_file,
                        workspace_root,
                        assets_subdir,
                        copy_images,
                        "subsection",
                        max_first_section_nodes,
                        "    ",
                        original_rel,
                        license_name,
                    )
                )
                i += 1
            else:
                intro_para_buffer = []
                lines.append(f"\n        <!-- TODO: unsupported top-level element <{tag}> -->")
                i += 1
            count += 1

        if not intro_closed:
            lines.append("    </introduction>")
    else:
        lines.append("    </introduction>")

    lines.append("</section>")
    return "\n".join(lines) + "\n"


def infer_assets_subdir_from_input(input_file: Path) -> str:
    return input_file.resolve().parents[2].name


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototype CNXML -> PreTeXt converter")
    parser.add_argument("input", type=Path, help="Path to index.cnxml")
    parser.add_argument("output", type=Path, help="Path to output .ptx file")
    parser.add_argument("--workspace-root", type=Path, default=None, help="Workspace root (defaults to inferred project root)")
    parser.add_argument(
        "--assets-subdir",
        default=None,
        help="Subdirectory under assets/ for copied images (defaults to the module content root, e.g. PRECALC)",
    )
    parser.add_argument("--no-copy-images", action="store_true", help="Do not copy images into assets")
    parser.add_argument("--section-id", default=None, help="Override generated section xml:id")
    parser.add_argument("--no-attribution", action="store_true", help="Skip attribution convention at top")
    parser.add_argument("--max-content-nodes", type=int, default=None, help="Optional cap on top-level <content> nodes to convert")
    parser.add_argument("--max-first-section-nodes", type=int, default=None, help="Optional cap on first nested section children")
    args = parser.parse_args()

    tree = ET.parse(args.input)
    root = tree.getroot()

    workspace_root = args.workspace_root.resolve() if args.workspace_root else args.input.resolve().parents[3]
    assets_subdir = args.assets_subdir or infer_assets_subdir_from_input(args.input)

    out = build_pretext_section(
        root,
        args.input.resolve(),
        args.output.resolve(),
        workspace_root,
        assets_subdir,
        not args.no_copy_images,
        args.max_content_nodes,
        args.max_first_section_nodes,
        args.section_id,
        not args.no_attribution,
    )
    out = resolve_or_downgrade_xrefs(out)
    # Ensure there are no raw ampersands or raw angle operators in text content.
    out = escape_ampersands_in_xml(out)
    out = sanitize_angle_operators_outside_math(out)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(out, encoding="utf-8")

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
