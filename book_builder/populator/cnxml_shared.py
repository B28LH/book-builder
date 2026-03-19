"""Shared stateless CNXML-to-PreTeXt helpers.

This module contains pure utility and MathML/TeX helpers extracted from the
legacy converter so the main conversion script can stay focused on orchestration
and block-level structure conversion.
"""

from __future__ import annotations

import os
import re
import shutil
import lxml.etree as ET
from pathlib import Path


def local(tag: object) -> str:
    """Return local element name; ignore non-element lxml nodes."""
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def escape_ampersands_in_xml(s: str) -> str:
    """Escape raw ampersands that are not already part of an entity.

    Leaves common XML entities and numeric entities alone (e.g. &amp;, &lt;, &#123;).
    """
    return re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+|#x[0-9A-Fa-f]+)', '&amp;', s)


def sanitize_angle_operators_outside_math(xml: str) -> str:
    """Escape raw '<' and '>' in text outside math environments.

    This keeps markup intact and only sanitizes plain-text operators.
    """
    tag_pat = re.compile(r"<!--.*?-->|<\?.*?\?>|<![^>]*>|</?[A-Za-z_][\w:.-]*(?:\s+[^<>]*?)?/?>", re.DOTALL)
    math_tags = {"m", "me", "md", "mrow"}

    def update_math_depth(token: str, depth: int) -> int:
        stripped = token.strip()
        if not stripped.startswith("<"):
            return depth
        if stripped.startswith("<!--") or stripped.startswith("<?") or stripped.startswith("<!"):
            return depth

        m = re.match(r"<\s*(/)?\s*([A-Za-z_][\w:.-]*)", stripped)
        if not m:
            return depth

        closing = bool(m.group(1))
        name = m.group(2).split(":", 1)[-1]
        self_closing = stripped.endswith("/>")

        if name not in math_tags:
            return depth
        if closing:
            return max(0, depth - 1)
        if not self_closing:
            return depth + 1
        return depth

    out: list[str] = []
    i = 0
    math_depth = 0
    n = len(xml)

    while i < n:
        ch = xml[i]

        if ch == "<":
            match = tag_pat.match(xml, i)
            if match:
                token = match.group(0)
                out.append(token)
                math_depth = update_math_depth(token, math_depth)
                i = match.end()
                continue

            if math_depth == 0:
                out.append("&lt;")
            else:
                out.append("<")
            i += 1
            continue

        if ch == ">":
            if math_depth == 0:
                out.append("&gt;")
            else:
                out.append(">")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def resolve_or_downgrade_xrefs(out: str) -> str:
    """Replace unresolved <xref .../> with plain text to avoid build errors."""
    ids = set(re.findall(r'\bxml:id="([^"]+)"', out))

    xref_pat = re.compile(r'<xref\s+([^>]*?)ref="([^"]+)"([^>]*)/>')

    def _replace(match: re.Match[str]) -> str:
        ref = match.group(2)
        if ref in ids:
            return match.group(0)
        return f"<c>{ref}</c>"

    return xref_pat.sub(_replace, out)


def relpath_posix(target: Path, base: Path) -> str:
    return Path(os.path.relpath(target, base)).as_posix()


def source_origin_path(input_file: Path, workspace_root: Path) -> str:
    rel = relpath_posix(input_file, workspace_root)
    return rel.removeprefix("adapted-works/")


def copy_image_to_assets(
    src: str,
    input_file: Path,
    output_file: Path,
    workspace_root: Path,
    assets_subdir: str,
    copy_images: bool,
) -> str:
    """Resolve CNXML image source and rewrite it to project assets path."""
    source_abs = (input_file.parent / src).resolve()
    assets_dir = (workspace_root / "assets" / assets_subdir).resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    dest_abs = assets_dir / source_abs.name
    if copy_images and source_abs.exists() and source_abs != dest_abs:
        shutil.copy2(source_abs, dest_abs)

    return f"{assets_subdir}/{source_abs.name}"


def mathml_to_tex(node: ET.Element | None) -> str:
    if node is None:
        return ""

    tag = local(node.tag)

    if tag == "math":
        return "".join(mathml_to_tex(child) for child in node)

    if tag == "mrow":
        children = list(node)

        # Matrix/determinant encoded as mrow fences around an mtable, e.g.
        # [ mtable ] or | mtable | (common in OpenStax CNXML).
        if len(children) >= 3 and local(children[0].tag) == "mo" and local(children[-1].tag) == "mo":
            open_delim = (children[0].text or "").strip()
            close_delim = (children[-1].text or "").strip()
            middle = children[1:-1]

            # Be permissive: mtable may be direct or nested inside helper mrow wrappers.
            mtable_candidates = [n for n in middle if local(n.tag) == "mtable"]
            if not mtable_candidates:
                for n in middle:
                    mtable_candidates.extend([d for d in n.iter() if local(d.tag) == "mtable"])

            if len(mtable_candidates) == 1:
                body = mathml_to_tex(mtable_candidates[0])
                env_map = {
                    ("[", "]"): "bmatrix",
                    ("(", ")"): "pmatrix",
                    ("|", "|"): "vmatrix",
                    ("‖", "‖"): "Vmatrix",
                    ("{", "}"): "Bmatrix",
                }
                env = env_map.get((open_delim, close_delim), "matrix")
                return rf"\begin{{{env}}} {body} \end{{{env}}}"

        return "".join(mathml_to_tex(child) for child in node)

    if tag in {"mi", "mn"}:
        txt = (node.text or "").strip()
        if tag == "mi" and txt == "lim":
            return r"\lim"
        if tag == "mi" and txt == "ln":
            return r"\ln "
        if tag == "mi" and txt == "log":
            return r"\log "
        return txt

    if tag == "mtext":
        txt = clean_text(node.text or "")
        return f"\\text{{ {txt} }}" if txt else ""

    if tag == "mo":
        raw_txt = node.text or ""
        if raw_txt and raw_txt.isspace():
            return r"\ "
        txt = raw_txt.strip()
        fixes = {
            "−": "-",
            "–": "-",
            "×": r" \times ",
            "·": r" \cdot ",
            "≤": r" \le ",
            "≥": r" \ge ",
            "≠": r" \ne ",
            "→": r" \to ",
            "{": r"\{",
            "}": r"\}",
            "<": " &lt; ",
            ">": " &gt; ",
        }
        return "".join(fixes.get(char, char) for char in txt)

    if tag == "mspace":
        return ""

    if tag == "munder":
        children = list(node)
        if len(children) == 2:
            base = mathml_to_tex(children[0])
            under = mathml_to_tex(children[1])
            under = re.sub(r"\s*\\to\s*", r" \\to ", under)
            return f"{base}_{{{under}}}"

    if tag == "munderover":
        children = list(node)
        if len(children) == 3:
            base = mathml_to_tex(children[0])
            under = mathml_to_tex(children[1])
            over = mathml_to_tex(children[2])
            under = re.sub(r"\s*\\to\s*", r" \\to ", under)
            return f"{base}_{{{under}}}^{{{over}}}"

    if tag == "msup":
        children = list(node)
        if len(children) == 2:
            return f"{mathml_to_tex(children[0])}^{{{mathml_to_tex(children[1])}}}"

    if tag == "msub":
        children = list(node)
        if len(children) == 2:
            return f"{mathml_to_tex(children[0])}_{{{mathml_to_tex(children[1])}}}"

    if tag == "mfrac":
        children = list(node)
        if len(children) == 2:
            return f"\\frac{{{mathml_to_tex(children[0])}}}{{{mathml_to_tex(children[1])}}}"

    if tag == "msqrt":
        content = "".join(mathml_to_tex(child) for child in node)
        return f"\\sqrt{{{content}}}"

    if tag == "mroot":
        children = list(node)
        if len(children) == 2:
            radicand = mathml_to_tex(children[0])
            index = mathml_to_tex(children[1])
            return f"\\sqrt[{index}]{{{radicand}}}"

    if tag == "menclose":
        notation = node.attrib.get("notation", "")
        content = "".join(mathml_to_tex(child) for child in node)
        if notation == "updiagonalstrike":
            return f"\\cancel{{{content}}}"
        return content

    if tag == "mfenced":
        children = list(node)
        open_delim = node.attrib.get("open", "(")
        close_delim = node.attrib.get("close", ")")

        # Common MathML matrix form: <mfenced open="[" close="]"><mtable>...</mtable></mfenced>
        if len(children) == 1 and local(children[0].tag) == "mtable":
            body = mathml_to_tex(children[0])
            env_map = {
                ("[", "]"): "bmatrix",
                ("(", ")"): "pmatrix",
                ("|", "|"): "vmatrix",
                ("‖", "‖"): "Vmatrix",
                ("{", "}"): "Bmatrix",
            }
            env = env_map.get((open_delim, close_delim), "matrix")
            return rf"\begin{{{env}}} {body} \end{{{env}}}"

        content = "".join(mathml_to_tex(child) for child in children)
        left_map = {"{": r"\{", "}": r"\}", "|": "|", "‖": r"\|"}
        right_map = {"{": r"\{", "}": r"\}", "|": "|", "‖": r"\|"}
        left = left_map.get(open_delim, open_delim)
        right = right_map.get(close_delim, close_delim)
        return rf"\left{left}{content}\right{right}"

    if tag == "mtable":
        rows = []
        for row in node:
            if local(row.tag) == "mtr":
                rows.append(mathml_to_tex(row))
        return r" \\ ".join([r for r in rows if r])

    if tag == "mtr":
        cells = []
        for cell in node:
            if local(cell.tag) == "mtd":
                cells.append(mathml_to_tex(cell))
        return " & ".join([c for c in cells if c])

    if tag == "mtd":
        return "".join(mathml_to_tex(child) for child in node)

    return "".join(mathml_to_tex(child) for child in node)


def normalize_tex_notation(tex: str) -> str:
    """Normalize common plain-text math notations into cleaner TeX."""
    # Handle legacy forms like limh→0 or limh\to0.
    tex = re.sub(r"(?<!\\)lim\s*([A-Za-z])\s*→\s*([A-Za-z0-9.+\-]+)", r"\\lim_{\1 \\to \2}", tex)
    tex = re.sub(r"(?<!\\)lim\s*([A-Za-z])\s*\\to\s*([A-Za-z0-9.+\-]+)", r"\\lim_{\1 \\to \2}", tex)
    tex = re.sub(r"(?<!\\)\bln\b", r"\\ln", tex)
    tex = re.sub(r"(?<!\\)\blog\b", r"\\log", tex)
    tex = tex.replace(r"$", r"\$")
    return tex


def has_matrix_environment(tex: str) -> bool:
    return bool(re.search(r"\\begin\{(?:bmatrix|pmatrix|vmatrix|Vmatrix|Bmatrix|matrix)\}", tex))


def align_derivation_row(row: str, align_comments: bool) -> str:
    """Align equation rows for multi-line derivations.

    - Insert an alignment point before the first '=' when practical.
    - When explanatory text is present, place it in a third column via '&&'.
    """
    out = row.strip()

    if align_comments:
        out = re.sub(r"\s*&\s*(\\text\{)", r" && \1", out, count=1)

    if "&=" not in out:
        if out.startswith("="):
            out = "&" + out
        else:
            comment_col = out.find("&&")
            eq_slice = out if comment_col == -1 else out[:comment_col]
            eq_idx = eq_slice.find("=")
            if eq_idx != -1:
                out = out[:eq_idx] + "&=" + out[eq_idx + 1 :]

    return out


def maybe_convert_cases(tex: str) -> str | None:
    """Convert likely piecewise rows into a TeX cases environment."""
    rows = [r.strip() for r in tex.split(r"\\") if r.strip()]
    if len(rows) < 2:
        return None
    if not any("&" in row for row in rows):
        return None
    if not any(r"\text{if" in row or r"\text{ if" in row for row in rows):
        return None

    first = rows[0]
    brace_idx = first.find(r"\{")
    if brace_idx == -1:
        return None

    prefix = first[:brace_idx].strip()
    first_case = first[brace_idx + 2 :].strip()
    case_rows = [first_case] + rows[1:]
    case_rows[-1] = re.sub(r"\\}\s*$", "", case_rows[-1]).strip()
    case_rows = [row for row in case_rows if row]
    if len(case_rows) < 2:
        return None

    body = r" \\ ".join(case_rows)
    cases_tex = rf"\begin{{cases}} {body} \end{{cases}}"
    return f"{prefix}{cases_tex}" if prefix else cases_tex


def render_multiline_math(tex: str, indent: str = "") -> str:
    rows = [r.strip() for r in tex.split(r"\\") if r.strip()]
    align_comments = any(r"\text{" in row for row in rows)
    lines = [f"{indent}<p><md>"]
    for row in rows:
        aligned_row = align_derivation_row(row, align_comments)
        escaped_row = aligned_row.replace('&', '&amp;')
        lines.append(f"{indent}    <mrow>{escaped_row}</mrow>")
    lines.append(f"{indent}</md></p>")
    return "\n".join(lines)
