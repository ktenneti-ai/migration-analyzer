"""Finds semantic models in a corpus directory, in the shapes real models
actually arrive in, and turns each into the (filename, text) pair the
analyzer's upload endpoint receives.

Recognized:
- PBIP / Fabric TMDL folders: `X.SemanticModel/definition/` (or any
  `definition/` directory holding `model.tmdl`). The analyzer only accepts
  one file per upload, so the folder's .tmdl files are concatenated into one
  script (model.tmdl first) — noted on the input so it's never mistaken for
  a file the user could upload as-is.
- `model.bim` / `*.bim`: model JSON. The upload endpoint only accepts
  `.json`/`.tmdl` extensions, so it's submitted as `.json` (noted).
- `*.pbit`: Power BI template; its `DataModelSchema` entry is model.bim
  JSON (UTF-16-LE), extracted and submitted as `.json` (noted).
- `*.json` / `*.tmdl` loose files.
- `*.pbix`: listed as skipped. Its data model is XPress9-compressed and not
  readable without Power BI; save it as .pbit or PBIP to include it.
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# PBIP side-car JSON that is never a semantic model.
_NON_MODEL_JSON = {
    "definition.pbism", "definition.pbir", ".platform", "item.metadata.json", "item.config.json",
    "diagramLayout.json", "localSettings.json", "editorSettings.json", "report.json",
    "unappliedChanges.json", "cache.abf",
}


@dataclass
class InputItem:
    path: str  # original file/folder, relative to the corpus root
    kind: str  # pbip_tmdl_folder | bim | pbit | json | tmdl | pbix
    upload_filename: str = ""
    notes: list[str] = field(default_factory=list)
    skip_reason: str | None = None


def discover(root: Path) -> list[InputItem]:
    items: list[InputItem] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root)
        dirnames.sort()

        # Report folders hold visuals, not models.
        if d.name.endswith(".Report"):
            dirnames[:] = []
            continue

        definition = d / "definition"
        if (definition / "model.tmdl").is_file() or (d.name == "definition" and (d / "model.tmdl").is_file()):
            folder = definition if (definition / "model.tmdl").is_file() else d
            label = d.name if folder is definition else d.parent.name
            items.append(
                InputItem(
                    path=str(folder.relative_to(root)),
                    kind="pbip_tmdl_folder",
                    upload_filename=f"{_stem(label)}.tmdl",
                    notes=["PBIP TMDL folder: the harness concatenated its .tmdl files into one upload "
                           "(the app only accepts a single file)"],
                )
            )
            dirnames[:] = []
            # A model.bim next to a TMDL definition is a stale copy; skip it.
            continue

        for fname in sorted(filenames):
            p = rel / fname
            lower = fname.lower()
            if lower.endswith(".bim"):
                items.append(InputItem(str(p), "bim", f"{_stem(d.name if fname == 'model.bim' else fname)}.json",
                                       notes=["submitted as .json — the upload endpoint rejects the .bim extension"]))
            elif lower.endswith(".pbit"):
                items.append(InputItem(str(p), "pbit", f"{_stem(fname)}.json",
                                       notes=["extracted DataModelSchema from the .pbit template"]))
            elif lower.endswith(".pbix"):
                items.append(InputItem(str(p), "pbix", skip_reason=(
                    "PBIX data model is XPress9-compressed and can't be read outside Power BI; "
                    "save it as .pbit (File > Export > Power BI template) or as a PBIP project")))
            elif lower.endswith(".json") and fname not in _NON_MODEL_JSON:
                items.append(InputItem(str(p), "json", fname))
            elif lower.endswith(".tmdl"):
                items.append(InputItem(str(p), "tmdl", fname))
    return items


def _stem(name: str) -> str:
    for suffix in (".SemanticModel", ".Dataset", ".bim", ".pbit", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def load_text(root: Path, item: InputItem) -> str:
    """Produces exactly the text that would be uploaded. Raises
    UnicodeDecodeError the same way the upload route would reject it."""
    path = root / item.path
    if item.kind == "pbip_tmdl_folder":
        files = sorted(path.rglob("*.tmdl"))
        # model.tmdl first so the script starts with `model` (the app's
        # format detector keys off the first keyword), then the rest in a
        # stable order.
        files.sort(key=lambda f: (f.name != "model.tmdl", f.name != "database.tmdl", str(f)))
        return "\n\n".join(f.read_bytes().decode("utf-8-sig") for f in files)
    if item.kind == "pbit":
        with zipfile.ZipFile(path) as z:
            raw = z.read("DataModelSchema")
        return raw.decode("utf-16-le").lstrip("﻿")
    # Same decoding as backend/app/api/routes/ingestion.py.
    return path.read_bytes().decode("utf-8-sig")
