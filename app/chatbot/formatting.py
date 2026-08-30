"""
Deterministic number formatting for LLM-facing tool output (Phase 9 fix).

CRITICAL BUG PREVENTED: testing showed the LLM (llama3.2) would
misconvert large raw numbers into "trillion/billion" language with real
scale errors (e.g. reporting operating_cash_flow as 10x too large, and
free_cash_flow as 100x too large) even though the underlying tool data
was completely correct. Since the project's core rule is "LLM never
invents financial numbers," letting it do ANY arithmetic/scale
conversion on raw figures is unsafe — even when it's just reformatting
a real number, a conversion error produces a wrong number in the
answer. Fix: format every number into Indian Rupee crore notation
ourselves (deterministic Python), so the LLM only ever copies
already-correct strings into a sentence — it never converts scale itself.
"""

CRORE = 1_00_00_000        # 1 crore = 10,000,000
LAKH_CRORE = CRORE * 1_00_000  # 1 lakh crore = 10^12


def format_inr(value: float | None) -> str:
    """
    Formats a raw rupee figure into Indian numbering convention
    (crore / lakh crore), which is how Indian financial figures are
    conventionally reported — also sidesteps the trillion/billion
    conversion entirely, removing the LLM's opportunity to miscalculate.
    """
    if value is None:
        return "N/A"

    abs_value = abs(value)
    sign = "-" if value < 0 else ""

    if abs_value >= LAKH_CRORE:
        return f"{sign}₹{abs_value / LAKH_CRORE:.2f} lakh crore"
    elif abs_value >= CRORE:
        return f"{sign}₹{abs_value / CRORE:.2f} crore"
    else:
        return f"{sign}₹{abs_value:,.0f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def format_ratio(value: float | None, suffix: str = "x") -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}{suffix}"


# Which formatter applies to which metric name — keeps formatting
# consistent and centralized rather than scattered across call sites.
CURRENCY_METRICS = {
    "revenue", "net_income", "total_assets", "total_equity", "total_debt",
    "operating_cash_flow", "free_cash_flow", "ebitda", "ebit", "gross_profit",
    "interest_expense", "current_assets", "current_liabilities",
    "pretax_income", "tax_provision", "market_cap", "enterprise_value",
}
PERCENT_METRICS = {
    "gross_margin", "ebitda_margin", "net_margin", "roe", "roa", "roce",
    "revenue_cagr_3y", "revenue_yoy", "upside_pct", "margin_of_safety_pct",
}
RATIO_METRICS = {
    "debt_to_equity", "interest_coverage", "current_ratio", "cfo_to_pat",
    "pe_ratio", "ev_ebitda", "price_to_book", "beta",
}


def format_metrics_dict(metrics: dict) -> dict:
    """
    Walks a flat metrics dict and returns a parallel dict of pre-formatted
    display strings, keyed the same way. Unrecognized keys are passed
    through as plain strings (not silently dropped).
    """
    formatted = {}
    for key, value in metrics.items():
        if key in CURRENCY_METRICS:
            formatted[key] = format_inr(value)
        elif key in PERCENT_METRICS:
            formatted[key] = format_percent(value)
        elif key in RATIO_METRICS:
            formatted[key] = format_ratio(value)
        else:
            formatted[key] = str(value)
    return formatted


if __name__ == "__main__":
    # Regression test against the exact real Reliance figures that
    # exposed the LLM's scale-conversion bug.
    test_metrics = {
        "revenue": 10572190000000.0,
        "net_income": 807750000000.0,
        "operating_cash_flow": 1921130000000.0,
        "free_cash_flow": 691970000000.0,
        "ebit": 1472180000000.0,
        "roe": 0.08934991095428249,
        "debt_to_equity": 0.44025087663020035,
    }

    formatted = format_metrics_dict(test_metrics)
    print("Formatted output:")
    for k, v in formatted.items():
        print(f"  {k}: {v}")