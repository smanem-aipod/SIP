"""
Case/whitespace-tolerant string comparison helpers for the calculation
engine.

Population filters (config/calculations/role_mappings.yaml) and formula
conditions (config/calculations/sip_metrics.yaml) compare source-file text
values (e.g. "Job Profile for SIP") against literal strings in config
(e.g. "Sales Professional"). Source files come from independently
maintained HR/BP exports that don't always agree on capitalization or
incidental whitespace with the config or with each other.

A plain `pandas.Series.eq`/`isin` comparison is exact-match: any casing
difference (e.g. "sales professional" vs "Sales Professional") makes an
employee silently vanish from that role's population - not an error, just
missing from output, with their target/payout looking like "nil" from the
user's perspective (see DEF-022). The helpers below fold to a
case/whitespace-insensitive comparison, but ONLY when both sides being
compared are text - numeric, boolean, and date/datetime comparisons are
returned completely untouched, so this cannot change the meaning of any
non-text filter or condition already in use.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def normalize_for_match(value: Any) -> Any:
    """Fold a scalar to a case/whitespace-insensitive form if it's text."""

    if isinstance(value, str):
        return value.strip().casefold()

    return value


def _is_string_series(series: pd.Series) -> bool:
    return series.dtype == object or pd.api.types.is_string_dtype(series)


def _casefolded(series: pd.Series) -> pd.Series:
    # Deliberately NOT .astype("string") - that promotes to pandas'
    # nullable StringDtype, where None becomes pd.NA and any comparison
    # against pd.NA propagates as <NA> instead of True/False. That would
    # silently change not_equals/not_in semantics for null cells (a None
    # cell should still compare not-equal to a real value, same as plain
    # `series.ne(value)` on object dtype does). Using .str directly on the
    # original object/string series keeps null cells as plain NaN, which
    # `.eq`/`.isin` already treat as False (and `.ne` as True) - matching
    # the exact behavior being replaced here for anything that isn't a
    # genuine case/whitespace difference.
    return series.str.strip().str.casefold()


def flexible_eq(series: pd.Series, value: Any) -> pd.Series:
    """Series == scalar, case/whitespace-insensitive for text values only."""

    if _is_string_series(series) and isinstance(value, str):
        return _casefolded(series).eq(normalize_for_match(value))

    return series.eq(value)


def flexible_isin(series: pd.Series, values: list[Any]) -> pd.Series:
    """Series.isin(values), case/whitespace-insensitive for text values only."""

    if _is_string_series(series) and all(isinstance(v, str) for v in values):
        normalized = [normalize_for_match(v) for v in values]
        return _casefolded(series).isin(normalized)

    return series.isin(values)


def flexible_series_eq(left: pd.Series, right: pd.Series) -> pd.Series:
    """Series == Series, case/whitespace-insensitive when both sides are text."""

    if _is_string_series(left) and _is_string_series(right):
        return _casefolded(left).eq(_casefolded(right))

    return left.eq(right)
