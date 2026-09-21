"""DAX dependency extraction (bracket-based, not a full DAX grammar).

Milestone 1 scope: find measure/column references inside a DAX expression
well enough to build the measure -> measure / measure -> column lineage
graph, and flag references that don't resolve to a known object as
migration gaps. A full DAX AST (tokenizer for CALCULATE/FILTER/etc. per
spec section 6) is a later milestone; this module is deliberately narrow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.metadata.models import MigrationGap, PowerBIMeasure, PowerBISemanticModel, Status
from app.metadata.store import new_id

_QUALIFIED_REF = re.compile(r"(?:'([^']+)'|(\w+))\[([^\]]+)\]")


@dataclass
class ParsedReferences:
    bare_names: list[str] = field(default_factory=list)  # e.g. [Total Revenue] -> could be measure or column
    qualified: list[tuple[str, str]] = field(default_factory=list)  # (table, column)


def extract_references(expression: str) -> ParsedReferences:
    result = ParsedReferences()
    matched_spans: list[tuple[int, int]] = []

    for m in _QUALIFIED_REF.finditer(expression):
        table = m.group(1) or m.group(2)
        column = m.group(3)
        result.qualified.append((table, column))
        matched_spans.append(m.span())

    # Bare [Name] references: any `[...]` not already consumed as part of a
    # qualified Table[Column] match above.
    for m in re.finditer(r"\[([^\]]+)\]", expression):
        if any(m.start() >= s and m.end() <= e for s, e in matched_spans):
            continue
        result.bare_names.append(m.group(1))

    return result


def resolve_dependencies(model: PowerBISemanticModel) -> list[MigrationGap]:
    """Mutates each measure's referenced_measures/columns/dependent_tables
    in place and returns gaps for anything that doesn't resolve."""
    gaps: list[MigrationGap] = []

    measures_by_name: dict[str, PowerBIMeasure] = {}
    columns_by_table: dict[str, set[str]] = {}
    measures_by_table: dict[str, set[str]] = {}
    for table in model.tables:
        columns_by_table[table.name] = {c.name for c in table.columns}
        measures_by_table[table.name] = {m.name for m in table.measures}
        for measure in table.measures:
            measures_by_name[measure.name] = measure

    for table in model.tables:
        for measure in table.measures:
            refs = extract_references(measure.expression)
            referenced_measures: list[str] = []
            referenced_columns: list[str] = []
            dependent_tables: set[str] = set()

            for name in refs.bare_names:
                if name in measures_by_name and name != measure.name:
                    referenced_measures.append(name)
                elif name in columns_by_table.get(table.name, set()):
                    referenced_columns.append(f"{table.name}.{name}")
                    dependent_tables.add(table.name)
                else:
                    gaps.append(
                        MigrationGap(
                            id=new_id(),
                            object_ref=f"Measure:{measure.name}",
                            missing_information=(
                                f"Reference '[{name}]' in measure '{measure.name}' does not "
                                "match any known measure or column in its own table."
                            ),
                            why_it_matters=(
                                "Unresolved references break dependency graph accuracy and "
                                "migration impact analysis."
                            ),
                            migration_impact="Measure dependency chain may be incomplete.",
                            recommended_action=(
                                "Confirm the referenced object name or supply the missing "
                                "table/measure definition."
                            ),
                            status=Status.REQUIRES_INPUT,
                        )
                    )

            for table_name, column_name in refs.qualified:
                if table_name in columns_by_table and column_name in columns_by_table[table_name]:
                    referenced_columns.append(f"{table_name}.{column_name}")
                    dependent_tables.add(table_name)
                elif column_name in measures_by_table.get(table_name, set()) and column_name != measure.name:
                    # DAX allows Table[MeasureName] to reference a measure hosted on
                    # that table — not just a column. Without this branch, every
                    # such reference (a common, valid pattern) is misreported as an
                    # unresolved gap.
                    referenced_measures.append(column_name)
                else:
                    gaps.append(
                        MigrationGap(
                            id=new_id(),
                            object_ref=f"Measure:{measure.name}",
                            missing_information=(
                                f"Reference '{table_name}[{column_name}]' in measure "
                                f"'{measure.name}' does not match any known table/column."
                            ),
                            why_it_matters=(
                                "Unresolved references break dependency graph accuracy and "
                                "source lineage resolution."
                            ),
                            migration_impact="Source-to-target mapping may be incomplete.",
                            recommended_action=(
                                "Confirm the table/column exists or supply the missing "
                                "table definition."
                            ),
                            status=Status.REQUIRES_INPUT,
                        )
                    )

            measure.referenced_measures = sorted(set(referenced_measures))
            measure.referenced_columns = sorted(set(referenced_columns))
            measure.dependent_tables = sorted(dependent_tables)

    _compute_depths(measures_by_name)
    return gaps


def _compute_depths(measures_by_name: dict[str, PowerBIMeasure]) -> None:
    depth_cache: dict[str, int] = {}

    def depth_of(name: str, visiting: frozenset[str]) -> int:
        if name in depth_cache:
            return depth_cache[name]
        if name in visiting or name not in measures_by_name:
            return 0
        measure = measures_by_name[name]
        if not measure.referenced_measures:
            depth_cache[name] = 0
            return 0
        next_visiting = visiting | {name}
        depth = 1 + max(
            (depth_of(ref, next_visiting) for ref in measure.referenced_measures), default=0
        )
        depth_cache[name] = depth
        return depth

    for name in measures_by_name:
        measures_by_name[name].dependency_depth = depth_of(name, frozenset())
