"""Databricks Unity Catalog Metric View YAML generation (spec sections 18/19),
adapted from the `pbi-unified` skill's build_view.py.

Builds one provisional Metric View spec per candidate fact table
(gold_design.detect_fact_groups), using the SQL translator's output for
measures and Power BI relationships for joins/dimensions. Since no
Teradata/Databricks connection exists yet, `source:` and join `source:`
values are placeholders (the Power BI table's snake_case name) rather than
real Unity Catalog three-part names — every spec is explicitly INFERRED,
per build_view.py's own "Mapping from PBI" table:
    Fact table                      -> source:
    Dimension + active relationship -> joins[]
    Column                          -> dimensions[].expr
    Measure (auto/auto_spot_check)  -> measures[].expr, with a `-- DAX:`
        provenance comment above the SQL (a spec requirement, not decoration)

`_invalid_measure_reason()` is ported near-verbatim: even a measure the
classifier scored AUTO can still be a PBI visual-layer pattern (SELECTEDVALUE,
a static string, unaggregated concatenation) that has no metric-view
equivalent, so it's excluded here with a reason rather than emitted as a
broken measure.
"""
from __future__ import annotations

import re

import yaml

from app.metadata.models import (
    MetricViewDimension,
    MetricViewExcludedMeasure,
    MetricViewJoin,
    MetricViewMeasure,
    MetricViewSpec,
    PowerBISemanticModel,
)
from app.parsers.dax.sql_translator import snake, translate_model
from app.recommendations.gold_design import detect_fact_groups

_SELECTEDVALUE_RE = re.compile(r"\bSELECTEDVALUE\s*\(", re.I)
_STATIC_STR_RE = re.compile(r"""^\s*(['"])[^'"]*\1\s*$""")
_YAML_INCLUDE_STATUSES = {"auto", "auto_spot_check"}


def _invalid_measure_reason(sql: str, original_dax: str) -> str | None:
    s = sql.strip()
    dax = (original_dax or "").strip()
    if _SELECTEDVALUE_RE.search(s) or _SELECTEDVALUE_RE.search(dax):
        return "SELECTEDVALUE is a DAX visual-layer function with no metric view equivalent"
    if _STATIC_STR_RE.match(s):
        return "Static string literal — not a metric/aggregation"
    if '"' in s and "&" in s and not re.search(r"\b(sum|count|avg|min|max|try_divide|MEASURE)\s*\(", s, re.I):
        return "String concatenation expression — Power BI report title text, not a measure"
    return None


def build_metric_view_specs(model: PowerBISemanticModel) -> list[MetricViewSpec]:
    facts, _dimensions = detect_fact_groups(model)
    if not facts:
        return []

    translations = {item.measure_name: item for item in translate_model(model)}
    tables_by_name = {t.name: t for t in model.tables}

    specs: list[MetricViewSpec] = []
    for fact in facts:
        fact_alias = "source"
        joined_aliases: dict[str, str] = {fact.table_name: fact_alias}
        joins: list[MetricViewJoin] = []

        for rel in model.relationships:
            if not rel.is_active or rel.from_table != fact.table_name or rel.to_table not in tables_by_name:
                continue
            alias = snake(rel.to_table)
            joined_aliases[rel.to_table] = alias
            joins.append(
                MetricViewJoin(
                    name=alias,
                    source=snake(rel.to_table),
                    on=f"{fact_alias}.{snake(rel.from_column)} = {alias}.{snake(rel.to_column)}",
                )
            )

        dimensions: list[MetricViewDimension] = []
        seen_names: set[str] = set()
        for table_name, alias in joined_aliases.items():
            table = tables_by_name.get(table_name)
            if table is None:
                continue
            for column in table.columns:
                if column.hidden or column.name in seen_names:
                    continue
                seen_names.add(column.name)
                dimensions.append(MetricViewDimension(name=column.name, expr=f"{alias}.{snake(column.name)}"))

        measures: list[MetricViewMeasure] = []
        excluded: list[MetricViewExcludedMeasure] = []
        for measure_name in fact.measures:
            item = translations.get(measure_name)
            if item is None:
                continue
            if item.status not in _YAML_INCLUDE_STATUSES:
                excluded.append(MetricViewExcludedMeasure(name=measure_name, reason=f"status={item.status}"))
                continue
            invalid_reason = _invalid_measure_reason(item.translated_sql, item.original_dax)
            if invalid_reason:
                excluded.append(MetricViewExcludedMeasure(name=measure_name, reason=invalid_reason))
                continue
            measures.append(
                MetricViewMeasure(name=measure_name, expr=f"-- DAX: {item.original_dax.strip()}\n{item.translated_sql}")
            )

        if not measures:
            continue  # nothing usable for this fact yet — don't emit an empty/useless spec

        specs.append(
            MetricViewSpec(
                fact_table=fact.table_name,
                source=snake(fact.table_name),
                source_note=(
                    "Placeholder — replace with the real Unity Catalog three-part name "
                    "(catalog.schema.table) once Bronze/Silver/Gold tables exist."
                ),
                joins=joins,
                dimensions=dimensions,
                measures=measures,
                excluded_measures=excluded,
            )
        )
    return specs


class _LiteralStr(str):
    pass


def _literal_representer(dumper: yaml.Dumper, data: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _literal_representer)


def render_yaml(spec: MetricViewSpec) -> str:
    doc = {
        "version": spec.version,
        "source": spec.source,
        "joins": [j.model_dump() for j in spec.joins],
        "dimensions": [d.model_dump() for d in spec.dimensions],
        "measures": [
            {"name": m.name, "expr": _LiteralStr(m.expr) if "\n" in m.expr else m.expr} for m in spec.measures
        ],
    }
    header = f"# {spec.source_note}\n"
    return header + yaml.dump(doc, sort_keys=False, width=100, allow_unicode=True)
