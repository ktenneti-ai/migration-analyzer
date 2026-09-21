"""Upload content-shape detection.

Despite the package name (this module predates TMDL support), it now
inspects both JSON and TMDL uploads — a single entry point matches the
single `.json`/`.tmdl` upload endpoint. Detection never rejects an
unfamiliar *shape* (spec section 4): an unrecognized JSON object is stored
as UNKNOWN_GENERIC rather than refused, and TMDL content is a first-class
schema with its own adapter, not an error case.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

# TMDL (Tabular Model Definition Language) is a common Power BI / Tabular
# Editor export format that people sometimes save with a .json extension.
# It isn't JSON, so check for its characteristic top-level keywords before
# ever attempting json.loads — otherwise it fails with a cryptic "Expecting
# value: line 1 column 1" error instead of being routed to its own adapter.
_TMDL_HINT_RE = re.compile(
    r"^(createOrReplace\b|model\s|table\s|relationship\s|expression\s|cultureInfo\s|annotation\s|ref\s)"
)


class DetectedSchema(str, Enum):
    POWER_BI_MODEL = "power_bi_model"
    TMDL = "tmdl"
    TERADATA = "teradata"
    DATABRICKS = "databricks"
    UNKNOWN_GENERIC = "unknown_generic"


class InvalidJSONError(ValueError):
    pass


@dataclass
class DetectionResult:
    schema: DetectedSchema
    summary: str
    payload: dict


def detect(raw_text: str) -> DetectionResult:
    if _TMDL_HINT_RE.match(raw_text.lstrip()):
        return DetectionResult(
            schema=DetectedSchema.TMDL,
            summary="TMDL (Tabular Model Definition Language) semantic model script.",
            payload={"raw_text": raw_text},
        )

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise InvalidJSONError(f"Invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        return DetectionResult(
            schema=DetectedSchema.UNKNOWN_GENERIC,
            summary=f"Top-level JSON value is a {type(payload).__name__}, expected an object.",
            payload={"root": payload},
        )

    if isinstance(payload.get("model"), dict) and isinstance(
        payload["model"].get("tables"), list
    ):
        table_count = len(payload["model"]["tables"])
        return DetectionResult(
            schema=DetectedSchema.POWER_BI_MODEL,
            summary=f"Power BI semantic model JSON with {table_count} table(s).",
            payload=payload,
        )

    if str(payload.get("platform", "")).lower() == "teradata" and isinstance(
        payload.get("objects"), list
    ):
        return DetectionResult(
            schema=DetectedSchema.TERADATA,
            summary=f"Teradata object export with {len(payload['objects'])} object(s).",
            payload=payload,
        )

    if str(payload.get("platform", "")).lower() == "databricks":
        return DetectionResult(
            schema=DetectedSchema.DATABRICKS,
            summary="Databricks metadata export.",
            payload=payload,
        )

    return DetectionResult(
        schema=DetectedSchema.UNKNOWN_GENERIC,
        summary=f"Unrecognized JSON shape with top-level keys: {sorted(payload.keys())}.",
        payload=payload,
    )
