# Known Limitations

This document honestly discloses methodological compromises and data
constraints across the platform, per the project's core principle:
**financial correctness and transparency over polish**. Every limitation
below is also referenced inline in the relevant module's docstring.

## Backtesting (Phase 7)

### 1. Approximated look-ahead-bias guard (not true point-in-time data)
Our data source (yfinance) does not provide real disclosure/publication
dates for financial statements — only `period_end_date` (the fiscal
period covered). To avoid leaking future information into backtests, we
approximate publication timing using a conservative **assumed reporting
lag** (45 days for quarterly results, 60 days for annual — see
`app/backtesting/point_in_time.py::ASSUMED_REPORTING_LAG_DAYS`), modeled
on typical Indian-market disclosure norms (SEBI LODR outer limits).

**Impact:** this is an approximation, not a true point-in-time database.
A real company might disclose earlier or later than our assumed lag,
which could shift exactly which data was "available" on a given backtest
date by a few days to a few weeks in either direction.

### 2. Survivorship bias in the investment universe
Backtests use the **current** Nifty 50 constituent list applied
throughout the historical period, since we don't have historical index
membership data. Companies that were removed from the index (due to
poor performance, delisting, etc.) during the backtest window are
invisible to the backtest, which structurally biases results upward
(only "survivors" are considered).

**Impact:** backtest returns are likely somewhat optimistic relative to
what a real investor following this exact strategy historically would
have experienced, since underperforming companies that dropped out of
the index aren't represented.

### 3. Short data history limits backtest window
Our quarterly financial data only covers **December 2024 onward**
(confirmed via direct query — see project development notes), a
limitation of yfinance's free-tier quarterly statement depth. This
means:
- Backtests cannot meaningfully start before mid-2025 (needs at least
  one full quarter of point-in-time history before the first rebalance).
- Multi-year backtests spanning different market regimes (bull/bear
  cycles, rate environments) are not currently possible with real data.

### 4. Selection scoring is fundamentals-only, not the full live score
The live screener's fundamental score (Phase 2/5) includes a
DCF-derived Valuation component, which requires **live** market price
and shares-outstanding data — data that cannot be retroactively
obtained for arbitrary historical dates via our current data source.
Backtested portfolio selection therefore uses a simpler fundamentals-only
score (Net Margin + annualized ROE), not the full 6-component weighted
score used elsewhere in the platform. See
`app/backtesting/selection.py::_compute_point_in_time_score`.

### 5. Simple equal-weighting, no transaction costs or slippage
The backtest engine assumes equal-weighted positions with no brokerage,
taxes (STT, capital gains), bid-ask spread, or market-impact costs.
Real-world returns from following this exact strategy would be lower
than the backtest results shown, especially for higher-turnover periods.

## General Data Constraints (all phases)

- **Data source:** yfinance only (per project scope — zero paid data
  sources). No proprietary datasets, no direct NSE/BSE bulk data feeds.
- **Quarterly cash-flow gaps:** `operating_cash_flow` and
  `free_cash_flow` are frequently unavailable at the quarterly level in
  yfinance's data (only reliably available annually), limiting
  cash-flow-based analysis at quarterly granularity.
- **Beta from yfinance can be unreliable:** we found yfinance's reported
  `beta` field for at least one company (RELIANCE.NS: 0.16) was
  implausibly low compared to real-world expectations (~1.0-1.3). We now
  self-compute beta from stored price history against a NIFTY 50
  benchmark (`app/risk/returns.py::calculate_beta`) rather than trusting
  the raw field, but this required an extra verification step and is
  worth remembering when interpreting any single company's risk profile.
- **Segment/geography/customer-concentration data:** not available from
  yfinance in structured form; business/industry analysis (Phase 3) is
  therefore descriptive (business summary, sector, employee count) but
  cannot programmatically break down revenue by segment or geography.

## Philosophy

Per the project's strict rules: **never fabricate data**. Every place in
this codebase where a data limitation exists, the code returns `None` or
an explicit "not available" / "pending" status rather than guessing or
silently defaulting to a plausible-looking number. These limitations are
disclosed here, in module docstrings, and (where applicable) directly in
API/UI output — not buried or omitted.

## RAG / Document Retrieval (Phase 8)

### Embedding-based retrieval struggles with numeric-table-adjacent facts
Financial research PDFs frequently place key facts (price target, rating,
CMP) directly adjacent to dense numeric tables (shareholding patterns,
financial summaries). Verified via direct testing: a query for
"price target and rating" scored only 0.312 cosine similarity against
the chunk actually containing "TP: INR665 (+21%) Buy" — moderate-low,
because the surrounding table numbers dilute the chunk's semantic
embedding signal. Pure semantic (embedding-based) search alone is not
fully reliable for pinpointing short factual answers buried in
tabular contexts.

**Mitigation considered but deferred (future enhancement):** a hybrid
retrieval approach — lightweight regex/pattern extraction for
well-structured key fields (price target, rating, CMP) run alongside
semantic search for qualitative/narrative content — would likely
improve reliability for these specific fact types. Not built in this
phase to avoid scope creep; documented here as a known gap.