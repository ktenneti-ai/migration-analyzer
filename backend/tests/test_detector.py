import pytest

from app.ingestion.json.detector import DetectedSchema, InvalidJSONError, detect


def test_detects_power_bi_model():
    result = detect('{"model": {"tables": [{"name": "T1", "columns": [], "measures": []}]}}')
    assert result.schema == DetectedSchema.POWER_BI_MODEL
    assert "1 table" in result.summary


def test_detects_teradata_export():
    result = detect('{"platform": "Teradata", "objects": [{"name": "VW_X"}]}')
    assert result.schema == DetectedSchema.TERADATA


def test_detects_databricks_export():
    result = detect('{"platform": "Databricks", "catalog": "prod"}')
    assert result.schema == DetectedSchema.DATABRICKS


def test_unknown_schema_is_not_rejected():
    result = detect('{"foo": "bar", "baz": 123}')
    assert result.schema == DetectedSchema.UNKNOWN_GENERIC
    assert result.payload == {"foo": "bar", "baz": 123}


def test_non_object_root_is_unknown_generic_not_an_error():
    result = detect("[1, 2, 3]")
    assert result.schema == DetectedSchema.UNKNOWN_GENERIC


def test_invalid_json_raises():
    with pytest.raises(InvalidJSONError):
        detect("{not valid json")


def test_empty_string_raises():
    with pytest.raises(InvalidJSONError):
        detect("")


def test_tmdl_content_is_detected_not_rejected_as_invalid_json():
    tmdl = "createOrReplace\r\n\r\n\tmodel Model\r\n\t\tculture: en-US\r\n"
    result = detect(tmdl)
    assert result.schema == DetectedSchema.TMDL
    assert result.payload["raw_text"] == tmdl
