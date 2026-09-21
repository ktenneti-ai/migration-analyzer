"""DAX migration-complexity classification: a 0-100 confidence score plus an
A-F category per measure, adapted from the `pbi-unified` Claude Code skill's
`classify_score.py` / `dax_inventory.py` methodology (same function-name-set
+ regex-over-DAX-text approach we already use in dependency_parser.py, no
DAX AST required).

Unlike pbi-unified — which extracts table/measure references itself from
scratch — this reuses what dependency_parser.py already resolved
(measure.referenced_measures, measure.dependent_tables), since re-deriving
them here would just be a second, potentially inconsistent implementation
of the same regex matching.

Category legend (mirrors pbi-unified's CLAUDE.md):
    A = simple aggregation (score 90-100, no complex patterns)
    B = derived measure (references other measures, or IF/SWITCH/ISBLANK rewrites)
    C = time intelligence (SAMEPERIODLASTYEAR, DATESYTD, DATEADD, ...)
    D = filtered aggregate (CALCULATE with boolean/table/ALL filter args)
    E = semi-additive (LASTNONBLANK, CLOSINGBALANCEYEAR, ...)
    F = complex/untranslatable (RLS, EARLIER, dependency cycle, or score < 11)

Band legend (maps to the app's LOW/MEDIUM/HIGH complexity buckets):
    AUTO / AUTO_SPOT_CHECK -> LOW      (score >= 70)
    NEEDS_REVIEW           -> MEDIUM   (40 <= score < 70)
    MANUAL_PORT / UNSUPPORTED -> HIGH  (score < 40)
"""
from __future__ import annotations

import re

from app.metadata.models import MigrationGap, PowerBIMeasure, PowerBISemanticModel
from app.metadata.store import new_id

# --- Function-name sets (verbatim from pbi-unified/scripts/classify_score.py) ---

DIRECT = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNTROWS", "COUNT", "COUNTA", "DISTINCTCOUNT",
    "DISTINCTCOUNTNOBLANK", "DIVIDE", "BLANK", "ABS", "ROUND", "INT", "MOD", "SQRT", "EXP",
    "LN", "LOG", "POWER", "CONCATENATE", "LEFT", "RIGHT", "MID", "LEN", "UPPER", "LOWER",
    "TRIM", "SUBSTITUTE", "SEARCH", "FIND", "YEAR", "MONTH", "DAY", "HOUR", "MINUTE",
    "WEEKDAY", "EOMONTH", "TODAY", "NOW", "FORMAT", "TRUE", "FALSE", "AND", "OR", "NOT",
}
TIER2 = {
    "IF", "SWITCH", "ISBLANK", "COALESCE", "SELECTEDVALUE", "COUNTBLANK",
    "SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX", "VALUES", "HASONEVALUE", "CALCULATE",
}
TIME_INTEL = {
    "SAMEPERIODLASTYEAR", "DATESYTD", "DATESQTD", "DATESMTD", "DATEADD",
    "PARALLELPERIOD", "TOTALYTD", "TOTALQTD", "TOTALMTD", "DATESINPERIOD",
    "DATESBETWEEN", "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSYEAR", "PREVIOUSDAY",
    "NEXTMONTH", "NEXTQUARTER", "NEXTYEAR", "NEXTDAY", "FIRSTDATE", "LASTDATE",
    "STARTOFMONTH", "STARTOFQUARTER", "STARTOFYEAR", "ENDOFMONTH", "ENDOFQUARTER", "ENDOFYEAR",
}
SEMI_ADDITIVE = {
    "LASTNONBLANK", "LASTNONBLANKVALUE", "FIRSTNONBLANK", "FIRSTNONBLANKVALUE",
    "OPENINGBALANCEMONTH", "OPENINGBALANCEQUARTER", "OPENINGBALANCEYEAR",
    "CLOSINGBALANCEMONTH", "CLOSINGBALANCEQUARTER", "CLOSINGBALANCEYEAR",
}
REL_MOD = {"USERELATIONSHIP"}
VIRTUAL_REL = {"TREATAS", "CROSSFILTER"}
RLS_FUNCS = {"USERNAME", "USERPRINCIPALNAME", "CUSTOMDATA"}
RANKY = {"RANKX", "TOPN"}
EARLIER = {"EARLIER", "EARLIEST"}
KNOWN = (
    DIRECT | TIER2 | TIME_INTEL | SEMI_ADDITIVE | REL_MOD | VIRTUAL_REL | RLS_FUNCS | RANKY | EARLIER
    | {
        "ALL", "ALLEXCEPT", "ALLSELECTED", "REMOVEFILTERS", "KEEPFILTERS",
        "FILTER", "RELATED", "RELATEDTABLE", "LOOKUPVALUE", "VAR", "RETURN", "ADDCOLUMNS",
        "SUMMARIZE", "SUMMARIZECOLUMNS", "CROSSJOIN", "GENERATE", "DISTINCT", "CONCATENATEX",
        "ISFILTERED", "ISCROSSFILTERED", "SELECTEDMEASURE", "IN",
    }
)

BANDS = [(90, "AUTO"), (70, "AUTO_SPOT_CHECK"), (40, "NEEDS_REVIEW"), (11, "MANUAL_PORT"), (0, "UNSUPPORTED")]

_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


def split_args(s: str, open_paren_idx: int) -> tuple[list[str], int]:
    """Parenthesis-depth-aware argument splitter (ported from pbi-unified's
    _shared.py). Given a string and the index of an opening '(', returns
    (list_of_args, closing_paren_index). A naive comma-split breaks on
    nested calls like DIVIDE(SUM(x), COUNT(y))."""
    depth, cur, args, i = 0, [], [], open_paren_idx
    while i < len(s):
        ch = s[i]
        if ch in "({":
            depth += 1
            if depth > 1:
                cur.append(ch)
        elif ch in ")}":
            depth -= 1
            if depth == 0:
                if cur:
                    args.append("".join(cur))
                return args, i
            cur.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(cur))
            cur = []
        elif depth >= 1:
            cur.append(ch)
        i += 1
    if cur:
        args.append("".join(cur))
    return args, i


def _strip_strings_comments(dax: str) -> str:
    dax = re.sub(r"//[^\n]*|--[^\n]*", " ", dax)
    dax = re.sub(r"/\*.*?\*/", " ", dax, flags=re.S)
    return re.sub(r'"(?:[^"]|"")*"', '""', dax)


def _calculate_filter_kinds(s: str) -> set[str]:
    kinds: set[str] = set()
    for m in re.finditer(r"\bCALCULATE(?:TABLE)?\s*\(", s, re.I):
        args, _ = split_args(s, m.end() - 1)
        for arg in args[1:]:
            a = arg.strip()
            if re.match(r"^(ALL|ALLEXCEPT|REMOVEFILTERS)\s*\(", a, re.I):
                kinds.add("all_family")
            elif re.match(r"^KEEPFILTERS\s*\(", a, re.I):
                kinds.add("keepfilters")
            elif re.match(r"^(USERELATIONSHIP|CROSSFILTER|TREATAS)\s*\(", a, re.I):
                kinds.add("relationship_mod")
            elif re.match(r"^FILTER\s*\(", a, re.I):
                kinds.add("filter_table")
            elif re.search(r"\bIN\s*\{|=|<>|>=|<=|>|<", a):
                kinds.add("boolean")
            else:
                kinds.add("other")
    return kinds


def _iterator_over_virtual_table(s: str) -> bool:
    for m in re.finditer(r"\b(SUMX|AVERAGEX|MINX|MAXX|COUNTX|CONCATENATEX|RANKX)\s*\(", s, re.I):
        args, _ = split_args(s, m.end() - 1)
        if args and re.match(
            r"^\s*(FILTER|VALUES|ALL|ADDCOLUMNS|SUMMARIZE|CROSSJOIN|GENERATE|TOPN|DISTINCT)\s*\(",
            args[0],
            re.I,
        ):
            return True
    return False


def analyze_expression(dax: str) -> dict:
    """Everything score_one() needs that isn't already on the canonical
    PowerBIMeasure (functions used, VAR usage, CALCULATE filter shapes,
    iterator-over-virtual-table, BLANK/0 sensitivity)."""
    s = _strip_strings_comments(dax or "")
    return {
        "functions": {f.upper() for f in _FUNC_RE.findall(s)},
        "uses_var": bool(re.search(r"\bVAR\b", s, re.I)),
        "calculate_filter_kinds": _calculate_filter_kinds(s),
        "iterator_over_virtual_table": _iterator_over_virtual_table(s),
        "blank_zero_sensitive": bool(
            re.search(r"BLANK\s*\(\s*\)\s*(=|<>)|(=|<>)\s*0\b.*ISBLANK|ISBLANK.*(=|<>)", s, re.I)
        ),
    }


def band(score: int) -> str:
    for lo, name in BANDS:
        if score >= lo:
            return name
    return "UNSUPPORTED"


_BAND_TO_BUCKET = {
    "AUTO": "LOW",
    "AUTO_SPOT_CHECK": "LOW",
    "NEEDS_REVIEW": "MEDIUM",
    "MANUAL_PORT": "HIGH",
    "UNSUPPORTED": "HIGH",
}


def complexity_bucket(complexity_band: str) -> str:
    """Maps pbi-unified's 5-band scale onto the app's 3-bucket
    LOW/MEDIUM/HIGH complexity dashboard shape."""
    return _BAND_TO_BUCKET.get(complexity_band, "HIGH")


def classify_category(funcs: set[str], info: dict, score: int) -> str:
    if funcs & RLS_FUNCS or funcs & EARLIER or score < 11:
        return "F"
    if funcs & SEMI_ADDITIVE:
        return "E"
    if funcs & TIME_INTEL:
        return "C"
    if info["calculate_filter_kinds"]:
        return "D"
    if info.get("has_measure_refs") or (funcs & TIER2):
        return "B"
    return "A"


def score_one(info: dict, tables_touched: set[str], bidi_tables: set[str], m2m_tables: set[str]) -> tuple[int, list[str]]:
    funcs: set[str] = info["functions"]
    reasons: list[str] = []
    score = 100
    caps: list[tuple[int, str]] = []

    def ded(v: int, why: str) -> None:
        nonlocal score
        score -= v
        reasons.append(f"-{v}: {why}")

    def cap(v: int, why: str) -> None:
        caps.append((v, why))

    if funcs & RLS_FUNCS:
        cap(10, f"RLS-coupled function {sorted(funcs & RLS_FUNCS)} — UNSUPPORTED in view")
    if funcs & VIRTUAL_REL:
        cap(25, f"virtual relationship {sorted(funcs & VIRTUAL_REL)}")
    if funcs & REL_MOD:
        cap(30, "USERELATIONSHIP rewires join graph per-measure")
    if funcs & EARLIER:
        cap(25, "nested row context (EARLIER)")
    if funcs & TIME_INTEL:
        cap(35, f"time intelligence {sorted(funcs & TIME_INTEL)[:3]}")
    if funcs & SEMI_ADDITIVE:
        cap(35, "semi-additive — needs snapshot/window pattern")
    if "all_family" in info["calculate_filter_kinds"] or funcs & {"ALL", "ALLEXCEPT", "REMOVEFILTERS", "ALLSELECTED"}:
        cap(55, "ALL-family: total/window semantics not a plain aggregate")
    if tables_touched & bidi_tables:
        cap(45, "touches bi-directional relationship path")
    if tables_touched & m2m_tables:
        cap(45, "touches many-to-many relationship path")

    t2 = funcs & (TIER2 - {"CALCULATE"})
    if t2:
        ded(min(12 * len(t2), 36), f"pattern rewrites {sorted(t2)[:4]}")
    if "boolean" in info["calculate_filter_kinds"]:
        ded(15, "CALCULATE boolean filter -> FILTER clause")
    if "filter_table" in info["calculate_filter_kinds"]:
        ded(25, "CALCULATE with FILTER() table arg")
    if "keepfilters" in info["calculate_filter_kinds"]:
        ded(20, "KEEPFILTERS semantics")
    if "other" in info["calculate_filter_kinds"]:
        ded(20, "CALCULATE with unrecognized filter arg")
    if info["uses_var"]:
        ded(10, "VAR/RETURN needs inlining/decomposition")
    if info["iterator_over_virtual_table"]:
        ded(35, "iterator over virtual table -> CTE/pre-agg")
    if funcs & RANKY:
        ded(30, "RANKX/TOPN -> window logic, likely consumer-side")
    if "LOOKUPVALUE" in funcs:
        ded(25, "LOOKUPVALUE -> new explicit join")
    if info["blank_zero_sensitive"]:
        ded(10, "BLANK vs 0/NULL sensitive comparison")
    unknown = funcs - KNOWN
    if unknown:
        ded(min(30 * len(unknown), 60), f"uncataloged functions {sorted(unknown)[:4]}")

    score = max(score, 0)
    for v, why in caps:
        if score > v:
            score = v
            reasons.append(f"cap {v}: {why}")
    return score, reasons


def topo_order(deps: dict[str, list[str]]) -> tuple[list[str], list[list[str]]]:
    order: list[str] = []
    temp: set[str] = set()
    perm: set[str] = set()
    cycles: list[list[str]] = []

    def visit(n: str, stack: list[str]) -> None:
        if n in perm:
            return
        if n in temp:
            cycles.append(stack + [n])
            return
        temp.add(n)
        for d in deps.get(n, []):
            visit(d, stack + [n])
        temp.discard(n)
        perm.add(n)
        order.append(n)

    for n in deps:
        visit(n, [])
    return order, cycles


def _relationship_flags(model: PowerBISemanticModel) -> tuple[set[str], set[str]]:
    bidi: set[str] = set()
    m2m: set[str] = set()
    for rel in model.relationships:
        direction = (rel.cross_filter_direction or "").upper()
        cardinality = (rel.cardinality or "").upper()
        if "BOTH" in direction or "BIDIRECTIONAL" in direction:
            bidi.add(rel.from_table)
            bidi.add(rel.to_table)
        if "MANY_TO_MANY" in cardinality or "M2M" in cardinality:
            m2m.add(rel.from_table)
            m2m.add(rel.to_table)
    return bidi, m2m


def classify_measures(model: PowerBISemanticModel) -> None:
    """Mutates every measure's complexity_score/band/category/reasons and
    functions_used in place. Must run after dependency_parser.resolve_dependencies()
    (needs measure.referenced_measures and measure.dependent_tables)."""
    bidi_tables, m2m_tables = _relationship_flags(model)

    measures_by_name: dict[str, PowerBIMeasure] = {}
    home_table: dict[str, str] = {}
    for table in model.tables:
        for measure in table.measures:
            measures_by_name[measure.name] = measure
            home_table[measure.name] = table.name

    deps = {name: m.referenced_measures for name, m in measures_by_name.items()}
    order, cycles = topo_order(deps)

    scores: dict[str, int] = {}
    for name in order:
        measure = measures_by_name[name]
        info = analyze_expression(measure.expression)
        info["has_measure_refs"] = bool(measure.referenced_measures)
        tables_touched = set(measure.dependent_tables) | {home_table[name]}

        score, reasons = score_one(info, tables_touched, bidi_tables, m2m_tables)
        dep_scores = [scores[d] for d in measure.referenced_measures if d in scores]
        if dep_scores and min(dep_scores) < score:
            score = min(dep_scores)
            reasons.append(f"propagated from weakest dependency (score {score})")

        category = classify_category(info["functions"], info, score)
        scores[name] = score
        measure.functions_used = sorted(info["functions"])
        measure.complexity_score = score
        measure.complexity_band = band(score)
        measure.complexity_category = category
        measure.complexity_reasons = reasons

    for cycle in cycles:
        for name in cycle:
            measure = measures_by_name.get(name)
            if measure is None:
                continue
            scores[name] = 20
            measure.complexity_score = 20
            measure.complexity_band = "MANUAL_PORT"
            measure.complexity_category = "F"
            measure.complexity_reasons = measure.complexity_reasons + ["dependency cycle"]


def detect_relationship_model_gaps(model: PowerBISemanticModel) -> list[MigrationGap]:
    """Surfaces the HIGH-severity relationship features from pbi-unified's
    model-coverage.md as explicit MigrationGaps, one per affected table
    pair. Without this, a many-to-many or bi-directional relationship is
    only visible indirectly, as a capped measure score with a one-line
    reason (see classify_measures) — nothing tells the user a bridge-table
    or filter-path *design decision* is required before migration, which
    model-coverage.md's G5 gate calls for explicitly."""
    gaps: list[MigrationGap] = []
    seen: set[tuple[str, str, str]] = set()
    for rel in model.relationships:
        direction = (rel.cross_filter_direction or "").upper()
        cardinality = (rel.cardinality or "").upper()
        pair = tuple(sorted((rel.from_table, rel.to_table)))
        object_ref = f"Relationship:{rel.from_table} <-> {rel.to_table}"

        if "MANY_TO_MANY" in cardinality or "M2M" in cardinality:
            key = ("m2m", *pair)
            if key not in seen:
                seen.add(key)
                gaps.append(
                    MigrationGap(
                        id=new_id(),
                        object_ref=object_ref,
                        missing_information=(
                            f"Many-to-many relationship between '{rel.from_table}' and '{rel.to_table}'."
                        ),
                        why_it_matters=(
                            "Requires bridge-table design — fanout risk is even higher than a "
                            "bi-directional relationship (pbi-unified model-coverage.md)."
                        ),
                        migration_impact=(
                            "Measures touching this relationship path are capped at complexity "
                            "score 45 and routed to manual review."
                        ),
                        recommended_action=(
                            "Design a bridge table or dedicated aggregation views before migrating "
                            "affected measures."
                        ),
                    )
                )

        if "BOTH" in direction or "BIDIRECTIONAL" in direction:
            key = ("bidi", *pair)
            if key not in seen:
                seen.add(key)
                gaps.append(
                    MigrationGap(
                        id=new_id(),
                        object_ref=object_ref,
                        missing_information=(
                            f"Bi-directional relationship between '{rel.from_table}' and '{rel.to_table}'."
                        ),
                        why_it_matters=(
                            "Filter path ambiguity — dimension-side join keys must be "
                            "uniqueness-checked or fanout silently inflates measures "
                            "(pbi-unified model-coverage.md)."
                        ),
                        migration_impact=(
                            "Measures touching this relationship path are capped at complexity "
                            "score 45 and routed to manual review."
                        ),
                        recommended_action=(
                            "Redesign filter paths; consider a separate view per filter direction."
                        ),
                    )
                )
    return gaps
