import numpy as np
import pandas as pd

from benchmark_replication import month_end_rebalance_dates
from cost_utils import ETF_OFFICIAL_COSTS, calc_rebalance_cost_from_weight_change, daily_expense_rate
from performance import performance_summary
from project_paths import MODEL_PANEL_FILE, OUTPUT_DIR, ensure_output_dir
from strategy_factor_diagnostics import build_exhaustive_ic_monthly, build_exhaustive_candidate_source
from strategy_ic_selected import (
    PARAMS as IC_PARAMS,
    SELECTED_FACTOR_SPECS,
    _apply_turnover_limit,
    _benchmark_weights,
    _build_selected_score,
    _normalize_factor_weights,
    _score_to_target,
)


WALK_FORWARD_PARAMS = {
    "ic_lookback_months": 12,
    "min_training_months": 12,
    "min_family_observations": 12,
    "min_hit_ratio": 0.50,
    "require_positive_top_minus_bottom": True,
    "benchmark_weight_column": "etf_weight_pct",
    "individual_active_limit": 0.035,
    "active_budget": 0.10,
    "individual_max_weight": 0.30,
    "one_way_turnover_limit": 0.10,
    "cost_scenario": "base",
    "annual_fund_expense_rate": ETF_OFFICIAL_COSTS["annual_total_fee_expense_rate"],
    "active_risk_target_te": None,
    "active_risk_lookback_days": 120,
    "active_risk_min_observations": 60,
    "liquidity_scaling": False,
    "liquidity_scaling_floor": 0.40,
}


FAMILY_MAP = {}
for spec in SELECTED_FACTOR_SPECS:
    FAMILY_MAP.setdefault(spec["theme"], []).append(spec["factor"])


def _family_training_stats(
    monthly_ic: pd.DataFrame,
    rebalance_date: pd.Timestamp,
    lookback_months: int,
    min_training_months: int,
) -> pd.DataFrame:
    monthly_ic = monthly_ic.copy()
    monthly_ic["date"] = pd.to_datetime(monthly_ic["date"], errors="coerce")
    prior_dates = sorted(monthly_ic.loc[monthly_ic["date"] < rebalance_date, "date"].dropna().unique())
    train_dates = prior_dates[-lookback_months:]
    rows = []
    enough_history = len(train_dates) >= min_training_months
    for family, factors in FAMILY_MAP.items():
        g = monthly_ic[monthly_ic["date"].isin(train_dates) & monthly_ic["factor"].isin(factors)].copy()
        ic = pd.to_numeric(g["ic"], errors="coerce").dropna()
        tmb = pd.to_numeric(g["top_minus_bottom_return"], errors="coerce").dropna()
        mean_ic = float(ic.mean()) if len(ic) else np.nan
        hit = float((ic > 0).mean()) if len(ic) else np.nan
        mean_tmb = float(tmb.mean()) if len(tmb) else np.nan
        rows.append(
            {
                "date": rebalance_date,
                "factor_family": family,
                "training_start_date": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d") if train_dates else "",
                "training_end_date": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d") if train_dates else "",
                "training_month_count": len(train_dates),
                "training_observations": int(len(ic)),
                "training_mean_ic": mean_ic,
                "training_median_ic": float(ic.median()) if len(ic) else np.nan,
                "training_hit_ratio_ic_positive": hit,
                "training_mean_top_minus_bottom_return": mean_tmb,
                "training_hit_ratio_top_minus_bottom_positive": float((tmb > 0).mean()) if len(tmb) else np.nan,
                "enough_history": enough_history,
            }
        )
    return pd.DataFrame(rows)


def _attach_realized_next_month_stats(validation: pd.DataFrame, monthly_ic: pd.DataFrame) -> pd.DataFrame:
    monthly_ic = monthly_ic.copy()
    monthly_ic["date"] = pd.to_datetime(monthly_ic["date"], errors="coerce")
    rows = []
    for _, row in validation.iterrows():
        family = row["factor_family"]
        factors = FAMILY_MAP.get(family, [])
        g = monthly_ic[
            monthly_ic["date"].eq(pd.Timestamp(row["date"])) & monthly_ic["factor"].isin(factors)
        ].copy()
        ic = pd.to_numeric(g["ic"], errors="coerce").dropna()
        tmb = pd.to_numeric(g["top_minus_bottom_return"], errors="coerce").dropna()
        rows.append(
            {
                "realized_next_month_mean_ic": float(ic.mean()) if len(ic) else np.nan,
                "realized_next_month_hit_ratio_ic_positive": float((ic > 0).mean()) if len(ic) else np.nan,
                "realized_next_month_mean_top_minus_bottom_return": float(tmb.mean()) if len(tmb) else np.nan,
                "realized_next_month_factor_count": int(g["factor"].nunique()),
            }
        )
    return pd.concat([validation.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _select_families(row_df: pd.DataFrame, params: dict) -> list[str]:
    selected = []
    for row in row_df.itertuples():
        passes = (
            bool(row.enough_history)
            and row.training_observations >= int(params["min_family_observations"])
            and pd.notna(row.training_mean_ic)
            and row.training_mean_ic > 0
            and pd.notna(row.training_hit_ratio_ic_positive)
            and row.training_hit_ratio_ic_positive > float(params["min_hit_ratio"])
        )
        if params.get("require_positive_top_minus_bottom", True):
            passes = passes and pd.notna(row.training_mean_top_minus_bottom_return) and row.training_mean_top_minus_bottom_return > 0
        if passes:
            selected.append(row.factor_family)
    return selected


def build_walk_forward_factor_validation(panel: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    params = {**WALK_FORWARD_PARAMS, **(params or {})}
    monthly_ic = build_exhaustive_ic_monthly(panel)
    monthly_ic["date"] = pd.to_datetime(monthly_ic["date"], errors="coerce")
    dates = pd.DatetimeIndex(sorted(panel["date"].dropna().unique()))
    rebalance_dates = sorted(set(month_end_rebalance_dates(dates)))
    frames = []
    for date in rebalance_dates:
        stats = _family_training_stats(
            monthly_ic,
            pd.Timestamp(date),
            int(params["ic_lookback_months"]),
            int(params["min_training_months"]),
        )
        selected = _select_families(stats, params)
        stats["selected_for_next_month"] = stats["factor_family"].isin(selected)
        stats["selected_family_count"] = len(selected)
        stats["selection_rule"] = (
            f"prior {params['ic_lookback_months']} IC months; mean IC > 0; "
            f"hit ratio > {params['min_hit_ratio']:.0%}; top-minus-bottom > 0"
        )
        frames.append(stats)
    validation = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not validation.empty:
        validation = _attach_realized_next_month_stats(validation, monthly_ic)
    return validation


def _selected_specs_for_date(wf_validation: pd.DataFrame, date: pd.Timestamp) -> list[dict]:
    selected_families = wf_validation[
        wf_validation["date"].eq(pd.Timestamp(date)) & wf_validation["selected_for_next_month"]
    ]["factor_family"].tolist()
    specs = [spec for spec in SELECTED_FACTOR_SPECS if spec["theme"] in selected_families]
    return _normalize_factor_weights(specs) if specs else []


def _normalize_long_only(w: pd.Series, max_weight: float | None = None) -> pd.Series:
    x = pd.to_numeric(w, errors="coerce").fillna(0.0).clip(lower=0.0)
    if max_weight is not None:
        x = x.clip(upper=float(max_weight))
    total = float(x.sum())
    if total <= 0:
        return x
    return x / total


def _apply_liquidity_scaling(
    raw_target: pd.Series,
    base: pd.Series,
    g: pd.DataFrame,
    floor: float,
    max_weight: float,
) -> tuple[pd.Series, dict]:
    if "trading_value" not in g.columns:
        return raw_target, {"liquidity_scaling_applied": False, "average_liquidity_multiplier": np.nan}
    liq = pd.to_numeric(g.set_index("stock_code")["trading_value"], errors="coerce").reindex(raw_target.index)
    if liq.notna().sum() < 3:
        return raw_target, {"liquidity_scaling_applied": False, "average_liquidity_multiplier": np.nan}
    rank = liq.rank(pct=True).fillna(0.5)
    multiplier = rank.clip(lower=float(floor), upper=1.0)
    active = raw_target.reindex(base.index, fill_value=0.0) - base
    target = base + active * multiplier.reindex(base.index, fill_value=0.5)
    target = _normalize_long_only(target, max_weight=max_weight)
    return target.sort_index(), {
        "liquidity_scaling_applied": True,
        "average_liquidity_multiplier": float(multiplier.mean()),
    }


def _active_covariance(
    return_mat: pd.DataFrame,
    date: pd.Timestamp,
    universe: pd.Index,
    lookback_days: int,
    min_observations: int,
) -> pd.DataFrame:
    hist = return_mat.loc[return_mat.index < date, universe].tail(int(lookback_days))
    valid_counts = hist.notna().sum()
    sparse = valid_counts < int(min_observations)
    hist = hist.loc[:, ~sparse]
    if hist.shape[1] < 2:
        return pd.DataFrame(index=universe, columns=universe, dtype=float)
    cov = hist.cov() * 252.0
    diag = pd.Series(np.diag(cov), index=cov.index).replace([np.inf, -np.inf], np.nan)
    fill_var = float(diag.dropna().median()) if diag.notna().any() else 0.10
    cov = cov.reindex(index=universe, columns=universe)
    for code in universe:
        if pd.isna(cov.loc[code, code]) or cov.loc[code, code] <= 0:
            cov.loc[code, code] = fill_var
    cov = cov.fillna(0.0)
    jitter = max(float(np.nanmean(np.diag(cov.values))) * 1e-6, 1e-10)
    cov = cov + np.eye(len(cov)) * jitter
    return pd.DataFrame(cov, index=universe, columns=universe)


def _apply_active_risk_target(
    raw_target: pd.Series,
    base: pd.Series,
    cov: pd.DataFrame,
    target_te: float | None,
    max_weight: float,
) -> tuple[pd.Series, dict]:
    if target_te is None or cov.empty:
        return raw_target, {
            "active_risk_target_te": target_te,
            "expected_active_te_before_scale": np.nan,
            "active_risk_scale": 1.0,
            "active_risk_target_applied": False,
        }
    idx = base.index.union(raw_target.index)
    b = base.reindex(idx, fill_value=0.0)
    t = raw_target.reindex(idx, fill_value=0.0)
    cov = cov.reindex(index=idx, columns=idx).fillna(0.0)
    active = t - b
    variance = float(active.values @ cov.values @ active.values)
    expected_te = float(np.sqrt(max(variance, 0.0)))
    if expected_te > float(target_te) and expected_te > 0:
        scale = float(target_te) / expected_te
        target = b + active * scale
        target = _normalize_long_only(target, max_weight=max_weight)
        applied = True
    else:
        scale = 1.0
        target = t
        applied = False
    return target.sort_index(), {
        "active_risk_target_te": target_te,
        "expected_active_te_before_scale": expected_te,
        "active_risk_scale": scale,
        "active_risk_target_applied": applied,
    }


def run_walk_forward_strategy(
    panel: pd.DataFrame,
    wf_validation: pd.DataFrame,
    params: dict | None = None,
) -> dict[str, pd.DataFrame]:
    params = {**WALK_FORWARD_PARAMS, **(params or {})}
    source = build_exhaustive_candidate_source(panel.copy())
    source["stock_code"] = source["stock_code"].astype(str).str.zfill(6)
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])

    dates = pd.DatetimeIndex(sorted(source["date"].dropna().unique()))
    rebalance_dates = sorted(set(month_end_rebalance_dates(dates)))
    rebalance_set = set(rebalance_dates)
    first_oos = wf_validation.loc[wf_validation["enough_history"], "date"].min()

    return_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    benchmark_returns = pd.read_csv(OUTPUT_DIR / "benchmark_pdf_returns.csv", parse_dates=["date"]).set_index("date")[
        "pdf_return"
    ]

    current = pd.Series(dtype=float)
    rows = []
    weight_rows = []
    turnover_rows = []
    signal_rows = []
    daily_fund_cost = daily_expense_rate(params["annual_fund_expense_rate"])

    for date in dates:
        if pd.notna(first_oos) and date < first_oos:
            continue

        port_ret = np.nan
        if not current.empty and date in return_mat.index:
            ret = pd.to_numeric(return_mat.loc[date], errors="coerce").reindex(current.index).fillna(0.0)
            port_ret = float((current * ret).sum())
            denom = 1.0 + port_ret
            if denom != 0:
                current = current * (1.0 + ret) / denom

        trading_cost = 0.0
        selected_families = []
        is_rebalance = date in rebalance_set
        turnover_info = {
            "desired_turnover_before_limit": 0.0,
            "turnover_limit": float(params["one_way_turnover_limit"]),
            "turnover_blend_ratio": 1.0,
            "realized_turnover_after_limit": 0.0,
            "turnover_was_binding": False,
            "traded_weight_after_limit": 0.0,
            "active_risk_target_te": params.get("active_risk_target_te"),
            "expected_active_te_before_scale": np.nan,
            "active_risk_scale": 1.0,
            "active_risk_target_applied": False,
            "liquidity_scaling_applied": False,
            "average_liquidity_multiplier": np.nan,
        }

        g = source[source["date"].eq(date)].copy()
        if g.empty:
            continue
        base = _benchmark_weights(g, params["benchmark_weight_column"])

        if is_rebalance:
            specs = _selected_specs_for_date(wf_validation, date)
            selected_families = sorted({spec["theme"] for spec in specs})
            if specs:
                diagnostics, score, coverage = _build_selected_score(g, specs)
                raw_target, raw_active = _score_to_target(
                    base,
                    score,
                    float(params["individual_active_limit"]),
                    float(params["active_budget"]),
                    float(params["individual_max_weight"]),
                )
            else:
                diagnostics = pd.DataFrame(index=base.index)
                score = pd.Series(0.0, index=base.index)
                coverage = pd.Series(0.0, index=base.index)
                raw_target = base.copy()
                raw_active = raw_target - base

            if bool(params.get("liquidity_scaling", False)):
                raw_target, liquidity_info = _apply_liquidity_scaling(
                    raw_target,
                    base,
                    g,
                    float(params["liquidity_scaling_floor"]),
                    float(params["individual_max_weight"]),
                )
                turnover_info.update(liquidity_info)

            cov = _active_covariance(
                return_mat,
                date,
                base.index.union(raw_target.index),
                int(params["active_risk_lookback_days"]),
                int(params["active_risk_min_observations"]),
            )
            raw_target, risk_info = _apply_active_risk_target(
                raw_target,
                base,
                cov,
                params.get("active_risk_target_te"),
                float(params["individual_max_weight"]),
            )
            turnover_info.update(risk_info)

            previous = current if not current.empty else base
            current, turnover_info = _apply_turnover_limit(
                previous,
                raw_target,
                float(params["one_way_turnover_limit"]),
            )
            cost_detail = calc_rebalance_cost_from_weight_change(
                date=date,
                previous_weights=previous,
                target_weights=current,
                scenario=str(params["cost_scenario"]),
            )
            trading_cost = float(cost_detail["total_cost"])

            for code in current.index:
                weight_rows.append(
                    {
                        "date": date,
                        "stock_code": code,
                        "benchmark_weight": float(base.reindex(current.index).fillna(0.0).get(code, 0.0)),
                        "raw_target_weight_before_turnover_limit": float(raw_target.reindex(current.index).fillna(0.0).get(code, 0.0)),
                        "final_weight_after_turnover_limit": float(current.get(code, 0.0)),
                        "active_weight": float(current.get(code, 0.0) - base.reindex(current.index).fillna(0.0).get(code, 0.0)),
                        "score": float(score.reindex(current.index).fillna(0.0).get(code, 0.0)),
                        "selected_factor_coverage_ratio": float(coverage.reindex(current.index).fillna(0.0).get(code, 0.0)),
                        "selected_families": ",".join(selected_families),
                    }
                )

            turnover_rows.append(
                {
                    "date": date,
                    "selected_families": ",".join(selected_families),
                    "selected_family_count": len(selected_families),
                    "trading_cost_return": -trading_cost,
                    **turnover_info,
                }
            )

            if not diagnostics.empty:
                diag = diagnostics.reset_index().rename(columns={"index": "stock_code"})
                diag["date"] = date
                diag["selected_families"] = ",".join(selected_families)
                signal_rows.append(diag)

        if not current.empty:
            cost_reflected = port_ret - trading_cost - daily_fund_cost if pd.notna(port_ret) else np.nan
            rows.append(
                {
                    "date": date,
                    "walk_forward_factor_tilt_return_before_cost": port_ret,
                    "walk_forward_factor_tilt_cost_reflected_return": cost_reflected,
                    "benchmark_pdf_return": benchmark_returns.reindex([date]).iloc[0]
                    if date in benchmark_returns.index
                    else np.nan,
                    "trading_cost_return": -trading_cost,
                    "fund_expense_return": -daily_fund_cost,
                    "turnover": turnover_info["realized_turnover_after_limit"] if is_rebalance else 0.0,
                    "is_rebalance": is_rebalance,
                    "selected_families": ",".join(selected_families) if is_rebalance else "",
                }
            )

    returns = pd.DataFrame(rows)
    weights = pd.DataFrame(weight_rows)
    turnover = pd.DataFrame(turnover_rows)
    signals = pd.concat(signal_rows, ignore_index=True) if signal_rows else pd.DataFrame()

    if returns.empty:
        summary = pd.DataFrame()
    else:
        ret = returns.set_index("date")
        summary_row = performance_summary(
            ret["walk_forward_factor_tilt_cost_reflected_return"],
            ret["benchmark_pdf_return"],
            "walk_forward_factor_tilt_cost_reflected",
        )
        summary_row.update(
            {
                "start_date": ret.dropna(subset=["walk_forward_factor_tilt_cost_reflected_return"]).index.min(),
                "end_date": ret.dropna(subset=["walk_forward_factor_tilt_cost_reflected_return"]).index.max(),
                "oos_rebalance_count": int(turnover.shape[0]),
                "turnover_binding_count": int(turnover["turnover_was_binding"].sum()) if not turnover.empty else 0,
                "average_turnover": float(turnover["realized_turnover_after_limit"].mean()) if not turnover.empty else np.nan,
                "total_trading_cost_return": float(returns["trading_cost_return"].sum()),
                "total_fund_expense_return": float(returns["fund_expense_return"].sum()),
                "ic_lookback_months": params["ic_lookback_months"],
                "min_training_months": params["min_training_months"],
            }
        )
        summary = pd.DataFrame([summary_row])
    return {
        "returns": returns,
        "weights": weights,
        "turnover": turnover,
        "signals": signals,
        "summary": summary,
    }


def summarize_walk_forward_families(wf_validation: pd.DataFrame) -> pd.DataFrame:
    if wf_validation.empty:
        return pd.DataFrame()
    rows = []
    for family, g in wf_validation.groupby("factor_family"):
        selected = g[g["selected_for_next_month"]]
        rows.append(
            {
                "factor_family": family,
                "walk_forward_dates": int(g.shape[0]),
                "eligible_dates": int(g["enough_history"].sum()),
                "selected_count": int(g["selected_for_next_month"].sum()),
                "selection_rate_after_eligible": float(selected.shape[0] / max(g["enough_history"].sum(), 1)),
                "avg_training_mean_ic_when_selected": float(selected["training_mean_ic"].mean()) if not selected.empty else np.nan,
                "avg_realized_next_month_ic_when_selected": float(selected["realized_next_month_mean_ic"].mean()) if not selected.empty else np.nan,
                "hit_ratio_realized_next_month_ic_positive_when_selected": float(
                    (selected["realized_next_month_mean_ic"] > 0).mean()
                )
                if not selected.empty
                else np.nan,
                "avg_realized_next_month_top_minus_bottom_when_selected": float(
                    selected["realized_next_month_mean_top_minus_bottom_return"].mean()
                )
                if not selected.empty
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("avg_realized_next_month_ic_when_selected", ascending=False)


def run_walk_forward_factor_validation(params: dict | None = None) -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    panel = pd.read_csv(MODEL_PANEL_FILE, dtype={"stock_code": str}, low_memory=False)
    panel["stock_code"] = panel["stock_code"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])

    wf_validation = build_walk_forward_factor_validation(panel, params)
    family_summary = summarize_walk_forward_families(wf_validation)
    strategy = run_walk_forward_strategy(panel, wf_validation, params)

    wf_validation.to_csv(OUTPUT_DIR / "walk_forward_factor_validation.csv", index=False, encoding="utf-8-sig")
    family_summary.to_csv(OUTPUT_DIR / "family_walk_forward_ic_summary.csv", index=False, encoding="utf-8-sig")
    strategy["summary"].to_csv(OUTPUT_DIR / "out_of_sample_strategy_summary.csv", index=False, encoding="utf-8-sig")
    strategy["returns"].to_csv(OUTPUT_DIR / "walk_forward_factor_tilt_returns.csv", index=False, encoding="utf-8-sig")
    strategy["weights"].to_csv(OUTPUT_DIR / "walk_forward_factor_tilt_weights.csv", index=False, encoding="utf-8-sig")
    strategy["turnover"].to_csv(OUTPUT_DIR / "walk_forward_factor_tilt_turnover.csv", index=False, encoding="utf-8-sig")
    strategy["signals"].to_csv(OUTPUT_DIR / "walk_forward_factor_tilt_signals.csv", index=False, encoding="utf-8-sig")
    return {
        "validation": wf_validation,
        "family_summary": family_summary,
        **strategy,
    }


if __name__ == "__main__":
    result = run_walk_forward_factor_validation()
    print(result["family_summary"].to_string(index=False))
    print(result["summary"].to_string(index=False))
