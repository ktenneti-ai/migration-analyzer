"""Tier-1/Tier-2 mechanical DAX -> Databricks SQL translation, adapted from
the `pbi-unified` skill's translate.py.

This is deliberately narrow, matching pbi-unified's own philosophy ("the
honest baseline + markers, not magic"):

- CALCULATE rewriting and iterator-over-virtual-table rewriting are NOT
  attempted — both require knowing the target view's join graph and source
  grain, which needs a real Gold-layer design and Teradata source data,
  neither of which exists yet. Translating DAX into SQL against tables that
  don't exist would be fabrication, so those measures are left NEEDS_REVIEW.
- IF/SWITCH are flagged (a note is added) but not mechanically rewritten to
  CASE WHEN — DAX's BLANK-coalescing semantics don't map 1:1 onto SQL NULL
  semantics for every IF shape, so a blind rewrite risks being silently
  wrong. A human completes it, same as pbi-unified's own translate.py does.

Dispatch is driven by the classifier's band (classifier.py):
    AUTO            -> full mechanical translation (DIRECT_MAP + DIVIDE +
                        column/measure reference normalization)
    AUTO_SPOT_CHECK -> the above, plus ISBLANK->IS NULL, plus notes for
                        IF/SWITCH/VAR that still need a human to finish
    NEEDS_REVIEW / MANUAL_PORT / UNSUPPORTED -> a stub naming the
        classifier's own reasons; no translation is attempted
"""
from __future__ import annotations

import re

from app.metadata.models import PowerBIMeasure, PowerBISemanticModel, SqlTranslationItem
from app.parsers.dax.classifier import analyze_expression, split_args, topo_order

# Mechanical, schema-independent substitutions only — functions whose
# Databricks equivalent needs semantic completion (INT, EOMONTH, CONVERT,
# CURRENCY, PATHITEM, ROUNDUP/ROUNDDOWN, SEARCH/FIND with differing arg
# order, ...) are deliberately excluded; a wrong mechanical guess there is
# worse than an honest NEEDS_REVIEW.
_DIRECT_MAP: list[tuple[str, str]] = [
    (r"\bDISTINCTCOUNTNOBLANK\s*\(", "count(distinct "),
    (r"\bDISTINCTCOUNT\s*\(", "count(distinct "),
    (r"\bCOUNTROWS\s*\(\s*(?:'[^']*'|[A-Za-z_]\w*)\s*\)", "count(*)"),
    (r"\bSUM\s*\(", "sum("),
    (r"\bAVERAGE\s*\(", "avg("),
    (r"\bMIN\s*\(", "min("),
    (r"\bMAX\s*\(", "max("),
    (r"\bCOUNTA?\s*\(", "count("),
    (r"\bBLANK\s*\(\s*\)", "NULL"),
    (r"\bTODAY\s*\(\s*\)", "current_date()"),
    (r"\bNOW\s*\(\s*\)", "current_timestamp()"),
    (r"\bYEAR\s*\(", "year("),
    (r"\bMONTH\s*\(", "month("),
    (r"\bDAY\s*\(", "day("),
    (r"\bLEN\s*\(", "length("),
    (r"\bUPPER\s*\(", "upper("),
    (r"\bLOWER\s*\(", "lower("),
    (r"\bTRIM\s*\(", "trim("),
    (r"\bABS\s*\(", "abs("),
    (r"\bROUND\s*\(", "round("),
    (r"\bSQRT\s*\(", "sqrt("),
]

_QUALIFIED_REF = re.compile(r"(?:'([^']+)'|(\w+))\[([^\]]+)\]")
_BARE_REF = re.compile(r"\[([^\]]+)\]")

_TRANSLATABLE_STATUSES = {"auto", "auto_spot_check"}


def snake(s: str) -> str:
    """PascalCase/camelCase/arbitrary Power BI names -> snake_case (ported
    verbatim from pbi-unified's _shared.py — Unity Catalog columns are
    conventionally snake_case, and a naive lowercase-only pass would turn
    'OrderID' into 'orderid', which won't match a real 'order_id' column)."""
    s = (s or "").strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"\W+", "_", s.lower())
    return s.strip("_")


def _rewrite_divide(s: str) -> str:
    """DIVIDE(num, denom[, alt]) -> try_divide(...), matching DAX's
    BLANK-on-zero-denominator semantics (not NULLIF, which differs)."""
    while True:
        m = re.search(r"\bDIVIDE\s*\(", s, re.I)
        if not m:
            return s
        args, end = split_args(s, m.end() - 1)
        if len(args) >= 3:
            repl = f"coalesce(try_divide({args[0].strip()}, {args[1].strip()}), {args[2].strip()})"
        elif len(args) >= 2:
            repl = f"try_divide({args[0].strip()}, {args[1].strip()})"
        else:
            return s
        s = s[: m.start()] + repl + s[end + 1 :]


def _apply_direct_map(s: str) -> str:
    for pattern, replacement in _DIRECT_MAP:
        s = re.sub(pattern, replacement, s, flags=re.I)
    return s


def _normalize_column_refs(s: str) -> str:
    def repl(m: re.Match) -> str:
        table = (m.group(1) or m.group(2) or "").strip()
        col = m.group(3).strip()
        return f"{snake(table)}.{snake(col)}"

    return _QUALIFIED_REF.sub(repl, s)


def _resolve_bare_refs(
    s: str, measure: PowerBIMeasure, home_table: str, statuses: dict[str, str], notes: list[str]
) -> tuple[str, bool]:
    """Replaces bare [Name] refs with MEASURE(`Name`) (if that dependency
    translated cleanly) or `home_table_col`.column (if it's a same-table
    column, per dependency_parser's bare-name resolution). Returns
    (new_sql, had_unresolved_reference)."""
    had_unresolved = False
    bare_columns = {
        col: f"{snake(table)}.{snake(col)}"
        for rc in measure.referenced_columns
        for table, _, col in [rc.partition(".")]
        if table == home_table
    }

    def repl(m: re.Match) -> str:
        nonlocal had_unresolved
        name = m.group(1)
        if name in measure.referenced_measures:
            dep_status = statuses.get(name)
            if dep_status in _TRANSLATABLE_STATUSES:
                return f"MEASURE(`{name}`)"
            had_unresolved = True
            notes.append(
                f"unresolved measure ref [{name}] (dependency status: {dep_status or 'unclassified'}) — resolve manually"
            )
            return m.group(0)
        if name in bare_columns:
            return bare_columns[name]
        had_unresolved = True
        notes.append(f"unresolved reference [{name}] — could not be validated against known measures/columns")
        return m.group(0)

    return _BARE_REF.sub(repl, s), had_unresolved


def _t1(dax: str) -> str:
    s = _rewrite_divide(dax)
    s = _apply_direct_map(s)
    s = _normalize_column_refs(s)
    return s.strip()


def _t2_transform(dax: str, notes: list[str]) -> str:
    s = re.sub(r"\bISBLANK\s*\(([^()]+)\)", r"(\1 IS NULL)", dax, flags=re.I)
    if re.search(r"\bIF\s*\(", s, re.I):
        notes.append("IF -> CASE WHEN: needs manual rewrite; verify ELSE NULL semantics")
    if re.search(r"\bSWITCH\s*\(", s, re.I):
        notes.append("SWITCH -> CASE: needs manual rewrite")
    return s


def translate_model(model: PowerBISemanticModel) -> list[SqlTranslationItem]:
    measures_by_name: dict[str, PowerBIMeasure] = {}
    home_table: dict[str, str] = {}
    for table in model.tables:
        for measure in table.measures:
            measures_by_name[measure.name] = measure
            home_table[measure.name] = table.name

    deps = {name: m.referenced_measures for name, m in measures_by_name.items()}
    order, _cycles = topo_order(deps)

    statuses: dict[str, str] = {}
    items: dict[str, SqlTranslationItem] = {}

    for name in order:
        measure = measures_by_name[name]
        band = measure.complexity_band
        notes: list[str] = []

        if band == "AUTO":
            sql, had_unresolved = _resolve_bare_refs(_t1(measure.expression), measure, home_table[name], statuses, notes)
            status = "needs_review" if had_unresolved else "auto"
        elif band == "AUTO_SPOT_CHECK":
            transformed = _t2_transform(measure.expression, notes)
            sql, had_unresolved = _resolve_bare_refs(_t1(transformed), measure, home_table[name], statuses, notes)
            if analyze_expression(measure.expression)["uses_var"]:
                notes.append("VAR/RETURN -> inline subexpressions or decompose into helper measures")
            status = "needs_review" if had_unresolved else "auto_spot_check"
        else:
            reasons = "; ".join(measure.complexity_reasons) or "complex DAX pattern"
            sql = f"-- {band}: manual conversion required ({reasons})"
            status = band.lower()

        statuses[name] = status
        items[name] = SqlTranslationItem(
            measure_name=name,
            table_name=home_table[name],
            original_dax=measure.expression,
            translated_sql=sql,
            status=status,
            complexity_category=measure.complexity_category,
            complexity_score=measure.complexity_score,
            notes=notes,
        )

    return sorted(items.values(), key=lambda i: (i.table_name, i.measure_name))
