import yfinance as yf


def fetch_company_info(ticker: str) -> dict:
    """
    Fetch basic company information from Yahoo Finance.
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
    Fetch market data from Yahoo Finance.

    Yahoo Finance's Ticker.info and fast_info can return incomplete
    data in deployed environments such as Render.

    Therefore this function uses multiple fallbacks:

    1. Ticker.info
    2. Ticker.fast_info
    3. Price history for current price
    4. get_shares_full() for shares outstanding
    5. Current price × shares outstanding for market cap
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
    # 1. Try Ticker.info
    # ---------------------------------------------------------

    try:
        info = t.info or {}

        current_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
        )

        market_cap = info.get("marketCap")
        shares_outstanding = info.get("sharesOutstanding")
        trailing_pe = info.get("trailingPE")
        price_to_book = info.get("priceToBook")
        enterprise_value = info.get("enterpriseValue")
        beta = info.get("beta")
        dividend_rate = info.get("dividendRate")
        payout_ratio = info.get("payoutRatio")

    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. Try fast_info
    # ---------------------------------------------------------

    try:
        fast_info = t.fast_info

        if current_price is None:
            try:
                current_price = fast_info.get("last_price")
            except Exception:
                pass

        if market_cap is None:
            try:
                market_cap = fast_info.get("market_cap")
            except Exception:
                pass

    except Exception:
        pass

    # ---------------------------------------------------------
    # 3. Current price fallback using price history
    # ---------------------------------------------------------

    if current_price is None:
        try:
            history = t.history(period="5d")

            if history is not None and not history.empty:
                close = history["Close"].dropna()

                if not close.empty:
                    current_price = float(close.iloc[-1])

        except Exception:
            pass

    # ---------------------------------------------------------
    # 4. Shares outstanding fallback
    #
    # Render does not provide sharesOutstanding through
    # Ticker.info, but get_shares_full() works.
    # ---------------------------------------------------------

    if shares_outstanding is None:
        try:
            shares = t.get_shares_full()

            if shares is not None and not shares.empty:
                shares = shares.dropna()

                if not shares.empty:
                    shares_outstanding = float(shares.iloc[-1])

        except Exception:
            pass

    # ---------------------------------------------------------
    # 5. Market cap fallback
    #
    # If Yahoo does not provide market cap directly,
    # calculate it from:
    #
    # Market Cap = Current Price × Shares Outstanding
    # ---------------------------------------------------------

    if (
        market_cap is None
        and current_price is not None
        and shares_outstanding is not None
    ):
        try:
            market_cap = (
                float(current_price)
                * float(shares_outstanding)
            )

        except (TypeError, ValueError):
            pass

    # ---------------------------------------------------------
    # Return normalized market data
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
    """

    t = yf.Ticker(ticker)

    try:
        info = t.info or {}
    except Exception:
        info = {}

    return {
        "ticker": ticker,
        "total_revenue": info.get("totalRevenue"),
        "revenue_growth": info.get("revenueGrowth"),
        "gross_profit": info.get("grossProfits"),
        "operating_margin": info.get("operatingMargins"),
        "profit_margin": info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "return_on_assets": info.get("returnOnAssets"),
        "ebitda": info.get("ebitda"),
        "free_cash_flow": info.get("freeCashflow"),
        "total_cash": info.get("totalCash"),
        "total_debt": info.get("totalDebt"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
    }