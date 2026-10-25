"""Tabular-model conventions shared by the model.bim JSON adapter and the
TMDL adapter: both formats serialize the same Tabular Object Model, so the
rules for reading relationship cardinality and a partition's Teradata
source live here once instead of drifting apart in each adapter.
"""
from __future__ import annotations

import re

# A table imported from Teradata typically has a partition whose M query
# looks like:
#     Source = Teradata.Database("BNRPROD", [HierarchicalNavigation=true]),
#     CP_ED = Source{[Schema="CP_ED"]}[Data],
#     V_X = CP_ED{[Name="V_CPED_X"]}[Data]
# Regex over the M text (consistent with this codebase's DAX handling — no
# full M parser) rather than trying to interpret the M language generally.
# Exported so downstream readers of source_hint (the teradata.py API routes,
# the lineage graph builder) parse it back apart with the same prefix,
# rather than each re-declaring their own copy of the literal.
TERADATA_SOURCE_HINT_PREFIX = "Teradata: "
# The first argument is a string literal or — common in real models, so the
# server can differ per environment — an M parameter, bare or as #"Name".
_TERADATA_DATABASE_RE = re.compile(r'Teradata\.Database\(\s*(?:"([^"]+)"|#"([^"]+)"|([A-Za-z_]\w*))')
# A parameter is a shared expression like:
#     ServerName = "tdprod" meta [IsParameterQuery=true, ...]
_M_PARAMETER_RE = re.compile(r'^\s*"([^"]*)"\s+meta\s*\[[^\]]*IsParameterQuery\s*=\s*true', re.I)
_M_SCHEMA_RE = re.compile(r'Schema\s*=\s*"([^"]+)"')
_M_TABLE_NAME_RE = re.compile(r'Name\s*=\s*"([^"]+)"')

# Confirmed naming convention (not an app-invented inference): this
# Teradata environment prefixes every view with "V_" — a base table has no
# such prefix. Exported so every reader of a parsed Teradata object name
# (teradata.py's API routes, compute_dashboard, the lineage graph builder)
# classifies it the same way instead of re-deriving the rule.
_TERADATA_VIEW_PREFIX = "V_"


def parse_teradata_source_hint(source_hint: str) -> dict:
    """Splits a "Teradata: DATABASE.SCHEMA.OBJECT" hint (as produced by
    teradata_source_hint) back into its parts, plus an object_type
    classification (VIEW/BASE_TABLE/None) from the "V_" naming convention."""
    parts = source_hint[len(TERADATA_SOURCE_HINT_PREFIX) :].split(".")
    if len(parts) > 3:
        # A host name like "tdprod.example.com" contains dots of its own.
        parts = [".".join(parts[:-2])] + parts[-2:]
    database = parts[0] if len(parts) > 0 else None
    schema = parts[1] if len(parts) > 1 else None
    obj = parts[2] if len(parts) > 2 else None
    object_type = None
    if obj:
        object_type = "VIEW" if obj.upper().startswith(_TERADATA_VIEW_PREFIX) else "BASE_TABLE"
    return {"database": database, "schema": schema, "object": obj, "object_type": object_type}


def m_parameter_value(expression: str | None) -> str | None:
    """The literal value of an M parameter expression, or None if the
    expression isn't a parameter."""
    m = _M_PARAMETER_RE.match(expression or "")
    return m.group(1) if m else None


def teradata_source_hint(m_text: str, parameters: dict[str, str]) -> str | None:
    """"Teradata: DATABASE.SCHEMA.OBJECT" for a partition M query that reads
    Teradata, resolving a parameterized server through `parameters`."""
    db_match = _TERADATA_DATABASE_RE.search(m_text)
    if not db_match:
        return None
    literal, quoted_param, bare_param = db_match.groups()
    param = quoted_param or bare_param
    database = literal or parameters.get(param, param)
    schema_match = _M_SCHEMA_RE.search(m_text)
    name_match = _M_TABLE_NAME_RE.search(m_text)
    parts = [database] + [m.group(1) for m in (schema_match, name_match) if m is not None]
    return TERADATA_SOURCE_HINT_PREFIX + ".".join(parts)


def relationship_cardinality(from_cardinality: str | None, to_cardinality: str | None) -> str:
    """Both formats only write fromCardinality/toCardinality when they
    differ from the (many-to-one) default, so their absence is itself the
    confirmed value, not a gap."""
    from_side = (from_cardinality or "many").lower()
    to_side = (to_cardinality or "one").lower()
    return f"{from_side.upper()}_TO_{to_side.upper()}"


def cross_filter_direction(crossfiltering_behavior: str | None) -> str:
    """bothDirections (or a simplified export's BIDIRECTIONAL) -> BOTH;
    oneDirection (the default, written only when explicit) and automatic
    -> SINGLE."""
    behavior = (crossfiltering_behavior or "").lower()
    return "BOTH" if "both" in behavior or "bidirectional" in behavior else "SINGLE"
