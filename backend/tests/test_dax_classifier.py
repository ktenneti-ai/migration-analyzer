from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.metadata.models import (
    PowerBIColumn,
    PowerBIMeasure,
    PowerBIRelationship,
    PowerBISemanticModel,
    PowerBITable,
    Provenance,
)
from app.parsers.dax.classifier import classify_measures, complexity_bucket
from app.parsers.dax.dependency_parser import resolve_dependencies


def _prov():
    return Provenance(source_file="x.json", source_type="json", json_path="$")


def _model(measures_by_table: dict[str, list[tuple[str, str]]], relationships=None) -> PowerBISemanticModel:
    tables = []
    for table_name, measures in measures_by_table.items():
        tables.append(
            PowerBITable(
                id=f"t-{table_name}",
                model_id="m1",
                name=table_name,
                columns=[PowerBIColumn(id="c1", table_id=f"t-{table_name}", name="Value", provenance=_prov())],
                measures=[
                    PowerBIMeasure(id=f"me-{name}", table_id=f"t-{table_name}", name=name, expression=expr, provenance=_prov())
                    for name, expr in measures
                ],
                provenance=_prov(),
            )
        )
    return PowerBISemanticModel(
        id="m1", project_id="p1", name="Test", tables=tables, relationships=relationships or [], provenance=_prov()
    )


def _classify(measures_by_table, relationships=None):
    model = _model(measures_by_table, relationships)
    resolve_dependencies(model)
    classify_measures(model)
    return {m.name: m for t in model.tables for m in t.measures}


def test_simple_aggregation_is_category_a():
    result = _classify({"Fact": [("Total Revenue", "SUM(Fact[Value])")]})
    m = result["Total Revenue"]
    assert m.complexity_category == "A"
    assert m.complexity_score == 100
    assert m.complexity_band == "AUTO"
    assert complexity_bucket(m.complexity_band) == "LOW"


def test_derived_measure_referencing_another_measure_is_category_b():
    result = _classify(
        {
            "Fact": [
                ("Total Revenue", "SUM(Fact[Value])"),
                ("Doubled Revenue", "[Total Revenue] * 2"),
            ]
        }
    )
    assert result["Doubled Revenue"].complexity_category == "B"


def test_time_intelligence_is_category_c_and_capped():
    result = _classify(
        {
            "Fact": [
                ("Total Revenue", "SUM(Fact[Value])"),
                ("Revenue YTD", "TOTALYTD([Total Revenue], Fact[Value])"),
            ]
        }
    )
    m = result["Revenue YTD"]
    assert m.complexity_category == "C"
    assert m.complexity_score <= 35
    assert m.complexity_band in ("MANUAL_PORT", "UNSUPPORTED")
    assert complexity_bucket(m.complexity_band) == "HIGH"


def test_filtered_aggregate_is_category_d():
    result = _classify({"Fact": [("Net Sales", "CALCULATE(SUM(Fact[Value]), Fact[Value] > 0)")]})
    assert result["Net Sales"].complexity_category == "D"


def test_semi_additive_is_category_e():
    result = _classify({"Fact": [("Ending Balance", "CLOSINGBALANCEMONTH(SUM(Fact[Value]), Fact[Value])")]})
    assert result["Ending Balance"].complexity_category == "E"


def test_earlier_forces_category_f():
    result = _classify({"Fact": [("Ranked", "EARLIER(Fact[Value])")]})
    m = result["Ranked"]
    assert m.complexity_category == "F"
    assert m.complexity_score <= 25


def test_rls_function_forces_low_score_and_category_f():
    result = _classify({"Fact": [("Whoami", "USERNAME()")]})
    assert result["Whoami"].complexity_category == "F"
    assert result["Whoami"].complexity_score <= 10


def test_weakest_link_propagates_through_dependency_chain():
    result = _classify(
        {
            "Fact": [
                ("Base", "SAMEPERIODLASTYEAR(Fact[Value])"),
                ("Wrapper", "[Base] * 1"),
            ]
        }
    )
    # Wrapper has no complex functions of its own but must inherit Base's capped score.
    assert result["Wrapper"].complexity_score == result["Base"].complexity_score
    assert "propagated from weakest dependency" in " ".join(result["Wrapper"].complexity_reasons)


def test_dependency_cycle_forces_manual_port():
    result = _classify(
        {
            "Fact": [
                ("A", "[B] + 1"),
                ("B", "[A] + 1"),
            ]
        }
    )
    assert result["A"].complexity_band == "MANUAL_PORT"
    assert result["B"].complexity_band == "MANUAL_PORT"
    assert "dependency cycle" in result["A"].complexity_reasons


def test_bidirectional_relationship_caps_score():
    rel = PowerBIRelationship(
        id="r1",
        model_id="m1",
        from_table="Fact",
        from_column="DimKey",
        to_table="Dim",
        to_column="DimKey",
        cross_filter_direction="BOTH",
        provenance=_prov(),
    )
    result = _classify({"Fact": [("Total", "SUM(Fact[Value])")]}, relationships=[rel])
    assert result["Total"].complexity_score <= 45


def test_dashboard_complexity_reflects_real_classification(sample_data_dir):
    import os

    from app.metadata.aggregates import compute_dashboard
    from app.metadata.models import ProjectData, Project

    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    model = extract_semantic_model(detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance")
    resolve_dependencies(model)
    classify_measures(model)

    data = ProjectData(project=Project(id="p1", name="Finance"), semantic_models=[model])
    dashboard = compute_dashboard(data)

    assert sum(dashboard["complexity"].values()) == 5
    assert dashboard["complexity"]["HIGH"] >= 1  # Revenue YTD (TOTALYTD)
