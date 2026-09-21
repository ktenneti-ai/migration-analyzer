"""Wrapper-view SQL generation (spec section 21/"complex functions"),
adapted from the `pbi-unified` skill's build_wrapper.py.

Wrapper views sit on top of a Metric View and use window functions / LAG /
RANK for measures a Metric View expr cannot contain (time intelligence,
ratio-of-total, ranking, YoY/MoM change) — see
pbi-unified/references/complex-functions.md.

The fork's original guidance deferred this ("requires a resolved date
dimension") but a date dimension is now derivable honestly from Power BI
metadata alone: an active relationship from the candidate fact to a
dimension-named table with recognizable year/month/quarter/date columns.
Where no such dimension exists (or a measure's base isn't itself
translatable), the measure is reported as skipped with a specific reason —
never silently dropped or guessed at.
"""
from __future__ import annotations

import re

from app.metadata.models import (
    PowerBISemanticModel,
    WrapperViewMeasure,
    WrapperViewSkippedMeasure,
    WrapperViewSpec,
)
from app.parsers.dax.sql_translator import snake, translate_model
from app.recommendations.gold_design import detect_fact_groups

# --- Pattern detection (ported from build_wrapper.py) ---

_SPLY_RE = re.compile(r"\bSAMEPERIODLASTYEAR\s*\(", re.I)
_DATEADD_RE = re.compile(r"\bDATEADD\s*\(", re.I)
_PARALLEL_RE = re.compile(r"\bPARALLELPERIOD\s*\(", re.I)
_YTD_RE = re.compile(r"\b(TOTALYTD|DATESYTD)\s*\(", re.I)
_QTD_RE = re.compile(r"\b(TOTALQTD|DATESQTD)\s*\(", re.I)
_MTD_RE = re.compile(r"\b(TOTALMTD|DATESMTD)\s*\(", re.I)
_ALL_RE = re.compile(r"\b(ALL|ALLEXCEPT|REMOVEFILTERS|ALLSELECTED)\s*\(", re.I)
_RANKX_RE = re.compile(r"\bRANKX\s*\(", re.I)
_ROLLING_RE = re.compile(r"\bDATESINPERIOD\s*\(", re.I)
_CALCULATE_RE = re.compile(r"\bCALCULATE\s*\(", re.I)
_MEASURE_REF_RE = re.compile(r"\[([^\]]+)\]")

_DATE_KEYWORDS = ("date", "calendar", "time", "period")
_TRANSLATABLE_STATUSES = {"auto", "auto_spot_check"}


def _classify_wrapper_pattern(dax: str) -> tuple[str | None, str | None]:
    if _SPLY_RE.search(dax):
        return "prior_period", "year"
    if _DATEADD_RE.search(dax):
        m = re.search(r"DATEADD\s*\([^,]*,\s*(-?\d+)\s*,\s*(\w+)", dax, re.I)
        if m:
            offset, unit = int(m.group(1)), m.group(2).upper()
            return "prior_period", f"{abs(offset)}_{unit.lower()}"
        return "prior_period", "custom"
    if _PARALLEL_RE.search(dax):
        return "prior_period", "parallel"
    if _YTD_RE.search(dax):
        return "to_date", "ytd"
    if _QTD_RE.search(dax):
        return "to_date", "qtd"
    if _MTD_RE.search(dax):
        return "to_date", "mtd"
    if _RANKX_RE.search(dax):
        return "rank", "dense"
    if _ROLLING_RE.search(dax):
        return "rolling", "period"
    if _ALL_RE.search(dax) and _CALCULATE_RE.search(dax):
        return "ratio_of_total", "all"
    return None, None


def _find_date_dim(model: PowerBISemanticModel, fact_table_name: str) -> dict | None:
    tables_by_name = {t.name: t for t in model.tables}
    for rel in model.relationships:
        if not rel.is_active or rel.from_table != fact_table_name:
            continue
        dim_name = rel.to_table
        normalized = dim_name.lower().replace("-", "").replace("_", "").replace(" ", "")
        if not any(kw in normalized for kw in _DATE_KEYWORDS):
            continue
        table = tables_by_name.get(dim_name)
        if table is None:
            continue

        visible_cols = [c.name for c in table.columns if not c.hidden]

        def find_col(pattern: str) -> str | None:
            for c in visible_cols:
                if re.match(pattern, snake(c), re.I):
                    return snake(c)
            return None

        return {
            "table": dim_name,
            "alias": snake(dim_name),
            "year": find_col(r"(calendar|fiscal)?_?year$"),
            "month": find_col(r"(calendar|fiscal)?_?month(_?number)?$"),
            "quarter": find_col(r"(calendar|fiscal)?_?quarter$"),
            "date": find_col(r"(full_?date|date_?key|date)$"),
        }
    return None


def _find_base_measure(dax: str, translations: dict) -> str | None:
    for ref in _MEASURE_REF_RE.findall(dax):
        item = translations.get(ref)
        if item and item.status in _TRANSLATABLE_STATUSES:
            return ref
    return None


def _gen_prior_period_sql(name: str, base: str, date_info: dict | None, sub_type: str) -> str | None:
    if not date_info or not date_info["date"]:
        return None
    date_col = f"{date_info['alias']}.{date_info['date']}"
    offset = 12
    if sub_type != "year":
        digits = sub_type.split("_")[0]
        offset = int(digits) if digits.isdigit() else 1
    return f"  LAG(MEASURE(`{base}`), {offset}) OVER (\n    ORDER BY {date_col}\n  ) AS `{name}`"


def _gen_to_date_sql(name: str, base: str, date_info: dict | None, sub_type: str) -> str | None:
    if not date_info or not date_info["date"]:
        return None
    d = date_info["alias"]
    date_col = f"{d}.{date_info['date']}"
    if sub_type == "ytd" and date_info["year"]:
        part_col = f"{d}.{date_info['year']}"
    elif sub_type == "qtd" and date_info["quarter"] and date_info["year"]:
        part_col = f"{d}.{date_info['year']}, {d}.{date_info['quarter']}"
    elif sub_type == "mtd" and date_info["month"] and date_info["year"]:
        part_col = f"{d}.{date_info['year']}, {d}.{date_info['month']}"
    else:
        return None
    return (
        f"  SUM(MEASURE(`{base}`)) OVER (\n"
        f"    PARTITION BY {part_col}\n"
        f"    ORDER BY {date_col}\n"
        f"    ROWS UNBOUNDED PRECEDING\n"
        f"  ) AS `{name}`"
    )


def _gen_ratio_sql(name: str, base: str, _date_info: dict | None, _sub_type: str) -> str:
    return f"  try_divide(\n    MEASURE(`{base}`),\n    SUM(MEASURE(`{base}`)) OVER ()\n  ) AS `{name}`"


def _gen_rank_sql(name: str, base: str, _date_info: dict | None, _sub_type: str) -> str:
    return f"  DENSE_RANK() OVER (\n    ORDER BY MEASURE(`{base}`) DESC\n  ) AS `{name}`"


def _gen_yoy_change_sql(name: str, base: str, prior_name: str, dax: str) -> str:
    if re.search(r"DIVIDE|%", dax, re.I):
        return f"  try_divide(\n    `{base}` - `{prior_name}`,\n    `{prior_name}`\n  ) AS `{name}`"
    return f"  `{base}` - `{prior_name}` AS `{name}`"


_GENERATORS = {
    "prior_period": _gen_prior_period_sql,
    "to_date": _gen_to_date_sql,
    "ratio_of_total": _gen_ratio_sql,
    "rank": _gen_rank_sql,
}

_NEEDS_DATE_DIM_HINT = {
    "prior_period": "no date dimension joined to this fact table with a recognizable date column",
    "to_date": "no date dimension joined to this fact table with the year/quarter/month columns this pattern needs",
}


def build_wrapper_views(model: PowerBISemanticModel) -> list[WrapperViewSpec]:
    facts, _dimensions = detect_fact_groups(model)
    if not facts:
        return []

    translations = {item.measure_name: item for item in translate_model(model)}
    specs: list[WrapperViewSpec] = []

    for fact in facts:
        date_info = _find_date_dim(model, fact.table_name)
        wrapper_columns: list[str] = []
        wrapped: list[WrapperViewMeasure] = []
        skipped: list[WrapperViewSkippedMeasure] = []
        group_by_dims: set[str] = set()
        prior_period_map: dict[str, str] = {}

        for measure_name in fact.measures:
            item = translations.get(measure_name)
            if item is None or item.status in _TRANSLATABLE_STATUSES:
                continue  # already usable in the metric view — no wrapper needed

            pattern, sub_type = _classify_wrapper_pattern(item.original_dax)
            if not pattern:
                continue  # not a recognized wrappable pattern; already covered by the classifier's own reasons

            base = _find_base_measure(item.original_dax, translations)
            if not base:
                skipped.append(
                    WrapperViewSkippedMeasure(
                        name=measure_name,
                        pattern=pattern,
                        reason="no base measure found among this model's auto/auto_spot_check measures",
                    )
                )
                continue

            gen_fn = _GENERATORS.get(pattern)
            col_sql = gen_fn(measure_name, base, date_info, sub_type) if gen_fn else None
            if not col_sql:
                skipped.append(
                    WrapperViewSkippedMeasure(
                        name=measure_name,
                        pattern=pattern,
                        reason=_NEEDS_DATE_DIM_HINT.get(pattern, f"'{pattern}' wrapper generation not supported"),
                    )
                )
                continue

            wrapper_columns.append(col_sql)
            wrapped.append(
                WrapperViewMeasure(name=measure_name, pattern=pattern, sub_type=sub_type, base_measure=base, sql_column=col_sql.strip())
            )
            if pattern == "prior_period":
                prior_period_map[measure_name] = base
            if date_info:
                for key in ("date", "year", "month", "quarter"):
                    if date_info.get(key):
                        group_by_dims.add(f"{date_info['alias']}.{date_info[key]}")

        # Second pass: YoY/MoM change measures that reference a prior-period wrapper.
        wrapped_names = {w.name for w in wrapped}
        for measure_name in fact.measures:
            if measure_name in wrapped_names:
                continue
            item = translations.get(measure_name)
            if item is None or item.status in _TRANSLATABLE_STATUSES:
                continue
            dax = item.original_dax
            prior_ref = base_ref = None
            for ref in _MEASURE_REF_RE.findall(dax):
                if ref in prior_period_map:
                    prior_ref = ref
                    base_ref = prior_period_map[ref]
                elif ref in translations and translations[ref].status in _TRANSLATABLE_STATUSES:
                    base_ref = base_ref or ref
            if prior_ref and base_ref and re.search(r"DIVIDE|change|growth|%|yoy|mom", dax + measure_name, re.I):
                change_sql = _gen_yoy_change_sql(measure_name, base_ref, prior_ref, dax)
                wrapper_columns.append(change_sql)
                wrapped.append(
                    WrapperViewMeasure(name=measure_name, pattern="yoy_change", sub_type="derived", base_measure=base_ref, sql_column=change_sql.strip())
                )

        if not wrapper_columns and not skipped:
            continue  # nothing wrappable and nothing to explain either — skip silently

        dims = sorted(group_by_dims)
        if wrapper_columns:
            base_measures_used = sorted({w.base_measure for w in wrapped if w.base_measure})
            base_cols = [f"  MEASURE(`{b}`) AS `{b}`" for b in base_measures_used]
            cols_block = ",\n".join(base_cols + wrapper_columns)
            view_name = f"{snake(fact.table_name)}_wrapper"
            source_view = f"metric_view_{snake(fact.table_name)}"
            sql = (
                "-- Wrapper view for measures that need window functions / LAG / RANK.\n"
                "-- Sits on top of the metric view and adds time intelligence, ratio-of-total,\n"
                "-- ranking, and derived change measures.\n"
                "-- REVIEW: verify date dimension columns and GROUP BY grain.\n\n"
                f"CREATE OR REPLACE VIEW {view_name} AS\n"
                "SELECT\n"
                + (f"  {', '.join(dims)},\n" if dims else "")
                + f"{cols_block}\n"
                f"FROM {source_view}\n"
                + (f"GROUP BY {', '.join(dims)};\n" if dims else "GROUP BY ALL;\n")
            )
        else:
            sql = "-- No wrapper view could be generated — see skipped_measures for why."

        specs.append(
            WrapperViewSpec(
                fact_table=fact.table_name,
                date_dimension=date_info["table"] if date_info else None,
                group_by=dims,
                wrapped_measures=wrapped,
                skipped_measures=skipped,
                sql=sql,
            )
        )

    return specs
