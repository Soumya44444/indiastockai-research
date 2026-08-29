"""
Custom filter engine for Analyst Mode (project spec Section 5: "Custom
filters supported (Analyst Mode)").

A filter is a list of conditions, each: {"field": str, "operator": str, "value": Any}.
Supported operators: >=, <=, >, <, ==, !=
Supported fields: any key present in a company profile dict (see
screener/presets.py's build_company_profile) — e.g. roe, debt_to_equity,
net_margin, revenue_cagr_3y, fundamental_score, sector.

Missing data (None) never silently passes or fails a numeric condition —
it's reported as "unknown", same transparency principle as the presets.
"""
import operator as op
from sqlalchemy.orm import Session
from app.data.models import Company
from app.screener.presets import build_company_profile

OPERATORS = {
    ">=": op.ge,
    "<=": op.le,
    ">": op.gt,
    "<": op.lt,
    "==": op.eq,
    "!=": op.ne,
}


def _evaluate_condition(profile: dict, condition: dict) -> dict:
    field = condition["field"]
    operator_str = condition["operator"]
    target_value = condition["value"]

    if operator_str not in OPERATORS:
        raise ValueError(f"Unsupported operator: {operator_str}. Use one of {list(OPERATORS.keys())}")

    actual_value = profile.get(field)
    label = f"{field} {operator_str} {target_value}"

    if actual_value is None:
        return {"criterion": label, "status": "unknown", "detail": f"{field}=None (missing data)"}

    try:
        passed = OPERATORS[operator_str](actual_value, target_value)
    except TypeError:
        # e.g. comparing string sector with a numeric operator by mistake
        return {"criterion": label, "status": "unknown", "detail": f"type mismatch: {field}={actual_value!r}"}

    status = "passed" if passed else "failed"
    return {"criterion": label, "status": status, "detail": f"{field}={actual_value}"}


def run_custom_filter(session: Session, conditions: list[dict]) -> list[dict]:
    """
    Runs a custom filter (list of conditions, ALL must pass) across every
    company in the database. Returns the same shape as run_preset() for
    consistency with the beginner presets.
    """
    companies = session.query(Company).all()
    results = []

    for company in companies:
        profile = build_company_profile(session, company)
        criteria_results = [_evaluate_condition(profile, c) for c in conditions]
        matched = all(c["status"] == "passed" for c in criteria_results)

        results.append({
            "ticker": profile["ticker"],
            "name": profile["name"],
            "sector": profile["sector"],
            "matched": matched,
            "fundamental_score": profile["fundamental_score"],
            "criteria": criteria_results,
        })

    results.sort(key=lambda r: (not r["matched"], -(r["fundamental_score"] or 0)))
    return results


if __name__ == "__main__":
    import time
    from app.data.db import SessionLocal

    session = SessionLocal()

    # Example custom filter: high-quality, low-leverage IT companies
    custom_conditions = [
        {"field": "roe", "operator": ">=", "value": 0.15},
        {"field": "debt_to_equity", "operator": "<=", "value": 0.3},
        {"field": "net_margin", "operator": ">=", "value": 0.10},
    ]

    print("Running custom filter: ROE>=15%, D/E<=0.3, Net Margin>=10%\n")
    start = time.time()
    results = run_custom_filter(session, custom_conditions)
    elapsed = time.time() - start

    matched_count = sum(1 for r in results if r["matched"])
    print(f"{matched_count} / {len(results)} companies matched (took {elapsed:.1f}s)\n")

    for r in results[:10]:
        status = "MATCH" if r["matched"] else "no match"
        print(f"[{status}] {r['ticker']} — {r['name']} (score={r['fundamental_score']})")
        for c in r["criteria"]:
            print(f"    {c['status']:8s} {c['criterion']} ({c['detail']})")

    session.close()