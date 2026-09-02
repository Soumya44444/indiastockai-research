"""
DCF valuation engine (project spec Section 13).

WACC (CAPM cost of equity + post-tax cost of debt)
-> Discount Bear/Base/Bull FCF
-> Enterprise Value
-> Equity Value
-> Fair Value per Share.

The engine uses:

    Net Debt = Total Debt - Cash & Cash Equivalents /
               Short-Term Investments

Cash is included because enterprise value represents the
value of the operating business, while equity value also
belongs to shareholders' cash holdings.

Macro assumptions are disclosed constants representative
of the Indian market context and should be revisited
periodically.
"""

from sqlalchemy.orm import Session

from app.data.models import Company
from app.data.providers.yfinance_provider import fetch_market_data
from app.screener.metric_aggregator import get_latest_metrics_bulk
from app.forecasting.forecast_engine import generate_forecast


# ---------------------------------------------------------
# Macro assumptions
# ---------------------------------------------------------

RISK_FREE_RATE = 0.068
EQUITY_RISK_PREMIUM = 0.065

DEFAULT_TERMINAL_GROWTH = 0.04

DEFAULT_BETA_IF_MISSING = 1.0


# ---------------------------------------------------------
# WACC
# ---------------------------------------------------------

def calculate_wacc(
    session: Session,
    company: Company,
) -> dict:
    """
    Calculate WACC.

    WACC =
        (E/V × Cost of Equity)
        +
        (D/V × Cost of Debt × (1 - Tax Rate))

    Cost of Equity via CAPM:

        Rf + Beta × ERP
    """

    market = fetch_market_data(company.ticker)

    metrics = get_latest_metrics_bulk(
        session,
        company.id,
    )

    # -----------------------------------------------------
    # Beta
    # -----------------------------------------------------

    beta = market.get("beta")

    beta_used = (
        beta
        if beta is not None
        else DEFAULT_BETA_IF_MISSING
    )

    # -----------------------------------------------------
    # Cost of equity
    # -----------------------------------------------------

    cost_of_equity = (
        RISK_FREE_RATE
        + beta_used * EQUITY_RISK_PREMIUM
    )

    # -----------------------------------------------------
    # Capital structure
    # -----------------------------------------------------

    market_cap = market.get("market_cap")

    total_debt = (
        market.get("total_debt")
        if market.get("total_debt") is not None
        else metrics.get("total_debt")
    )

    total_debt = total_debt or 0.0

    # -----------------------------------------------------
    # Tax rate
    # -----------------------------------------------------

    interest_expense = metrics.get(
        "interest_expense"
    )

    pretax_income = metrics.get(
        "pretax_income"
    )

    tax_provision = metrics.get(
        "tax_provision"
    )

    tax_rate = None

    if (
        pretax_income
        and tax_provision is not None
        and pretax_income != 0
    ):
        tax_rate = max(
            min(
                tax_provision / pretax_income,
                0.5,
            ),
            0.0,
        )

    if tax_rate is None:
        tax_rate = 0.25

    # -----------------------------------------------------
    # Cost of debt
    # -----------------------------------------------------

    cost_of_debt = None

    if interest_expense and total_debt:
        cost_of_debt = (
            abs(interest_expense)
            / total_debt
        )

    # -----------------------------------------------------
    # Market cap validation
    # -----------------------------------------------------

    if market_cap is None or market_cap <= 0:
        return {
            "available": False,
            "reason": (
                "Market cap unavailable — "
                "cannot weight WACC."
            ),
        }

    # -----------------------------------------------------
    # Capital weights
    # -----------------------------------------------------

    total_capital = (
        market_cap
        + total_debt
    )

    if total_capital <= 0:
        return {
            "available": False,
            "reason": (
                "Total capital unavailable — "
                "cannot calculate WACC."
            ),
        }

    equity_weight = (
        market_cap
        / total_capital
    )

    debt_weight = (
        total_debt
        / total_capital
    )

    # -----------------------------------------------------
    # WACC
    # -----------------------------------------------------

    if cost_of_debt is not None:

        wacc = (
            equity_weight
            * cost_of_equity
            +
            debt_weight
            * cost_of_debt
            * (1 - tax_rate)
        )

    else:

        # No debt or no interest data.
        # WACC collapses to cost of equity.
        wacc = cost_of_equity

    return {
        "available": True,
        "wacc": wacc,
        "cost_of_equity": cost_of_equity,
        "cost_of_debt": cost_of_debt,
        "beta_used": beta_used,
        "beta_was_estimated": beta is None,
        "tax_rate_used": tax_rate,
        "equity_weight": equity_weight,
        "debt_weight": debt_weight,
        "risk_free_rate": RISK_FREE_RATE,
        "equity_risk_premium": EQUITY_RISK_PREMIUM,
    }


# ---------------------------------------------------------
# DCF discounting
# ---------------------------------------------------------

def _discount_fcf_series(
    fcf_by_year: list[float],
    wacc: float,
    terminal_growth: float,
) -> dict:
    """
    Present-value each year's FCF and add a Gordon Growth
    terminal value.

    WACC must be greater than terminal growth.
    """

    if wacc <= terminal_growth:
        return {
            "available": False,
            "reason": (
                f"WACC ({wacc:.1%}) must exceed "
                f"terminal growth ({terminal_growth:.1%}) "
                "for a valid DCF."
            ),
        }

    if not fcf_by_year:
        return {
            "available": False,
            "reason": "No FCF projections available.",
        }

    pv_explicit = 0.0

    for year, fcf in enumerate(
        fcf_by_year,
        start=1,
    ):
        pv_explicit += (
            fcf
            / ((1 + wacc) ** year)
        )

    final_year_fcf = fcf_by_year[-1]

    terminal_value = (
        final_year_fcf
        * (1 + terminal_growth)
        / (wacc - terminal_growth)
    )

    pv_terminal = (
        terminal_value
        / (
            (1 + wacc)
            ** len(fcf_by_year)
        )
    )

    enterprise_value = (
        pv_explicit
        + pv_terminal
    )

    return {
        "available": True,
        "pv_explicit_fcf": pv_explicit,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "enterprise_value": enterprise_value,
        "terminal_value_pct_of_ev": (
            pv_terminal / enterprise_value
            if enterprise_value
            else None
        ),
    }


# ---------------------------------------------------------
# Full DCF
# ---------------------------------------------------------

def run_dcf(
    session: Session,
    company: Company,
    years: int = 3,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
) -> dict:
    """
    Full DCF:

        WACC
        -> Forecast
        -> Discount FCF
        -> Enterprise Value
        -> Net Debt adjustment
        -> Equity Value
        -> Fair Value per Share
    """

    # -----------------------------------------------------
    # 1. WACC
    # -----------------------------------------------------

    wacc_result = calculate_wacc(
        session,
        company,
    )

    if not wacc_result["available"]:
        return {
            "available": False,
            "reason": wacc_result["reason"],
        }

    # -----------------------------------------------------
    # 2. Forecast
    # -----------------------------------------------------

    forecast = generate_forecast(
        session,
        company.id,
        years=years,
    )

    if not forecast["available"]:
        return {
            "available": False,
            "reason": forecast["reason"],
        }

    # -----------------------------------------------------
    # 3. Market data
    # -----------------------------------------------------

    market = fetch_market_data(
        company.ticker
    )

    shares_outstanding = market.get(
        "shares_outstanding"
    )

    if not shares_outstanding:
        return {
            "available": False,
            "reason": (
                "Shares outstanding unavailable — "
                "cannot compute per-share value."
            ),
        }

    # -----------------------------------------------------
    # 4. Debt
    # -----------------------------------------------------

    total_debt = market.get(
        "total_debt"
    )

    if total_debt is None:

        metrics = get_latest_metrics_bulk(
            session,
            company.id,
        )

        total_debt = (
            metrics.get("total_debt")
            or 0.0
        )

    # -----------------------------------------------------
    # 5. Cash
    # -----------------------------------------------------

    cash_and_investments = market.get(
        "cash_and_investments"
    )

    if cash_and_investments is None:

        metrics = get_latest_metrics_bulk(
            session,
            company.id,
        )

        cash_and_investments = (
            metrics.get("total_cash")
            or 0.0
        )

    # -----------------------------------------------------
    # 6. TRUE NET DEBT
    # -----------------------------------------------------
    #
    # Net Debt = Total Debt - Cash
    #
    # Negative net debt is allowed because a company can
    # have more cash than debt.
    # -----------------------------------------------------

    net_debt = (
        total_debt
        - cash_and_investments
    )

    # -----------------------------------------------------
    # 7. Scenario DCFs
    # -----------------------------------------------------

    results = {}

    for scenario_name, years_data in forecast[
        "forecasts"
    ].items():

        fcf_series = [
            year_data["fcf"]
            for year_data in years_data
        ]

        if any(
            f is None
            for f in fcf_series
        ):
            results[scenario_name] = {
                "available": False,
                "reason": (
                    "Incomplete FCF projection "
                    "for this scenario."
                ),
            }

            continue

        dcf = _discount_fcf_series(
            fcf_series,
            wacc_result["wacc"],
            terminal_growth,
        )

        if not dcf["available"]:
            results[scenario_name] = dcf
            continue

        # -------------------------------------------------
        # Enterprise Value -> Equity Value
        # -------------------------------------------------

        equity_value = (
            dcf["enterprise_value"]
            - net_debt
        )

        fair_value_per_share = (
            equity_value
            / shares_outstanding
        )

        results[scenario_name] = {
            "available": True,
            "enterprise_value": (
                dcf["enterprise_value"]
            ),
            "equity_value": equity_value,
            "fair_value_per_share": (
                fair_value_per_share
            ),
            "terminal_value_pct_of_ev": (
                dcf["terminal_value_pct_of_ev"]
            ),
        }

    # -----------------------------------------------------
    # 8. Methodology note
    # -----------------------------------------------------

    beta_note = ""

    if wacc_result["beta_was_estimated"]:
        beta_note = (
            " (estimated, not available from data source)"
        )

    methodology_note = (
        f"WACC = {wacc_result['wacc']:.1%} "
        f"(Cost of Equity "
        f"{wacc_result['cost_of_equity']:.1%} "
        f"via CAPM "
        f"[Rf={RISK_FREE_RATE:.1%}, "
        f"Beta={wacc_result['beta_used']:.2f}"
        f"{beta_note}, "
        f"ERP={EQUITY_RISK_PREMIUM:.1%}]). "
        f"Terminal growth "
        f"{terminal_growth:.1%}. "
        f"Net debt = total debt "
        f"({total_debt:,.0f}) "
        f"- cash/investments "
        f"({cash_and_investments:,.0f}) "
        f"= {net_debt:,.0f}."
    )

    # -----------------------------------------------------
    # 9. Return
    # -----------------------------------------------------

    return {
        "available": True,

        "wacc_breakdown": wacc_result,

        "terminal_growth_used": terminal_growth,

        "total_debt_used": total_debt,

        "cash_and_investments_used": (
            cash_and_investments
        ),

        "net_debt_used": net_debt,

        "shares_outstanding": (
            shares_outstanding
        ),

        "current_price": market.get(
            "current_price"
        ),

        "scenarios": results,

        "methodology_note": methodology_note,
    }


# ---------------------------------------------------------
# Local test
# ---------------------------------------------------------

if __name__ == "__main__":

    from app.data.db import SessionLocal

    session = SessionLocal()

    try:

        company = (
            session.query(Company)
            .filter_by(
                ticker="RELIANCE.NS"
            )
            .first()
        )

        if not company:

            print(
                "RELIANCE.NS not found"
            )

        else:

            result = run_dcf(
                session,
                company,
                years=3,
            )

            print(
                f"DCF Valuation: "
                f"{company.name}\n"
            )

            if not result["available"]:

                print(
                    f"NOT AVAILABLE: "
                    f"{result['reason']}"
                )

            else:

                print(
                    f"Current Price: "
                    f"{result['current_price']}"
                )

                print(
                    f"Shares Outstanding: "
                    f"{result['shares_outstanding']:,.0f}"
                )

                print(
                    f"Total Debt Used: "
                    f"{result['total_debt_used']:,.0f}"
                )

                print(
                    f"Cash & Investments Used: "
                    f"{result['cash_and_investments_used']:,.0f}"
                )

                print(
                    f"Net Debt Used: "
                    f"{result['net_debt_used']:,.0f}"
                )

                print(
                    f"\n"
                    f"{result['methodology_note']}"
                    f"\n"
                )

                for scenario, vals in result[
                    "scenarios"
                ].items():

                    if not vals["available"]:

                        print(
                            f"[{scenario.upper()}] "
                            f"NOT AVAILABLE: "
                            f"{vals['reason']}"
                        )

                        continue

                    print(
                        f"[{scenario.upper()}] "
                        f"Fair Value/Share: "
                        f"{vals['fair_value_per_share']:,.2f} "
                        f"(EV="
                        f"{vals['enterprise_value']:,.0f}, "
                        f"Equity Value="
                        f"{vals['equity_value']:,.0f}, "
                        f"Terminal Value%="
                        f"{vals['terminal_value_pct_of_ev']:.1%})"
                    )

    finally:

        session.close()