"""Independent ground-truth extraction for Power BI semantic models.

This module deliberately shares no code with `app/` — it is a second,
separately written reading of the same source files, implemented from the
model.bim / TMSL / TMDL format rules rather than from the analyzer's
parsers. The harness compares the analyzer's output against this; where the
two disagree, the disagreement is the finding.

It also inventories model features the analyzer does not model at all
(calculation groups, RLS, perspectives, incremental refresh, ...) so a run
over real models shows what is being silently dropped, not just what is
being extracted wrongly.

TMDL rules implemented (per Microsoft's TMDL specification):
- nesting is by indentation (tabs by default; a space-indented file is
  handled by detecting its indent unit)
- `///` and `//` lines are descriptions/comments
- names are bare, or single-quoted with `''` escaping a literal quote
- an object's expression is either inline after `=`, fenced with ```, or
  — the common case in real PBIP exports — written unfenced on the
  following lines, indented one level deeper than the object's properties
- relationship cardinality defaults to many (from) -> one (to), and
  cross-filtering defaults to one direction
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class TruthMeasure:
    table: str
    name: str
    expression: str


@dataclass
class TruthTable:
    name: str
    columns: list[str] = field(default_factory=list)
    measures: list[TruthMeasure] = field(default_factory=list)
    is_auto_date: bool = False
    teradata_source: str | None = None  # "DB.SCHEMA.OBJECT" when a partition reads Teradata


@dataclass
class TruthRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    from_cardinality: str = "many"
    to_cardinality: str = "one"
    cross_filter: str = "oneDirection"
    is_active: bool = True

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.from_table, self.from_column, self.to_table, self.to_column)

    @property
    def is_many_to_many(self) -> bool:
        return self.from_cardinality == "many" and self.to_cardinality == "many"

    @property
    def is_bidirectional(self) -> bool:
        return self.cross_filter.lower() == "bothdirections"


@dataclass
class TruthModel:
    format: str  # model.bim | TMSL script | tmdl
    tables: dict[str, TruthTable] = field(default_factory=dict)
    relationships: list[TruthRelationship] = field(default_factory=list)
    # Model features, counted (e.g. {"calculation_group": 2, "rls_role": 1}).
    features: Counter = field(default_factory=Counter)
    # Data source kinds found in partition / shared M expressions.
    data_sources: Counter = field(default_factory=Counter)

    def all_measures(self) -> list[TruthMeasure]:
        return [m for t in self.tables.values() for m in t.measures]


# --- Shared helpers ---------------------------------------------------------

_M_SOURCE_KINDS = [
    ("Teradata.Database", "Teradata"),
    ("Sql.Database", "SQL Server / Azure SQL"),
    ("Sql.Databases", "SQL Server / Azure SQL"),
    ("Snowflake.Databases", "Snowflake"),
    ("Databricks.Catalogs", "Databricks"),
    ("DatabricksMultiCloud.Catalogs", "Databricks"),
    ("Oracle.Database", "Oracle"),
    ("PostgreSQL.Database", "PostgreSQL"),
    ("GoogleBigQuery.", "BigQuery"),
    ("AmazonRedshift.", "Redshift"),
    ("Odbc.", "ODBC"),
    ("OleDb.", "OLE DB"),
    ("AnalysisServices.", "Analysis Services"),
    ("PowerPlatform.Dataflows", "Dataflow"),
    ("PowerBI.Dataflows", "Dataflow"),
    ("Excel.Workbook", "Excel"),
    ("Csv.Document", "CSV"),
    ("SharePoint.", "SharePoint"),
    ("Web.Contents", "Web"),
    ("AzureStorage.", "Azure Storage"),
    ("Folder.Files", "Folder"),
    ("Json.Document", "JSON"),
    ("Binary.Decompress", "Entered data"),
]

# The server is a string literal or, often in real models, an M parameter.
_TD_DB_RE = re.compile(r'Teradata\.Database\(\s*(?:"([^"]+)"|#?"?([A-Za-z_][\w ]*)"?)')
_TD_SCHEMA_RE = re.compile(r'Schema\s*=\s*"([^"]+)"')
_TD_NAME_RE = re.compile(r'(?:Name|Item)\s*=\s*"([^"]+)"')


def _m_source_kinds(m_text: str) -> list[str]:
    kinds = sorted({label for needle, label in _M_SOURCE_KINDS if needle in m_text})
    return kinds or ["Other / none detected"]


def _teradata_object(m_text: str) -> str | None:
    db = _TD_DB_RE.search(m_text)
    if not db:
        return None
    parts = [db.group(1) or f"<parameter {db.group(2).strip()}>"]
    for rx in (_TD_SCHEMA_RE, _TD_NAME_RE):
        m = rx.search(m_text)
        if m:
            parts.append(m.group(1))
    return ".".join(parts)


_AUTO_DATE_PREFIXES = ("LocalDateTable_", "DateTableTemplate_")
_AUTO_DATE_ANNOTATIONS = {"__PBI_LocalDateTable", "__PBI_TemplateDateTable"}


# --- model.bim / TMSL JSON --------------------------------------------------

def find_model_json(payload) -> tuple[dict | None, str]:
    """Locates the `model` object in a model.bim, a .pbit DataModelSchema, or
    a TMSL createOrReplace/create/alter script."""
    if not isinstance(payload, dict):
        return None, ""
    if isinstance(payload.get("model"), dict):
        return payload["model"], "model.bim"
    for verb in ("createOrReplace", "create", "alter"):
        cmd = payload.get(verb)
        if isinstance(cmd, dict):
            db = cmd.get("database")
            if isinstance(db, dict) and isinstance(db.get("model"), dict):
                return db["model"], f"TMSL {verb} script"
    return None, ""


def _json_text(value) -> str:
    """bim expressions are a string or a list of lines."""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    return ""


def extract_from_json_text(text: str) -> TruthModel | None:
    """Returns None when the JSON isn't a semantic model at all."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    model, fmt = find_model_json(payload)
    if model is None:
        return None
    truth = TruthModel(format=fmt)
    feats = truth.features

    for t in model.get("tables", []) or []:
        name = t.get("name") or ""
        table = TruthTable(name=name)
        annotations = {a.get("name"): str(a.get("value", "")) for a in t.get("annotations", []) or []}
        table.is_auto_date = name.startswith(_AUTO_DATE_PREFIXES) or any(
            annotations.get(a, "").lower() == "true" for a in _AUTO_DATE_ANNOTATIONS
        )

        for c in t.get("columns", []) or []:
            table.columns.append(c.get("name") or "")
            if c.get("type") in ("calculated", "calculatedTableColumn") and c.get("expression") is not None:
                feats["calculated_column"] += 1
            elif "expression" in c and c.get("type") != "calculatedTableColumn":
                feats["calculated_column"] += 1
            if any(p.get("name") == "ParameterMetadata" for p in c.get("extendedProperties", []) or []):
                feats["field_parameter"] += 1

        for m in t.get("measures", []) or []:
            table.measures.append(TruthMeasure(name, m.get("name") or "", _json_text(m.get("expression"))))
            if m.get("kpi"):
                feats["kpi"] += 1
            if m.get("formatStringDefinition"):
                feats["dynamic_format_string"] += 1
            if m.get("detailRowsDefinition"):
                feats["detail_rows_expression"] += 1

        if t.get("calculationGroup"):
            feats["calculation_group"] += 1
            feats["calculation_item"] += len(t["calculationGroup"].get("calculationItems", []) or [])
        if t.get("hierarchies"):
            feats["hierarchy"] += len(t["hierarchies"])
        if t.get("refreshPolicy"):
            feats["incremental_refresh_policy"] += 1

        for p in t.get("partitions", []) or []:
            src = p.get("source") or {}
            kind = src.get("type", "m")
            if kind == "calculated":
                feats["calculated_table"] += 1
            elif kind == "entity":
                feats["direct_lake_or_entity_partition"] += 1
            elif kind == "policyRange":
                feats["incremental_refresh_partition"] += 1
            elif kind == "query":
                feats["legacy_query_partition"] += 1
            if p.get("mode", "").lower() in ("directquery", "dual"):
                feats[f"{p['mode'].lower()}_partition"] += 1
            m_text = _json_text(src.get("expression")) or _json_text(src.get("query"))
            if kind in ("m", "query") and m_text:
                for k in _m_source_kinds(m_text):
                    truth.data_sources[k] += 1
                table.teradata_source = table.teradata_source or _teradata_object(m_text)

        truth.tables[name] = table

    for r in model.get("relationships", []) or []:
        truth.relationships.append(
            TruthRelationship(
                from_table=r.get("fromTable", ""),
                from_column=r.get("fromColumn", ""),
                to_table=r.get("toTable", ""),
                to_column=r.get("toColumn", ""),
                from_cardinality=r.get("fromCardinality", "many"),
                to_cardinality=r.get("toCardinality", "one"),
                cross_filter=r.get("crossFilteringBehavior", "oneDirection"),
                is_active=bool(r.get("isActive", True)),
            )
        )

    for role in model.get("roles", []) or []:
        feats["role"] += 1
        perms = role.get("tablePermissions", []) or []
        feats["rls_table_filter"] += sum(1 for p in perms if p.get("filterExpression"))
        feats["ols_column_permission"] += sum(len(p.get("columnPermissions", []) or []) for p in perms)
    feats["perspective"] += len(model.get("perspectives", []) or [])
    # The model's own default culture is always listed; anything beyond it
    # is a translation.
    feats["translation_culture"] += max(0, len(model.get("cultures", []) or []) - 1)
    for e in model.get("expressions", []) or []:
        feats["shared_m_expression_or_parameter"] += 1
        m_text = _json_text(e.get("expression"))
        if m_text and "IsParameterQuery" not in m_text:
            for k in _m_source_kinds(m_text):
                truth.data_sources[k] += 1
    feats["legacy_data_source"] += len(model.get("dataSources", []) or [])

    truth.features = Counter({k: v for k, v in feats.items() if v})
    return truth


# --- TMDL -------------------------------------------------------------------

@dataclass
class _Node:
    indent: int
    keyword: str
    name: str | None = None
    expression: str | None = None  # text after `=` (header or property form)
    value: str | None = None  # `key: value` property value
    line_no: int = 0
    children: list["_Node"] = field(default_factory=list)

    def child(self, keyword: str) -> list["_Node"]:
        return [c for c in self.children if c.keyword == keyword]

    def prop(self, key: str) -> str | None:
        for c in self.children:
            if c.keyword == key and c.value is not None:
                return c.value
            if c.keyword == key and c.value is None and c.name is None and c.expression is None:
                return "true"  # bare flag, e.g. `isHidden`
        return None


_QUOTED = r"'(?:[^']|'')*'"


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


_NAME_RE = re.compile(rf"^\s*({_QUOTED}|[^\s='][^\s=]*)\s*")


def _split_name_rest(rest: str) -> tuple[str | None, str | None]:
    """`'My ''Name''' = expr` -> ("My 'Name'", "expr"); `Name` -> ("Name", None);
    `= expr` -> (None, "expr")."""
    rest = rest.strip()
    if rest.startswith("="):
        return None, rest[1:].strip()
    m = _NAME_RE.match(rest)
    if not m:
        return rest, None
    name = _unquote(m.group(1))
    after = rest[m.end():]
    if after.startswith("="):
        return name, after[1:].strip()
    return name, None


def _indent_unit(lines: list[str]) -> tuple[str, int]:
    if any(l.startswith("\t") for l in lines):
        return "\t", 1
    widths = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() and l.startswith(" ")]
    return " ", (min(widths) if widths else 4)


def parse_tmdl_tree(text: str) -> list[_Node]:
    lines = text.splitlines()
    ch, unit = _indent_unit(lines)

    def indent(line: str) -> int:
        return (len(line) - len(line.lstrip(ch))) // unit

    root = _Node(indent=-1, keyword="<root>")
    stack = [root]
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("//"):
            i += 1
            continue
        ind = indent(raw)
        while stack[-1].indent >= ind:
            stack.pop()
        parts = s.split(None, 1)
        keyword, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        node = _Node(indent=ind, keyword=keyword, line_no=i + 1)
        i += 1

        if keyword.endswith(":"):
            node.keyword, node.value = keyword[:-1], rest.strip()
        else:
            # `source = <M>` / `expression Name = ...` / `measure 'X' = ...`
            if "=" in keyword and not rest:
                keyword, rest = keyword.split("=", 1)[0], "=" + keyword.split("=", 1)[1]
                node.keyword = keyword
            name, expr = _split_name_rest(rest) if rest else (None, None)
            node.name = name
            if expr is not None:
                # A named object's body sits below its own properties (+2);
                # a nameless `key =` property's body sits one level below it.
                body_min = ind + (2 if name is not None else 1)
                if expr.startswith("```"):
                    body = []
                    while i < n and lines[i].strip() != "```":
                        body.append(lines[i])
                        i += 1
                    i += 1  # closing fence
                    expr = "\n".join(l.strip() for l in body)
                else:
                    body = [expr] if expr else []
                    while i < n and (not lines[i].strip() or indent(lines[i]) >= body_min):
                        body.append(lines[i].strip())
                        i += 1
                    expr = "\n".join(body).strip()
                node.expression = expr

        stack[-1].children.append(node)
        stack.append(node)
    return root.children


def _walk(nodes: list[_Node]):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _split_ref(value: str) -> tuple[str, str]:
    """`'Table Name'.'Col'` / `Table.Col` / `'Tbl'.Col` -> (table, column)."""
    m = re.match(rf"^\s*({_QUOTED}|[^.']+)\.(.+)$", value)
    if not m:
        return _unquote(value), ""
    return _unquote(m.group(1)), _unquote(m.group(2))


def extract_from_tmdl_text(text: str) -> TruthModel:
    roots = parse_tmdl_tree(text)
    truth = TruthModel(format="tmdl")
    feats = truth.features
    cultures = 0

    for node in _walk(roots):
        kw = node.keyword
        if kw == "table" and node.name:
            table = TruthTable(name=node.name)
            table.is_auto_date = node.name.startswith(_AUTO_DATE_PREFIXES) or any(
                a.name in _AUTO_DATE_ANNOTATIONS and (a.expression or "").lower() == "true"
                for a in node.child("annotation")
            )
            for c in node.children:
                if c.keyword == "column" and c.name is not None:
                    table.columns.append(c.name)
                    if c.expression:
                        feats["calculated_column"] += 1
                    if any(p.name == "ParameterMetadata" for p in c.child("extendedProperty")):
                        feats["field_parameter"] += 1
                elif c.keyword == "measure" and c.name is not None:
                    table.measures.append(TruthMeasure(node.name, c.name, c.expression or ""))
                    if c.child("kpi"):
                        feats["kpi"] += 1
                    if c.child("formatStringDefinition"):
                        feats["dynamic_format_string"] += 1
                    if c.child("detailRowsDefinition"):
                        feats["detail_rows_expression"] += 1
                elif c.keyword == "hierarchy":
                    feats["hierarchy"] += 1
                elif c.keyword == "calculationGroup":
                    feats["calculation_group"] += 1
                    feats["calculation_item"] += len(c.child("calculationItem"))
                elif c.keyword == "refreshPolicy":
                    feats["incremental_refresh_policy"] += 1
                elif c.keyword == "partition":
                    kind = (c.expression or "m").split()[0] if c.expression else "m"
                    if kind == "calculated":
                        feats["calculated_table"] += 1
                    elif kind == "entity":
                        feats["direct_lake_or_entity_partition"] += 1
                    elif kind == "policyRange":
                        feats["incremental_refresh_partition"] += 1
                    elif kind == "query":
                        feats["legacy_query_partition"] += 1
                    mode = (c.prop("mode") or "").lower()
                    if mode in ("directquery", "dual"):
                        feats[f"{mode}_partition"] += 1
                    if kind in ("m", "query"):
                        m_text = "\n".join(
                            s.expression or "" for s in c.children if s.keyword in ("source", "query")
                        )
                        if m_text:
                            for k in _m_source_kinds(m_text):
                                truth.data_sources[k] += 1
                            table.teradata_source = table.teradata_source or _teradata_object(m_text)
            truth.tables[node.name] = table
        elif kw == "relationship":
            from_table, from_column = _split_ref(node.prop("fromColumn") or "")
            to_table, to_column = _split_ref(node.prop("toColumn") or "")
            truth.relationships.append(
                TruthRelationship(
                    from_table=from_table,
                    from_column=from_column,
                    to_table=to_table,
                    to_column=to_column,
                    from_cardinality=node.prop("fromCardinality") or "many",
                    to_cardinality=node.prop("toCardinality") or "one",
                    cross_filter=node.prop("crossFilteringBehavior") or "oneDirection",
                    is_active=(node.prop("isActive") or "true").lower() != "false",
                )
            )
        elif kw == "role":
            feats["role"] += 1
            for p in node.child("tablePermission"):
                if p.expression:
                    feats["rls_table_filter"] += 1
                feats["ols_column_permission"] += len(p.child("columnPermission"))
        elif kw == "perspective":
            feats["perspective"] += 1
        elif kw == "cultureInfo":
            cultures += 1
        elif kw == "expression" and node.name is not None:
            feats["shared_m_expression_or_parameter"] += 1
            m_text = node.expression or ""
            if m_text and "IsParameterQuery" not in m_text:
                for k in _m_source_kinds(m_text):
                    truth.data_sources[k] += 1
        elif kw == "dataSource":
            feats["legacy_data_source"] += 1

    feats["translation_culture"] += max(0, cultures - 1)
    truth.features = Counter({k: v for k, v in feats.items() if v})
    return truth
