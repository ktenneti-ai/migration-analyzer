# Power BI extraction

Milestone 1's Power BI extraction logic lives in
`app/ingestion/json/powerbi_json_adapter.py` since JSON is currently the
only supported input format. Once PBIX/PBIT/PBIP/TMDL ingestion adapters
are added, shared extraction logic that isn't JSON-specific (e.g. DAX
dependency resolution consumers, relationship classification) should move
here so each input adapter feeds one common extraction path (spec
section 3).
