"""Tests for the real-model accuracy harness (backend/harness).

These pin down the harness's *own* correctness — its independent ground
truth and reference resolution — plus an end-to-end run. They deliberately
don't assert on the analyzer's current accuracy against the real-shape
fixtures, so fixing an analyzer bug the harness finds never breaks them.
"""
import json
import os
import zipfile
from pathlib import Path

from harness.dax_refs import Ref, Resolver, parse_analyzer_gap, scan
from harness.discover import discover, load_text
from harness.truth import extract_from_json_text, extract_from_tmdl_text
from harness.worker import analyze, build_truth

FIXTURES = Path(__file__).parent / "fixtures" / "real_shapes"
SAMPLES = Path(__file__).parent.parent.parent / "sample_data"


def _pbip_truth():
    item = next(i for i in discover(FIXTURES) if i.kind == "pbip_tmdl_folder")
    return build_truth(item, load_text(FIXTURES, item))


def test_discover_recognizes_real_input_shapes(tmp_path):
    (tmp_path / "a.pbix").write_bytes(b"PK")
    with zipfile.ZipFile(tmp_path / "t.pbit", "w") as z:
        z.writestr("DataModelSchema", (FIXTURES / "Finance" / "model.bim").read_text().encode("utf-16-le"))
    (tmp_path / "x.Report").mkdir()
    (tmp_path / "x.Report" / "report.json").write_text("{}")

    kinds = {i.path: (i.kind, i.skip_reason is not None) for i in discover(tmp_path)}
    assert kinds == {"a.pbix": ("pbix", True), "t.pbit": ("pbit", False)}

    pbit = next(i for i in discover(tmp_path) if i.kind == "pbit")
    assert extract_from_json_text(load_text(tmp_path, pbit)).tables.keys() == {
        "GL Entries", "Account", "Cost Center Bridge"}

    fixture_kinds = sorted(i.kind for i in discover(FIXTURES))
    assert fixture_kinds == ["bim", "pbip_tmdl_folder"]  # Sales.Report/ and definition.pbism ignored


def test_tmdl_truth_reads_spec_constructs():
    truth = _pbip_truth()
    assert set(truth.tables) == {"Sales", "Customer", "Date", "Time Intelligence"}
    measures = {m.name: m.expression for m in truth.tables["Sales"].measures}
    # Unfenced multi-line expression, indented below the measure's properties.
    assert measures["Sales Margin %"].splitlines() == [
        "VAR _sales = [Total Sales]",
        "VAR _cost = SUMX(Sales, Sales[Quantity] * RELATED(Customer[Standard Cost]))",
        "RETURN",
        "DIVIDE(_sales - _cost, _sales)",
    ]
    assert "Customer's Order Count" in measures  # '' escape
    assert "Line Total" in truth.tables["Sales"].columns  # calculated column
    assert "formatString" not in measures["Total Sales"]

    rels = {r.key: r for r in truth.relationships}
    assert set(rels) == {
        ("Sales", "CustomerKey", "Customer", "CustomerKey"),
        ("Sales", "Order Date", "Date", "Date"),
        ("Sales", "Ship Date", "Date", "Date"),
    }
    assert rels[("Sales", "Order Date", "Date", "Date")].is_bidirectional
    assert not rels[("Sales", "Ship Date", "Date", "Date")].is_active

    assert truth.tables["Customer"].teradata_source == "TDPROD.EDW_REF.CUSTOMER"
    assert truth.tables["Sales"].teradata_source == "<parameter ServerName>.EDW_SALES.V_ORDER_LINE"
    assert truth.features["calculation_group"] == 1
    assert truth.features["calculation_item"] == 2
    assert truth.features["rls_table_filter"] == 1
    assert truth.features["calculated_table"] == 1
    assert "translation_culture" not in truth.features  # only the default culture


def test_tmdl_truth_handles_fences_and_space_indentation():
    text = (
        "table T\n"
        "    measure M = ```\n"
        "        SUM ( T[x] )\n"
        "        ```\n"
        "        formatString: 0\n"
        "    column x\n"
        "        dataType: int64\n"
    )
    truth = extract_from_tmdl_text(text)
    assert truth.tables["T"].columns == ["x"]
    assert truth.tables["T"].measures[0].expression == "SUM ( T[x] )"


def test_bim_truth_reads_real_bim_conventions():
    truth = extract_from_json_text((FIXTURES / "Finance" / "model.bim").read_text())
    measures = {m.name: m.expression for m in truth.tables["GL Entries"].measures}
    assert measures["Amount YTD"].strip().startswith("VAR _ytd")  # list-of-lines expression
    m2m = [r for r in truth.relationships if r.is_many_to_many]
    assert len(m2m) == 1 and m2m[0].is_bidirectional
    assert truth.tables["GL Entries"].teradata_source == "TDPROD.EDW_FIN.V_GL_ENTRY"
    assert truth.features["translation_culture"] == 1
    assert truth.features["perspective"] == 1
    assert truth.data_sources["SQL Server / Azure SQL"] == 1


def test_tmsl_script_and_non_model_json():
    tmsl = json.dumps({"createOrReplace": {"object": {"database": "X"},
                                           "database": {"name": "X", "model": {"tables": [{"name": "T"}]}}}})
    assert extract_from_json_text(tmsl).format == "TMSL createOrReplace script"
    assert extract_from_json_text('{"platform": "teradata", "objects": []}') is None


def test_dax_scan_skips_comments_and_strings_and_honours_escapes():
    refs, strings = scan(
        "// [Commented]\n"
        "SUMX('Bob''s Table', 'Bob''s Table'[Qty]) /* [Block] */ & \"[NotARef]\" -- [Trailing]\n"
        "+ [Odd]]Name] + Sales[Amount]"
    )
    assert refs == [Ref("Bob's Table", "Qty"), Ref(None, "Odd]Name"), Ref("Sales", "Amount")]
    assert strings == {"[NotARef]"}


def test_resolver_matches_dax_name_resolution():
    truth = _pbip_truth()
    r = Resolver(truth)
    case = r.resolve(Ref(None, "total sales"), "Sales", set())
    assert (case.kind, case.target, case.exact_case) == ("measure", "Total Sales", False)
    other = r.resolve(Ref(None, "Standard Cost"), "Sales", set())
    assert (other.kind, other.target) == ("column_other_table", "Customer.Standard Cost")
    assert r.resolve(Ref(None, "Total"), "Sales", {"Total"}).kind == "virtual_column"
    assert r.resolve(Ref("Nope", "x"), "Sales", set()).kind == "unresolved"


def test_parse_analyzer_gap_message():
    assert parse_analyzer_gap(
        "Reference '[Old]' in measure 'M' does not match any known measure or column in its own table."
    ) == ("M", Ref(None, "Old"))
    assert parse_analyzer_gap(
        "Reference 'Fact Sales[Amt]' in measure 'M' does not match any known table/column."
    ) == ("M", Ref("Fact Sales", "Amt"))


def test_sample_data_reconciles_exactly(db_session):
    """The shipped samples are known-good: the analyzer's extraction must
    match the harness's ground truth exactly, with no harness errors."""
    items = [i for i in discover(SAMPLES) if not i.skip_reason]
    results = [analyze(SAMPLES, i) for i in items]
    assert {r["input"]["path"]: r["status"] for r in results} == {
        "finance_model.json": "ok",
        "finance_model.tmdl": "ok",
        "operations_model.json": "ok",
        "teradata_sample.json": "not_a_model",
    }
    extraction_checks = ("_missing", "_extra", "measure_expression_", "relationship_", "stage_crash")
    for r in results:
        bad = [f for f in r["findings"] if any(c in f["check"] for c in extraction_checks)]
        assert bad == [], (r["input"]["path"], bad)
        m = r.get("metrics") or {}
        for what in ("tables", "columns", "measures", "relationships"):
            assert m.get(f"{what}_matched", 0) == m.get(f"{what}_truth", 0)


def test_cli_end_to_end(tmp_path):
    from harness.run import main

    out = tmp_path / "out"
    assert main([str(FIXTURES), "--out", str(out), "--jobs", "2", "--redact"]) == 0
    report = (out / "report.md").read_text()
    results = json.loads((out / "results.json").read_text())["results"]
    assert "## Accuracy scorecard" in report
    assert len(results) == 2
    assert all(r["status"] in ("ok", "crashed", "rejected", "not_extracted") for r in results)
    # Redaction: no model content leaks into either output.
    for text in (report, json.dumps(results)):
        for secret in ("Total Sales", "GL Entries", "EDW_SALES", os.path.expanduser("~")):
            assert secret not in text


def test_operator_risk_check_accepts_correct_rewrites():
    from harness.worker import _operator_risks

    assert _operator_risks('"a" & [x]', '"a" || MEASURE(`x`)') == []
    assert _operator_risks("[a] || [b]", "MEASURE(`a`) OR MEASURE(`b`)") == []
    assert _operator_risks('"a&b" & [x]', '"a&b" & MEASURE(`x`)') == [
        "&: DAX string concatenation; in Databricks & is bitwise AND"]
    assert _operator_risks("[a] || [b]", "MEASURE(`a`) || MEASURE(`b`)") == [
        "||: DAX logical OR left in SQL, where || is string concatenation"]
