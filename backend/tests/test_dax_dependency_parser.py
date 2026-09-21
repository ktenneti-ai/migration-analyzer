from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.parsers.dax.dependency_parser import extract_references, resolve_dependencies


def test_extract_references_bare_and_qualified():
    refs = extract_references("[Total Revenue] - [Total Cost] + SUM(FactSales[Revenue])")
    assert refs.bare_names == ["Total Revenue", "Total Cost"]
    assert refs.qualified == [("FactSales", "Revenue")]


def test_extract_references_no_double_counts_qualified_as_bare():
    refs = extract_references("SUM('Fact Sales'[Revenue])")
    assert refs.qualified == [("Fact Sales", "Revenue")]
    assert refs.bare_names == []


def _finance_model(sample_data_dir):
    import os

    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    return extract_semantic_model(
        detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance"
    )


def test_resolve_dependencies_builds_chain_and_depth(sample_data_dir):
    model = _finance_model(sample_data_dir)
    gaps = resolve_dependencies(model)

    fact_sales = next(t for t in model.tables if t.name == "FactSales")
    by_name = {m.name: m for m in fact_sales.measures}

    total_revenue = by_name["Total Revenue"]
    assert total_revenue.referenced_columns == ["FactSales.Revenue"]
    assert total_revenue.dependency_depth == 0

    gross_margin = by_name["Gross Margin"]
    assert set(gross_margin.referenced_measures) == {"Total Revenue", "Total Cost"}
    assert gross_margin.dependency_depth == 1

    revenue_ytd = by_name["Revenue YTD"]
    assert "Total Revenue" in revenue_ytd.referenced_measures
    assert "DimDate.Date" in revenue_ytd.referenced_columns
    assert revenue_ytd.dependency_depth == 1

    # The sample file deliberately references a nonexistent measure and column.
    unresolved = by_name["Unresolved Reference Example"]
    assert unresolved.referenced_measures == []
    assert unresolved.referenced_columns == []
    assert len(gaps) == 2
    assert all(g.status == "REQUIRES_INPUT" for g in gaps)


def test_qualified_reference_to_a_measure_is_not_a_gap():
    # Table[MeasureName] is valid DAX for referencing a measure hosted on
    # that table, not just a column — a real pattern seen in production
    # Power BI models (e.g. 'Volume'[ADM] where ADM is a measure).
    payload = {
        "model": {
            "tables": [
                {
                    "name": "Volume",
                    "columns": [{"name": "ADMIT_NUM", "dataType": "int64"}],
                    "measures": [
                        {"name": "ADM", "expression": "SUM(Volume[ADMIT_NUM])"},
                        {"name": "ADM%", "expression": "CALCULATE(Volume[ADM]) / 100"},
                    ],
                }
            ]
        }
    }
    model = extract_semantic_model(payload, source_file="x.json", project_id="p1", model_name="X")
    gaps = resolve_dependencies(model)
    assert gaps == []

    adm_pct = next(m for m in model.tables[0].measures if m.name == "ADM%")
    assert adm_pct.referenced_measures == ["ADM"]
    assert adm_pct.referenced_columns == []


def test_circular_measure_reference_does_not_infinite_loop():
    from app.ingestion.json.powerbi_json_adapter import extract_semantic_model

    payload = {
        "model": {
            "tables": [
                {
                    "name": "T",
                    "columns": [],
                    "measures": [
                        {"name": "A", "expression": "[B] + 1"},
                        {"name": "B", "expression": "[A] + 1"},
                    ],
                }
            ]
        }
    }
    model = extract_semantic_model(payload, source_file="x.json", project_id="p1", model_name="X")
    gaps = resolve_dependencies(model)
    # No unresolved-reference gaps: both A and B exist as measures.
    assert gaps == []
    a = next(m for m in model.tables[0].measures if m.name == "A")
    b = next(m for m in model.tables[0].measures if m.name == "B")
    # Cycle guard means depth computation terminates rather than recursing forever.
    assert isinstance(a.dependency_depth, int)
    assert isinstance(b.dependency_depth, int)
