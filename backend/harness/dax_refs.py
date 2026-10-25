"""Independent DAX reference scanner and resolver (shares no code with
app/parsers/dax).

A character-level tokenizer rather than a regex: it skips `//`, `--` and
`/* */` comments and "string" literals, honours DAX escaping (`''` inside a
quoted table name, `]]` inside a bracketed name), and resolves names
case-insensitively, the way the DAX engine itself does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from harness.truth import TruthModel


@dataclass(frozen=True)
class Ref:
    table: str | None  # None for a bare [Name]
    name: str


@dataclass(frozen=True)
class Resolution:
    kind: str  # measure | column | column_other_table | virtual_column | unresolved
    target: str | None  # canonical "Table.Name" for columns, measure name for measures
    exact_case: bool = True


def scan(dax: str) -> tuple[list[Ref], set[str]]:
    """Returns (references, string literals) found outside comments."""
    refs: list[Ref] = []
    strings: set[str] = set()
    i, n = 0, len(dax)

    def read_bracket(j: int) -> tuple[str, int]:
        # dax[j] == "["; `]]` is an escaped `]`
        buf = []
        j += 1
        while j < n:
            if dax[j] == "]":
                if j + 1 < n and dax[j + 1] == "]":
                    buf.append("]")
                    j += 2
                    continue
                return "".join(buf), j + 1
            buf.append(dax[j])
            j += 1
        return "".join(buf), j

    while i < n:
        c = dax[i]
        two = dax[i : i + 2]
        if two in ("//", "--"):
            nl = dax.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif two == "/*":
            end = dax.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif c == '"':
            buf = []
            i += 1
            while i < n:
                if dax[i] == '"':
                    if i + 1 < n and dax[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(dax[i])
                i += 1
            strings.add("".join(buf))
        elif c == "'":
            buf = []
            i += 1
            while i < n:
                if dax[i] == "'":
                    if i + 1 < n and dax[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(dax[i])
                i += 1
            if i < n and dax[i] == "[":
                name, i = read_bracket(i)
                refs.append(Ref("".join(buf), name))
        elif c == "[":
            name, i = read_bracket(i)
            refs.append(Ref(None, name))
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (dax[j].isalnum() or dax[j] == "_"):
                j += 1
            ident = dax[i:j]
            if j < n and dax[j] == "[":
                name, i = read_bracket(j)
                refs.append(Ref(ident, name))
            else:
                i = j
        else:
            i += 1
    return refs, strings


class Resolver:
    def __init__(self, truth: TruthModel):
        self.measures: dict[str, str] = {}  # lower -> canonical name
        self.measure_home: dict[str, str] = {}  # lower measure -> table (lower)
        self.tables: dict[str, str] = {}  # lower -> canonical
        self.columns: dict[str, dict[str, str]] = {}  # lower table -> lower col -> canonical col
        for t in truth.tables.values():
            tl = t.name.lower()
            self.tables[tl] = t.name
            self.columns[tl] = {c.lower(): c for c in t.columns}
            for m in t.measures:
                self.measures[m.name.lower()] = m.name
                self.measure_home[m.name.lower()] = tl

    def resolve(self, ref: Ref, home_table: str, string_literals: set[str]) -> Resolution:
        nl = ref.name.lower()
        if ref.table is not None:
            tl = ref.table.lower()
            if tl in self.tables:
                canon_t = self.tables[tl]
                if nl in self.columns[tl]:
                    canon_c = self.columns[tl][nl]
                    exact = canon_t == ref.table and canon_c == ref.name
                    return Resolution("column", f"{canon_t}.{canon_c}", exact)
                if nl in self.measures:
                    canon = self.measures[nl]
                    return Resolution("measure", canon, canon_t == ref.table and canon == ref.name)
            return Resolution("unresolved", None)

        if nl in self.measures:
            canon = self.measures[nl]
            return Resolution("measure", canon, canon == ref.name)
        home_l = home_table.lower()
        if nl in self.columns.get(home_l, {}):
            canon_c = self.columns[home_l][nl]
            return Resolution("column", f"{home_table}.{canon_c}", canon_c == ref.name)
        owners = [tl for tl, cols in self.columns.items() if nl in cols]
        if len(owners) == 1:
            tl = owners[0]
            canon_c = self.columns[tl][nl]
            return Resolution("column_other_table", f"{self.tables[tl]}.{canon_c}", canon_c == ref.name)
        if len(owners) > 1:
            # Ambiguous bare column: valid DAX in row context, but which table
            # depends on the iterator — still a real reference, not a gap.
            return Resolution("column_other_table", None)
        if ref.name in string_literals or any(s.lower() == nl for s in string_literals):
            # ADDCOLUMNS / SUMMARIZE / SELECTCOLUMNS define columns by string name.
            return Resolution("virtual_column", None)
        return Resolution("unresolved", None)


# Analyzer gap messages look like:
#   "Reference '[Name]' in measure 'M' does not ..."
#   "Reference 'Table[Col]' in measure 'M' does not ..."
_GAP_RE = re.compile(r"^Reference '(.*)' in measure '(.*)' does not", re.S)


def parse_analyzer_gap(missing_information: str) -> tuple[str, Ref] | None:
    """Returns (measure_name, ref) for an analyzer unresolved-reference gap."""
    m = _GAP_RE.match(missing_information)
    if not m:
        return None
    ref_text, measure = m.group(1), m.group(2)
    if ref_text.startswith("["):
        return measure, Ref(None, ref_text[1:-1])
    lb = ref_text.find("[")
    if lb == -1:
        return None
    return measure, Ref(ref_text[:lb], ref_text[lb + 1 : -1])
