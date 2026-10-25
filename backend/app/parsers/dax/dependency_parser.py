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
from app.parsers.dax.classifier import strip_comments_and_strings

_QUALIFIED_REF = re.compile(r"(?:'([^']+)'|(\w+))\[([^\]]+)\]")
# Functions whose first argument is the table they iterate: inside them a
# bare [Column] refers to that table's column (row context), not to the
# measure's home table.
_ROW_CONTEXT_TABLE_RE = re.compile(
    r"\b(?:SUMX|AVERAGEX|MINX|MAXX|COUNTX|COUNTAX|PRODUCTX|CONCATENATEX|RANKX|FILTER|ADDCOLUMNS|"
    r"SELECTCOLUMNS|GENERATE|GENERATEALL)\s*\(\s*(?:'((?:[^']|'')+)'|(\w+))",
    re.I,
)


@dataclass
class ParsedReferences:
    bare_names: list[str] = field(default_factory=list)  # e.g. [Total Revenue] -> could be measure or column
    qualified: list[tuple[str, str]] = field(default_factory=list)  # (table, column)


def extract_references(expression: str) -> ParsedReferences:
    # Brackets inside a comment ("// was [Old Measure]") or a string literal
    # aren't references.
    expression = strip_comments_and_strings(expression)
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

    # DAX resolves names case-insensitively ([total sales] is [Total Sales]),
    # so every lookup is keyed by lowercased name and maps back to the
    # canonical spelling recorded in the model.
    measures_by_name: dict[str, PowerBIMeasure] = {}
    measure_names: dict[str, str] = {}
    table_names: dict[str, str] = {}
    columns_by_table: dict[str, dict[str, str]] = {}
    measures_by_table: dict[str, dict[str, str]] = {}
    column_owners: dict[str, list[str]] = {}  # column name -> tables that have it
    for table in model.tables:
        key = table.name.lower()
        table_names[key] = table.name
        columns_by_table[key] = {c.name.lower(): c.name for c in table.columns}
        measures_by_table[key] = {m.name.lower(): m.name for m in table.measures}
        for column in table.columns:
            column_owners.setdefault(column.name.lower(), []).append(table.name)
        for measure in table.measures:
            measures_by_name[measure.name] = measure
            measure_names[measure.name.lower()] = measure.name

    for table in model.tables:
        own_columns = columns_by_table[table.name.lower()]
        for measure in table.measures:
            refs = extract_references(measure.expression)
            referenced_measures: list[str] = []
            referenced_columns: list[str] = []
            dependent_tables: set[str] = set()

            row_context_tables = {
                (m.group(1) or "").replace("''", "'").lower() or m.group(2).lower()
                for m in _ROW_CONTEXT_TABLE_RE.finditer(strip_comments_and_strings(measure.expression))
            }
            for name in refs.bare_names:
                canonical_measure = measure_names.get(name.lower())
                owner = _row_context_owner(column_owners.get(name.lower(), []), row_context_tables)
                if canonical_measure is not None and canonical_measure != measure.name:
                    referenced_measures.append(canonical_measure)
                elif name.lower() in own_columns:
                    referenced_columns.append(f"{table.name}.{own_columns[name.lower()]}")
                    dependent_tables.add(table.name)
                elif owner is not None:
                    # A bare [Column] from another table, e.g.
                    # AVERAGEX(Customer, [Standard Cost]): valid in the
                    # iterator's row context.
                    owner_key = owner.lower()
                    referenced_columns.append(f"{owner}.{columns_by_table[owner_key][name.lower()]}")
                    dependent_tables.add(owner)
                else:
                    ambiguous = len(column_owners.get(name.lower(), [])) > 1
                    gaps.append(
                        MigrationGap(
                            id=new_id(),
                            object_ref=f"Measure:{measure.name}",
                            missing_information=(
                                f"Reference '[{name}]' in measure '{measure.name}' does not "
                                + (
                                    "identify a single column: it exists in more than one table "
                                    f"({', '.join(sorted(column_owners[name.lower()]))}) and none is "
                                    "the table the expression iterates over."
                                    if ambiguous
                                    else "match any known measure or column."
                                )
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
                table_key, column_key = table_name.lower(), column_name.lower()
                canonical_table = table_names.get(table_key)
                if canonical_table is not None and column_key in columns_by_table[table_key]:
                    referenced_columns.append(f"{canonical_table}.{columns_by_table[table_key][column_key]}")
                    dependent_tables.add(canonical_table)
                elif (
                    column_key in measures_by_table.get(table_key, {})
                    and measures_by_table[table_key][column_key] != measure.name
                ):
                    # DAX allows Table[MeasureName] to reference a measure hosted on
                    # that table — not just a column. Without this branch, every
                    # such reference (a common, valid pattern) is misreported as an
                    # unresolved gap.
                    referenced_measures.append(measures_by_table[table_key][column_key])
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


def _row_context_owner(owners: list[str], row_context_tables: set[str]) -> str | None:
    """The table a bare [Column] belongs to when it isn't on the measure's
    own table: the only table that has it, or else the one the expression
    iterates over. None when that can't be decided."""
    if len(owners) == 1:
        return owners[0]
    iterated = [t for t in owners if t.lower() in row_context_tables]
    return iterated[0] if len(iterated) == 1 else None


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
