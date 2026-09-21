"""JSON schema detection.

Inspect an uploaded JSON file's structure to decide which adapter should
process it (spec section 4: "Do NOT reject a JSON file simply because its
schema is unfamiliar"). Unknown shapes are still accepted and stored, just
without extraction — nothing is discarded.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

# TMDL (Tabular Model Definition Language) is a common Power BI / Tabular
# Editor export format that people sometimes save with a .json extension —
# it isn't JSON at all, so json.loads fails immediately with a cryptic
# "Expecting value: line 1 column 1" error. Recognize its characteristic
# top-level keywords so we can say what's actually wrong instead.
_TMDL_HINT_RE = re.compile(
    r"^(createOrReplace\b|model\s|table\s|relationship\s|expression\s|cultureInfo\s|annotation\s|ref\s)"
)


class DetectedSchema(str, Enum):
    POWER_BI_MODEL = "power_bi_model"
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
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        if _TMDL_HINT_RE.match(raw_text.lstrip()):
            raise InvalidJSONError(
                "This looks like a TMDL (Tabular Model Definition Language) file, not JSON — "
                "TMDL ingestion isn't implemented yet; JSON is the only supported format right "
                "now. Export the semantic model as JSON instead (e.g. Tabular Editor's "
                "'Save As JSON' / a .bim file), or ask for TMDL support to be added."
            ) from exc
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
