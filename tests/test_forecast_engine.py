"""Unit tests for the forecast engine's core projection logic
(app/forecasting/forecast_engine.py)."""
import pytest
from app.forecasting.forecast_engine import _project_scenario


class TestProjectScenario:
    def test_revenue_grows_correctly(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=3,
        )
        assert result[0]["revenue"] == pytest.approx(1100.0)
        assert result[1]["revenue"] == pytest.approx(1210.0)
        assert result[2]["revenue"] == pytest.approx(1331.0)

    def test_ebitda_uses_margin(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=1,
        )
        assert result[0]["ebitda"] == pytest.approx(1100.0 * 0.20)

    def test_ebit_equals_ebitda_minus_da(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.0, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=1,
        )
        expected_ebitda = 1000.0 * 0.20
        expected_da = 1000.0 * 0.05
        assert result[0]["ebit"] == pytest.approx(expected_ebitda - expected_da)

    def test_missing_da_pct_leaves_ebit_none(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=None, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=1,
        )
        assert result[0]["ebit"] is None
        assert result[0]["pat"] is None  # PAT depends on EBIT

    def test_working_capital_increase_is_positive_for_growing_revenue(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=1,
        )
        # Revenue grew 1000 -> 1100, so working capital (5% of revenue) also
        # grew: (1100*0.05) - (1000*0.05) = 5.0
        assert result[0]["working_capital_increase"] == pytest.approx(5.0)

    def test_working_capital_increase_none_when_wc_pct_missing(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=None, years=1,
        )
        assert result[0]["working_capital_increase"] is None

    def test_fcf_nets_out_working_capital_increase(self):
        with_wc = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=1,
        )
        without_wc = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.10, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=None, years=1,
        )
        # FCF with WC accounted for should be lower by exactly the WC increase
        wc_increase = with_wc[0]["working_capital_increase"]
        assert with_wc[0]["fcf"] == pytest.approx(without_wc[0]["fcf"] - wc_increase)

    def test_negative_ebit_does_not_produce_negative_tax_benefit_in_fcf(self):
        # A loss-making scenario shouldn't add a "tax credit" to FCF —
        # max(tax_amount, 0) in the source guards against this.
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.0, ebitda_margin=0.02,
            da_pct_revenue=0.10, tax_rate=0.25, capex_pct_revenue=0.05,
            wc_pct_revenue=0.0, years=1,
        )
        assert result[0]["ebit"] < 0  # confirm this test scenario is actually a loss
        # FCF = EBITDA - max(tax,0) - capex; with negative EBIT, tax floor is 0
        expected_fcf = result[0]["ebitda"] - 0 - (1000.0 * 0.05)
        assert result[0]["fcf"] == pytest.approx(expected_fcf)

    def test_multi_year_projection_length(self):
        result = _project_scenario(
            base_revenue=1000.0, revenue_growth=0.05, ebitda_margin=0.20,
            da_pct_revenue=0.05, tax_rate=0.25, capex_pct_revenue=0.08,
            wc_pct_revenue=0.05, years=5,
        )
        assert len(result) == 5
        assert [y["year"] for y in result] == [1, 2, 3, 4, 5]