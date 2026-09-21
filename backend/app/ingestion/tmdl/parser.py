"""Generic TMDL (Tabular Model Definition Language) tokenizer.

TMDL nests purely by indentation (one tab per level) and has one
non-obvious wrinkle: a multi-line expression is delimited by a line ending
in ` ``` ` and a following line that is just ` ``` ` — everything between is
literal text, not further indentation-parsed. Comments (`//`) and blank
lines are otherwise ignored.

This module only tokenizes structure (keyword + rest-of-line + children per
indentation) — it has no idea what a "table" or "measure" means. That
interpretation lives in tmdl_adapter.py, matching the ingestion/json split
between detector.py (shape) and powerbi_json_adapter.py (meaning).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_FENCE_OPEN_RE = re.compile(r"=\s*```\s*$")


@dataclass
class TmdlNode:
    indent: int
    keyword: str
    rest: str
    line_no: int
    children: list["TmdlNode"] = field(default_factory=list)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip("\t"))


def parse_tmdl(text: str) -> list[TmdlNode]:
    lines = text.splitlines()
    pos = 0
    n = len(lines)

    def parse_block(min_indent: int) -> list[TmdlNode]:
        nonlocal pos
        nodes: list[TmdlNode] = []
        while pos < n:
            raw = lines[pos]
            stripped = raw.strip()
            if not stripped or stripped.startswith("//"):
                pos += 1
                continue
            indent = _indent_of(raw)
            if indent < min_indent:
                break

            line_no = pos + 1
            pos += 1
            parts = stripped.split(None, 1)
            keyword = parts[0]
            rest = parts[1] if len(parts) > 1 else ""

            if _FENCE_OPEN_RE.search(rest):
                body_lines: list[str] = []
                while pos < n and lines[pos].strip() != "```":
                    body_lines.append(lines[pos].strip())
                    pos += 1
                if pos < n:
                    pos += 1  # consume the closing fence
                rest = _FENCE_OPEN_RE.sub("= " + "\n".join(body_lines), rest)

            node = TmdlNode(indent=indent, keyword=keyword, rest=rest, line_no=line_no)
            node.children = parse_block(indent + 1)
            nodes.append(node)
        return nodes

    return parse_block(0)


def find_all(nodes: list[TmdlNode], keyword: str) -> list[TmdlNode]:
    """Recursively finds every node with this keyword, at any depth —
    tolerant of both a single `model Model { table ... }`-wrapped export and
    a flatter per-table layout, since both are seen in the wild."""
    found: list[TmdlNode] = []
    for node in nodes:
        if node.keyword.lower() == keyword.lower():
            found.append(node)
        found.extend(find_all(node.children, keyword))
    return found


_NAME_EXPR_RE = re.compile(r"^(?:'([^']+)'|([^\s=]+))(?:\s*=\s*(.*))?$", re.S)


def parse_name_and_expression(rest: str) -> tuple[str, str | None]:
    """Header lines look like `Name` or `'Quoted Name'` or `Name = <DAX>` or
    `'Quoted Name' = <DAX>`. Returns (name, expression_or_None)."""
    m = _NAME_EXPR_RE.match(rest.strip())
    if not m:
        return rest.strip(), None
    name = m.group(1) or m.group(2)
    expr = m.group(3)
    return name, (expr.strip() if expr is not None else None)


def collect_properties(children: list[TmdlNode]) -> dict[str, str]:
    """Direct-child property lines are either `key: value` or a bare flag
    (e.g. `isHidden`, meaning true). Non-property children (annotation,
    variation, hierarchy, partition, ...) are silently ignored here — the
    adapter decides what to do with those keywords itself."""
    props: dict[str, str] = {}
    for child in children:
        if child.keyword.endswith(":"):
            props[child.keyword[:-1]] = child.rest.strip()
        elif not child.rest:
            props[child.keyword] = "true"
    return props


def split_table_column(value: str) -> tuple[str, str]:
    """`fromColumn`/`toColumn` values look like `Table.Column` or
    `'Table Name'.Column`."""
    value = value.strip()
    if value.startswith("'"):
        end = value.find("'", 1)
        if end == -1:
            return value, ""
        table = value[1:end]
        column = value[end + 1 :].lstrip(".")
        return table, column
    if "." in value:
        table, column = value.split(".", 1)
        return table, column
    return value, ""
