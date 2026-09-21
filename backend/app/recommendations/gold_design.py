"""Candidate Gold-layer fact/dimension inference from Power BI metadata alone
(spec section 18), adapted from the `pbi-unified` skill's translate.py
`detect_fact_group()` heuristic.

pbi-unified assigns each measure to a fact table using an externally-supplied
`table_map.json` (built from a live Unity Catalog profiling scan we don't
have). Since we have no Teradata/Databricks connection yet, this module
substitutes the only signal actually available at this stage: Power BI table
naming and DAX aggregation patterns. A table is treated as a "true fact"
candidate unless its name looks dimension-like (Dim*, D_*, Lookup*, Date,
Calendar — the same convention pbi-unified filters on). This gives real,
non-fabricated candidate facts/dimensions purely from ingested JSON, before
any Teradata or Databricks metadata exists — everything here is
status=INFERRED with explicit evidence, and grain is left REQUIRES_INPUT
since that needs a real key, which Power BI metadata doesn't expose.
"""
from __future__ import annotations

import re
from collections import Counter

from app.metadata.models import GoldDimensionCandidate, GoldFactCandidate, PowerBISemanticModel
from app.parsers.dax.classifier import topo_order

_DIM_PREFIXES = ("dim", "d_", "dimension", "lookup")
_DIM_EXACT = {"date", "calendar"}

_AGG_COL_RE = re.compile(
    r"\b(?:SUM|SUMX|AVERAGE|AVERAGEX|COUNT|COUNTA?|COUNTX|"
    r"DISTINCTCOUNT|DISTINCTCOUNTNOBLANK|MIN|MINX|MAX|MAXX)\s*\(\s*"
    r"(?:'([^']+)'|([A-Za-z_]\w*))\s*\[",
    re.I,
)
_COUNTROWS_RE = re.compile(r"\bCOUNTROWS\s*\(\s*(?:'([^']+)'|([A-Za-z_]\w*))\s*\)", re.I)


def _is_dim_like(table_name: str) -> bool:
    lowered = table_name.lower()
    if lowered in _DIM_EXACT:
        return True
    stripped = lowered.lstrip("-_ ")
    return any(stripped.startswith(p) for p in _DIM_PREFIXES)


def _detect_fact_group(
    dax: str, tables_referenced: list[str], home_table: str, true_fact_names: set[str], fact_names: set[str]
) -> tuple[str | None, str | None]:
    """Returns (fact_table_name, evidence_reason) or (None, None)."""
    if home_table in true_fact_names:
        return home_table, "measure's home table is not dimension-named"

    agg_tables: Counter[str] = Counter()
    for pattern in (_AGG_COL_RE, _COUNTROWS_RE):
        for m in pattern.finditer(dax):
            ref = (m.group(1) or m.group(2) or "").strip()
            if ref in true_fact_names:
                agg_tables[ref] += 2
            elif ref in fact_names:
                agg_tables[ref] += 1

    if agg_tables:
        best, count = agg_tables.most_common(1)[0]
        if best in true_fact_names:
            return best, f"most common SUM/COUNT/AVG aggregation target ({count} hit-weighted match(es))"
        true_fact_hits = [(t, c) for t, c in agg_tables.items() if t in true_fact_names]
        if true_fact_hits:
            best2 = max(true_fact_hits, key=lambda x: x[1])[0]
            return best2, "aggregation target among the true-fact candidates"
        return best, "only aggregation target found (dimension-named — low confidence)"

    for t in tables_referenced:
        if t in true_fact_names:
            return t, "only true-fact table referenced by this measure's columns"
    for t in tables_referenced:
        if t in fact_names:
            return t, "only table referenced by this measure's columns (dimension-named — low confidence)"
    return None, None


def detect_fact_groups(model: PowerBISemanticModel) -> tuple[list[GoldFactCandidate], list[GoldDimensionCandidate]]:
    fact_names = {t.name for t in model.tables}
    true_fact_names = {n for n in fact_names if not _is_dim_like(n)}
    home_table = {m.name: t.name for t in model.tables for m in t.measures}
    measures_by_name = {m.name: m for t in model.tables for m in t.measures}

    deps = {name: m.referenced_measures for name, m in measures_by_name.items()}
    order, _cycles = topo_order(deps)

    assignment: dict[str, str] = {}  # measure name -> fact table
    assignment_evidence: dict[str, str] = {}
    fact_measures: dict[str, list[str]] = {}
    fact_evidence: dict[str, set[str]] = {}

    for name in order:
        measure = measures_by_name[name]
        tables_referenced = list(measure.dependent_tables)
        fact, reason = _detect_fact_group(
            measure.expression, tables_referenced, home_table.get(name, ""), true_fact_names, fact_names
        )
        if fact is None:
            for dep in measure.referenced_measures:
                if dep in assignment:
                    fact = assignment[dep]
                    reason = f"inherited from referenced measure '{dep}'"
                    break
        if fact is None:
            continue
        assignment[name] = fact
        assignment_evidence[name] = reason or ""
        fact_measures.setdefault(fact, []).append(name)
        fact_evidence.setdefault(fact, set()).add(reason or "")

    facts = [
        GoldFactCandidate(
            table_name=table,
            evidence=sorted(e for e in fact_evidence[table] if e),
            measures=sorted(measures),
        )
        for table, measures in fact_measures.items()
    ]
    facts.sort(key=lambda f: f.table_name)

    fact_table_names = {f.table_name for f in facts}
    dim_evidence: dict[str, set[str]] = {}
    dim_related: dict[str, set[str]] = {}
    for rel in model.relationships:
        for dim_side, fact_side in ((rel.from_table, rel.to_table), (rel.to_table, rel.from_table)):
            if _is_dim_like(dim_side) and fact_side in fact_table_names:
                dim_related.setdefault(dim_side, set()).add(fact_side)
                dim_evidence.setdefault(dim_side, set()).add(
                    f"joined to candidate fact table '{fact_side}' via a Power BI relationship"
                )

    dimensions = [
        GoldDimensionCandidate(
            table_name=table,
            evidence=sorted(dim_evidence[table]),
            related_fact_tables=sorted(related),
        )
        for table, related in dim_related.items()
    ]
    dimensions.sort(key=lambda d: d.table_name)

    return facts, dimensions
