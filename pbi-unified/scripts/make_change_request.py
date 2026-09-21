#!/usr/bin/env python3
"""Emit change_request.json from review findings (schema in review-rubric.md).

Only findings with an actionable payload become changes:
  - proposed_sql -> {"measure", "new_sql", "new_status": "reviewed"}
  - proposed_action: "drop" -> {"measure", "action": "drop"}
Everything else stays a finding for the report (human/user decision).

The reviewing assistant edits review_findings.json first — adding proposed_sql for its
C1 re-derivations — then runs this.

Usage: python make_change_request.py --findings conversion/sales/review_findings.json
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import load_json, save_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    a = ap.parse_args()
    fnd = load_json(a.findings, "review_findings.json")
    changes = []
    for f in fnd["findings"]:
        obj = f.get("object", "")
        if f.get("proposed_sql"):
            changes.append({"measure": obj, "finding": f["finding"],
                            "severity": f["severity"], "reason": f["message"],
                            "new_sql": f["proposed_sql"], "new_status": "reviewed"})
        elif f.get("proposed_action") == "drop":
            changes.append({"measure": obj, "finding": f["finding"],
                            "severity": f["severity"], "reason": f["message"],
                            "action": "drop"})
    out = {"reviewer": "pbi-unified-reviewer",
           "review_score": fnd["review_score"],
           "verdict": fnd.get("verdict") or fnd.get("verdict_hint"),
           "changes": changes}
    save_json(out, os.path.join(os.path.dirname(a.findings), "change_request.json"))
    print(f"change_request.json: {len(changes)} actionable changes "
          f"(of {len(fnd['findings'])} findings). Apply with: "
          f"translate.py --apply-change-request change_request.json")


if __name__ == "__main__":
    main()
