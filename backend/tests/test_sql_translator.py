from app.metadata.models import PowerBIColumn, PowerBIMeasure, PowerBISemanticModel, PowerBITable, Provenance
from app.parsers.dax.classifier import classify_measures
from app.parsers.dax.dependency_parser import resolve_dependencies
from app.parsers.dax.sql_translator import translate_model


def _prov():
    return Provenance(source_file="x.json", source_type="json", json_path="$")


def _translate(measures: list[tuple[str, str]]) -> dict[str, dict]:
    table = PowerBITable(
        id="t1",
        model_id="m1",
        name="Fact",
        columns=[
            PowerBIColumn(id="c1", table_id="t1", name="Value", provenance=_prov()),
            PowerBIColumn(id="c2", table_id="t1", name="Cost", provenance=_prov()),
        ],
        measures=[
            PowerBIMeasure(id=f"me-{n}", table_id="t1", name=n, expression=e, provenance=_prov())
            for n, e in measures
        ],
        provenance=_prov(),
    )
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Test", tables=[table], provenance=_prov())
    resolve_dependencies(model)
    classify_measures(model)
    return {i.measure_name: i.model_dump() for i in translate_model(model)}


def test_simple_sum_translates_mechanically():
    result = _translate([("Total", "SUM(Fact[Value])")])
    item = result["Total"]
    assert item["status"] == "auto"
    assert item["translated_sql"] == "sum(fact.value)"
    assert item["notes"] == []


def test_divide_two_arg_uses_try_divide():
    result = _translate([("Margin Pct", "DIVIDE(SUM(Fact[Value]), SUM(Fact[Cost]))")])
    assert result["Margin Pct"]["translated_sql"] == "try_divide(sum(fact.value), sum(fact.cost))"


def test_divide_three_arg_uses_coalesce_try_divide():
    result = _translate([("Margin Pct", "DIVIDE(SUM(Fact[Value]), SUM(Fact[Cost]), 0)")])
    assert result["Margin Pct"]["translated_sql"] == "coalesce(try_divide(sum(fact.value), sum(fact.cost)), 0)"


def test_measure_reference_becomes_measure_function_call():
    result = _translate(
        [
            ("Base", "SUM(Fact[Value])"),
            ("Doubled", "[Base] * 2"),
        ]
    )
    assert result["Doubled"]["status"] == "auto"
    assert "MEASURE(`Base`)" in result["Doubled"]["translated_sql"]


def test_if_is_flagged_not_rewritten():
    result = _translate([("Flag", "IF(Fact[Value] > 0, 1, 0)")])
    item = result["Flag"]
    assert item["status"] == "auto_spot_check"
    assert "IF(" in item["translated_sql"]  # not mechanically rewritten
    assert any("CASE WHEN" in n for n in item["notes"])


def test_isblank_is_rewritten_to_is_null():
    result = _translate([("Flag", "IF(ISBLANK(Fact[Value]), 0, 1)")])
    assert "IS NULL" in result["Flag"]["translated_sql"]
    assert "ISBLANK" not in result["Flag"]["translated_sql"].upper()


def test_manual_port_band_produces_stub_not_fabricated_sql():
    result = _translate([("Cyclic A", "SUM(Fact[Value]) + EARLIER(Fact[Value])")])
    item = result["Cyclic A"]
    assert item["status"] in ("manual_port", "unsupported")
    assert item["translated_sql"].startswith("--")
    assert "nested row context" in item["translated_sql"] or item["notes"]


def test_unresolved_measure_reference_downgrades_to_needs_review():
    # A <-> B form a dependency cycle, which classify_measures forces to
    # MANUAL_PORT via a correction pass *after* its main scoring loop. C
    # depends only on A and was already scored (as AUTO) during that main
    # loop, before the correction ran — so C's own classify band doesn't
    # reflect that its dependency is now unusable. translate_model's own
    # reference-status check is the safety net that catches this and
    # downgrades C, rather than emitting SQL that calls MEASURE(`A`) against
    # a measure that will never actually translate.
    result = _translate(
        [
            ("A", "[B] + 1"),
            ("B", "[A] + 1"),
            ("C", "[A] + 1"),
        ]
    )
    assert result["A"]["status"] not in ("auto", "auto_spot_check")
    c = result["C"]
    assert c["status"] == "needs_review"
    assert any("unresolved measure ref" in n for n in c["notes"])
