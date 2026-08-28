"""
SQLAlchemy models for IndiaStockAI Research Workstation.
Every financial value is stored with full audit metadata:
source, period, publication date, units, and data quality status.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    ForeignKey, UniqueConstraint, Index, Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), unique=True, nullable=False, index=True)  # e.g. RELIANCE.NS
    name = Column(String(200), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    isin = Column(String(20))
    exchange = Column(String(10), default="NSE")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    financial_metrics = relationship("FinancialMetric", back_populates="company")
    prices = relationship("PriceHistory", back_populates="company")
    quality_flags = relationship("DataQualityFlag", back_populates="company")

    def __repr__(self):
        return f"<Company {self.ticker}>"


class FinancialMetric(Base):
    """
    EAV-style table: one row per (company, metric, period).
    Covers income statement, balance sheet, cash flow, and derived ratios.
    """
    __tablename__ = "financial_metrics"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    metric_name = Column(String(100), nullable=False)   # e.g. "revenue", "roe", "gnpa"
    statement_type = Column(String(30))                 # income | balance | cashflow | ratio | sector_specific
    period_type = Column(String(20), nullable=False)     # annual | quarterly | ttm
    period_end_date = Column(Date, nullable=False)       # reporting period end
    publication_date = Column(Date)                      # when this was disclosed/published

    value = Column(Float)
    unit = Column(String(20))                             # INR_CR | PERCENT | RATIO | DAYS etc.

    source = Column(String(100), nullable=False)          # e.g. "yfinance", "screener_upload", "nse_disclosure"
    data_quality_status = Column(String(20), default="ok")  # ok | estimated | missing | flagged
    is_missing = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="financial_metrics")

    __table_args__ = (
        UniqueConstraint(
            "company_id", "metric_name", "period_type", "period_end_date",
            name="uq_metric_period"
        ),
        Index("ix_metric_lookup", "company_id", "metric_name", "period_end_date"),
    )

    def __repr__(self):
        return f"<FinancialMetric {self.metric_name}={self.value} {self.period_end_date}>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    trade_date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)

    source = Column(String(50), default="yfinance")
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("company_id", "trade_date", name="uq_price_date"),
        Index("ix_price_lookup", "company_id", "trade_date"),
    )


class DataQualityFlag(Base):
    """
    Earnings-quality / forensic warning flags (Section 9 of spec).
    Never accusatory — descriptive signals only.
    """
    __tablename__ = "data_quality_flags"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    flag_type = Column(String(50), nullable=False)   # cfo_pat_divergence | weak_fcf | receivables_anomaly | etc.
    period_end_date = Column(Date)
    severity = Column(String(20), default="info")     # info | warning | high
    description = Column(String(500))

    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="quality_flags")