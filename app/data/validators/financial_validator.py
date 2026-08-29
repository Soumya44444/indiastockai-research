"""
Validation layer for financial metrics fetched from data providers.
Responsibilities (per project spec Section 4):
  - Correctly classify units (currency vs ratio/percent vs days)
  - Flag suspicious/outlier values without discarding them silently
  - Never fabricate data; missing values are surfaced, not guessed
"""
from datetime import date

# Metric name fragments that indicate a ratio or percentage, not currency.
# yfinance metric names are lowercased+underscored (see provider), so match on that form.
RATIO_KEYWORDS = [
    "rate", "margin", "ratio", "pct", "percent", "yield",
    "roe", "roce", "roa", "eps",  # EPS is per-share currency, but keep isolated below
]
DAYS_KEYWORDS = ["days"]

# EPS is currency-per-share, not a ratio — handle explicitly before the generic ratio check.
PER_SHARE_KEYWORDS = ["eps", "per_share"]

# Plausible bounds for sanity-flagging (not rejecting) values.
RATIO_PLAUSIBLE_RANGE = (-5.0, 5.0)       # e.g. margins/rates rarely outside -500%..500%
CURRENCY_MAGNITUDE_MAX = 5e13              # ~50 trillion — generous upper bound for INR figures


def classify_unit(metric_name: str, raw_unit_guess: str) -> str:
    """
    Decide the correct unit for a metric based on its name.
    Matches whole underscore-separated word-parts only (not substrings),
    so 'operation' doesn't falsely match 'ratio'.
    """
    name_parts = set(metric_name.lower().split("_"))

    if name_parts & set(PER_SHARE_KEYWORDS) or "pershare" in name_parts:
        return f"{raw_unit_guess}_PER_SHARE"
    if name_parts & set(DAYS_KEYWORDS):
        return "DAYS"
    if name_parts & set(RATIO_KEYWORDS):
        return "RATIO"
    return raw_unit_guess


def validate_metric(record: dict) -> dict:
    """
    Takes a single metric record (from a provider) and returns it enriched
    with corrected unit + data_quality_status. Does not mutate the input.
    """
    result = dict(record)
    value = result.get("value")

    corrected_unit = classify_unit(result["metric_name"], result.get("unit", "INR"))
    result["unit"] = corrected_unit

    # Determine quality status
    status = "ok"

    if value is None:
        status = "missing"
    elif corrected_unit == "RATIO" and not (RATIO_PLAUSIBLE_RANGE[0] <= value <= RATIO_PLAUSIBLE_RANGE[1]):
        status = "flagged"  # ratio outside plausible bounds — surfaced, not discarded
    elif corrected_unit not in ("RATIO", "DAYS") and abs(value) > CURRENCY_MAGNITUDE_MAX:
        status = "flagged"  # implausibly large currency figure

    result["data_quality_status"] = status
    result["is_missing"] = (status == "missing")
    return result


def validate_metrics(records: list[dict]) -> list[dict]:
    """Validate a batch of metric records."""
    return [validate_metric(r) for r in records]


def summarize_validation(validated: list[dict]) -> dict:
    """Quick summary counts for logging/audit purposes."""
    summary = {"total": len(validated), "ok": 0, "flagged": 0, "missing": 0}
    for r in validated:
        summary[r["data_quality_status"]] = summary.get(r["data_quality_status"], 0) + 1
    return summary


if __name__ == "__main__":
    # Quick manual test using real data
    from app.data.providers.yfinance_provider import fetch_financial_metrics

    ticker = "RELIANCE.NS"
    raw_metrics = fetch_financial_metrics(ticker)
    validated = validate_metrics(raw_metrics)

    print(f"Validated {len(validated)} metrics for {ticker}")
    print("Summary:", summarize_validation(validated))

    print("\nSample RATIO-classified metrics:")
    ratio_samples = [r for r in validated if r["unit"] == "RATIO"][:5]
    for r in ratio_samples:
        print(" ", r["metric_name"], "=", r["value"], r["unit"], r["data_quality_status"])

    flagged = [r for r in validated if r["data_quality_status"] == "flagged"]
    print(f"\nFlagged records: {len(flagged)}")
    for r in flagged[:5]:
        print(" ", r["metric_name"], "=", r["value"], r["unit"])