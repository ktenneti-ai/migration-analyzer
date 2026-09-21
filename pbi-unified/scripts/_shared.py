#!/usr/bin/env python3
"""Shared utilities for the PBI → Databricks conversion pipeline.

Centralises helpers that must behave identically across scripts — a drift in
snake() between translate.py and build_view.py silently breaks every column
reference in the emitted spec.
"""
import json, os, re


def snake(s: str) -> str:
    """Convert PascalCase / camelCase / arbitrary PBI names to snake_case.

    PBI names are typically PascalCase ('OrderID', 'NetAmount'); Unity Catalog
    columns are typically snake_case ('order_id', 'net_amount'). A naive
    lowercase-only pass turns 'OrderID' into 'orderid', which will never match
    a real 'order_id' column.
    """
    s = (s or "").strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"\W+", "_", s.lower())
    return s.strip("_")


def split_args(s: str, open_paren_idx: int) -> tuple:
    """Parenthesis-depth-aware argument splitter.

    Given a string and the index of an opening '(', returns
    (list_of_args, closing_paren_index). Handles nested parens and braces
    correctly — the naive comma-split version breaks on DIVIDE(SUM(x), COUNT(y)).
    """
    depth, cur, args, i = 0, [], [], open_paren_idx
    while i < len(s):
        ch = s[i]
        if ch in "({":
            depth += 1
            if depth > 1:
                cur.append(ch)
        elif ch in ")}":
            depth -= 1
            if depth == 0:
                if cur:
                    args.append("".join(cur))
                return args, i
            cur.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(cur))
            cur = []
        elif depth >= 1:
            cur.append(ch)
        i += 1
    if cur:
        args.append("".join(cur))
    return args, i


def load_json(path: str, label: str = None) -> dict:
    """Load a JSON file with a helpful error on failure."""
    label = label or os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(
            f"{label} not found at {path} — run the preceding pipeline stage first."
        )
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"{label} at {path} is not valid JSON (line {e.lineno}): {e.msg}"
        )


def save_json(data, path: str) -> None:
    """Write JSON with consistent formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_text(text: str, path: str) -> None:
    """Write a text file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
