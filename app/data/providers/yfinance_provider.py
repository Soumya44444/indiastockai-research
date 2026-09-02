import yfinance as yf


def _safe_float(value):
    """Convert a value to float when possible."""
    try:
        if value is None:
            return None

        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_value(df, row_name):
    """
    Return the latest non-null value for a row in a yfinance
    financial statement DataFrame.
    """

    try:
        if df is None or df.empty or row_name not in df.index:
            return None

        row = df.loc[row_name].dropna()

        if row.empty:
            return None

        return _safe_float(row.iloc[0])

    except Exception:
        return None


def _latest_shares(ticker_obj):
    """
    Get the latest available shares outstanding.

    Render does not reliably expose sharesOutstanding through
    Ticker.info, but get_shares_full() works.
    """

    try:
        shares = ticker_obj.get_shares_full()

        if shares is not None and not shares.empty:
            shares = shares.dropna()

            if not shares.empty:
                return _safe_float(shares.iloc[-1])

    except Exception:
        pass

    # Secondary fallback: balance sheet.
    try:
        balance_sheet = ticker_obj.balance_sheet

        shares = _latest_value(
            balance_sheet,
            "Ordinary Shares Number",
        )

        if shares is not None:
            return shares

        shares = _latest_value(
            balance_sheet,
            "Share Issued",
        )

        if shares is not None:
            return shares

    except Exception:
        pass

    return None


def _latest_dividend(ticker_obj):
    """
    Get the latest dividend per share from dividend history.
    """

    try:
        dividends = ticker_obj.dividends

        if dividends is not None and not dividends.empty:
            dividends = dividends.dropna()

            if not dividends.empty:
                return _safe_float(dividends.iloc[-1])

    except Exception:
        pass

    return None


def _calculate_beta(ticker: str):
    """
    Estimate beta from one year of daily returns against
    the NIFTY 50 (^NSEI).

    Returns None if sufficient data is unavailable.
    """

    try:
        stock = yf.Ticker(ticker)

        stock_history = stock.history(
            period="1y",
            interval="1d",
        )

        market = yf.Ticker("^NSEI")

        market_history = market.history(
            period="1y",
            interval="1d",
        )

        if (
            stock_history is None
            or stock_history.empty
            or market_history is None
            or market_history.empty
        ):
            return None

        stock_close = stock_history["Close"].dropna()
        market_close = market_history["Close"].dropna()

        if stock_close.empty or market_close.empty:
            return None

        stock_returns = stock_close.pct_change().dropna()
        market_returns = market_close.pct_change().dropna()

        import pandas as pd

        combined = pd.concat(
            [
                stock_returns.rename("stock"),
                market_returns.rename("market"),
            ],
            axis=1,
            join="inner",
        ).dropna()

        if len(combined) < 60:
            return None

        market_variance = combined["market"].var()

        if market_variance == 0:
            return None

        beta = (
            combined["stock"].cov(combined["market"])
            / market_variance
        )

        return _safe_float(beta)

    except Exception:
        return None


def fetch_company_info(ticker: str) -> dict:
    """
    Fetch basic company information from Yahoo Finance.

    Ticker.info is still used here because these fields are
    descriptive rather than required for valuation calculations.
    """

    t = yf.Ticker(ticker)

    try:
        info = t.info or {}
    except Exception:
        info = {}

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "website": info.get("website"),
        "exchange": info.get("exchange"),
    }


def fetch_business_profile(ticker: str) -> dict:
    """
    Fetch business profile information from Yahoo Finance.
    """

    t = yf.Ticker(ticker)

    try:
        info = t.info or {}
    except Exception:
        info = {}

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "country": info.get("country"),
    }


def fetch_market_data(ticker: str) -> dict:
    """
    Fetch market and valuation data from Yahoo Finance.

    This implementation is designed to work when Yahoo's
    Ticker.info / fast_info endpoints return incomplete data,
    as happens in some deployed environments.

    Data sources:

    - Current price:
        price history

    - Shares outstanding:
        get_shares_full()

    - Market capitalization:
        current price × shares outstanding

    - EPS:
        financial statements

    - P/E:
        current price ÷ diluted EPS

    - Price-to-book:
        market cap ÷ book equity

    - Beta:
        calculated against NIFTY 50 when possible

    - Dividend:
        dividend history

    - Payout ratio:
        latest dividend ÷ diluted EPS

    - Enterprise value:
        market cap + debt - cash

    """

    t = yf.Ticker(ticker)

    current_price = None
    market_cap = None
    shares_outstanding = None

    trailing_pe = None
    price_to_book = None
    enterprise_value = None
    beta = None
    dividend_rate = None
    payout_ratio = None

    # ---------------------------------------------------------
    # 1. Price history
    # ---------------------------------------------------------

    try:
        history = t.history(period="5d")

        if history is not None and not history.empty:
            close = history["Close"].dropna()

            if not close.empty:
                current_price = _safe_float(close.iloc[-1])

    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. Shares outstanding
    # ---------------------------------------------------------

    shares_outstanding = _latest_shares(t)

    # ---------------------------------------------------------
    # 3. Market capitalization
    # ---------------------------------------------------------

    if (
        current_price is not None
        and shares_outstanding is not None
    ):
        try:
            market_cap = (
                current_price
                * shares_outstanding
            )
        except Exception:
            market_cap = None

    # ---------------------------------------------------------
    # 4. Financial statements
    # ---------------------------------------------------------

    try:
        financials = t.financials
    except Exception:
        financials = None

    try:
        balance_sheet = t.balance_sheet
    except Exception:
        balance_sheet = None

    # ---------------------------------------------------------
    # 5. EPS
    #
    # Prefer diluted EPS.
    # ---------------------------------------------------------

    diluted_eps = _latest_value(
        financials,
        "Diluted EPS",
    )

    if diluted_eps is None:
        diluted_eps = _latest_value(
            financials,
            "Basic EPS",
        )

    # ---------------------------------------------------------
    # 6. P/E
    # ---------------------------------------------------------

    if (
        current_price is not None
        and diluted_eps is not None
        and diluted_eps > 0
    ):
        try:
            trailing_pe = (
                current_price
                / diluted_eps
            )
        except Exception:
            trailing_pe = None

    # ---------------------------------------------------------
    # 7. Book equity
    #
    # Prefer stockholders' equity.
    # Fall back to total equity gross minority interest.
    # ---------------------------------------------------------

    book_equity = None

    for row_name in [
        "Stockholders Equity",
        "Common Stock Equity",
        "Total Equity Gross Minority Interest",
    ]:
        book_equity = _latest_value(
            balance_sheet,
            row_name,
        )

        if book_equity is not None:
            break

    # ---------------------------------------------------------
    # 8. Price-to-book
    # ---------------------------------------------------------

    if (
        market_cap is not None
        and book_equity is not None
        and book_equity > 0
    ):
        try:
            price_to_book = (
                market_cap
                / book_equity
            )
        except Exception:
            price_to_book = None

    # ---------------------------------------------------------
    # 9. Debt and cash
    #
    # Build enterprise value ourselves.
    # ---------------------------------------------------------

    total_debt = _latest_value(
        balance_sheet,
        "Total Debt",
    )

    cash_and_investments = _latest_value(
        balance_sheet,
        "Cash Cash Equivalents And Short Term Investments",
    )

    if cash_and_investments is None:
        cash_and_investments = _latest_value(
            balance_sheet,
            "Cash And Cash Equivalents",
        )

    if market_cap is not None:
        try:
            enterprise_value = market_cap

            if total_debt is not None:
                enterprise_value += total_debt

            if cash_and_investments is not None:
                enterprise_value -= cash_and_investments

        except Exception:
            enterprise_value = None

    # ---------------------------------------------------------
    # 10. Beta
    #
    # Ticker.info beta is unavailable on Render, so calculate
    # it from historical returns against NIFTY 50.
    # ---------------------------------------------------------

    beta = _calculate_beta(ticker)

    # ---------------------------------------------------------
    # 11. Dividend
    # ---------------------------------------------------------

    dividend_rate = _latest_dividend(t)

    # ---------------------------------------------------------
    # 12. Payout ratio
    # ---------------------------------------------------------

    if (
        dividend_rate is not None
        and diluted_eps is not None
        and diluted_eps > 0
    ):
        try:
            payout_ratio = (
                dividend_rate
                / diluted_eps
            )
        except Exception:
            payout_ratio = None

    # ---------------------------------------------------------
    # Return normalized data
    # ---------------------------------------------------------

    return {
        "ticker": ticker,
        "current_price": current_price,
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "trailing_pe": trailing_pe,
        "price_to_book": price_to_book,
        "enterprise_value": enterprise_value,
        "beta": beta,
        "dividend_rate": dividend_rate,
        "payout_ratio": payout_ratio,
    }


def fetch_price_history(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
):
    """
    Fetch historical price data from Yahoo Finance.
    """

    t = yf.Ticker(ticker)

    try:
        history = t.history(
            period=period,
            interval=interval,
        )

        return history

    except Exception:
        return None


def fetch_financial_metrics(ticker: str) -> dict:
    """
    Fetch financial metrics from Yahoo Finance.

    Uses financial statements instead of Ticker.info wherever
    possible so the function works in deployed environments.
    """

    t = yf.Ticker(ticker)

    try:
        financials = t.financials
    except Exception:
        financials = None

    try:
        cashflow = t.cashflow
    except Exception:
        cashflow = None

    try:
        balance_sheet = t.balance_sheet
    except Exception:
        balance_sheet = None

    total_revenue = _latest_value(
        financials,
        "Total Revenue",
    )

    gross_profit = _latest_value(
        financials,
        "Gross Profit",
    )

    operating_income = _latest_value(
        financials,
        "Operating Income",
    )

    net_income = _latest_value(
        financials,
        "Net Income",
    )

    ebitda = _latest_value(
        financials,
        "EBITDA",
    )

    free_cash_flow = _latest_value(
        cashflow,
        "Free Cash Flow",
    )

    total_debt = _latest_value(
        balance_sheet,
        "Total Debt",
    )

    cash = _latest_value(
        balance_sheet,
        "Cash Cash Equivalents And Short Term Investments",
    )

    if cash is None:
        cash = _latest_value(
            balance_sheet,
            "Cash And Cash Equivalents",
        )

    debt_to_equity = None

    equity = _latest_value(
        balance_sheet,
        "Stockholders Equity",
    )

    if equity is None:
        equity = _latest_value(
            balance_sheet,
            "Common Stock Equity",
        )

    if (
        total_debt is not None
        and equity is not None
        and equity != 0
    ):
        debt_to_equity = (
            total_debt
            / equity
        )

    operating_margin = None

    if (
        operating_income is not None
        and total_revenue is not None
        and total_revenue != 0
    ):
        operating_margin = (
            operating_income
            / total_revenue
        )

    profit_margin = None

    if (
        net_income is not None
        and total_revenue is not None
        and total_revenue != 0
    ):
        profit_margin = (
            net_income
            / total_revenue
        )

    return {
        "ticker": ticker,
        "total_revenue": total_revenue,
        "revenue_growth": None,
        "gross_profit": gross_profit,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "return_on_equity": None,
        "return_on_assets": None,
        "ebitda": ebitda,
        "free_cash_flow": free_cash_flow,
        "total_cash": cash,
        "total_debt": total_debt,
        "debt_to_equity": debt_to_equity,
        "current_ratio": None,
        "quick_ratio": None,
    }