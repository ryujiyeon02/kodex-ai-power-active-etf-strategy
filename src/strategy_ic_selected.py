"""Legacy direct-tilt helpers.

This file is kept because the final ConsensusCore/MVO pipeline reuses small
portfolio helper functions from it, such as rebalance-date selection and
turnover-limit blending. The old direct IC-selected strategy is not the final
presentation strategy and should not be run as a standalone script.
"""

import numpy as np
import pandas as pd

from benchmark_replication import month_end_rebalance_dates
from cost_utils import ETF_OFFICIAL_COSTS, calc_rebalance_cost_from_weight_change, daily_expense_rate
from factor_utils import zscore_cross_section
from performance import drawdown_series, monthly_returns, performance_summary
from project_paths import MODEL_PANEL_FILE, OUTPUT_DIR, ensure_output_dir
from selected_factor_config import SELECTED_FACTOR_SPECS
from strategy_factor_diagnostics import build_exhaustive_candidate_source


PARAMS = {
    "benchmark_weight_column": "etf_weight_pct",
    "rebalance_frequency": "month_end",
    "individual_active_limit": 0.035,
    "active_budget": 0.10,
    "individual_max_weight": 0.30,
    "one_way_turnover_limit": 0.10,
    "cost_scenario": "base",
    "annual_fund_expense_rate": ETF_OFFICIAL_COSTS["annual_total_fee_expense_rate"],
    "minimum_coverage_multiplier": 0.25,
}


def weekly_rebalance_dates(price_dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """각 주의 마지막 거래일을 리밸런싱일로 사용합니다."""
    s = pd.Series(index=pd.DatetimeIndex(sorted(price_dates)), data=1)
    return list(s.groupby(s.index.to_period("W-FRI")).tail(1).index)


def biweekly_rebalance_dates(price_dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """격주 마지막 거래일을 리밸런싱일로 사용합니다."""
    weekly = weekly_rebalance_dates(price_dates)
    return weekly[::2]


def choose_rebalance_dates(price_dates: pd.DatetimeIndex, frequency: str) -> list[pd.Timestamp]:
    if frequency == "weekly":
        return weekly_rebalance_dates(price_dates)
    if frequency == "biweekly":
        return biweekly_rebalance_dates(price_dates)
    if frequency == "month_end":
        return month_end_rebalance_dates(price_dates)
    raise ValueError(f"지원하지 않는 리밸런싱 주기입니다: {frequency}")



def _normalize_factor_weights(specs: list[dict]) -> list[dict]:
    total = sum(float(s["weight"]) for s in specs)
    out = []
    for spec in specs:
        new_spec = spec.copy()
        new_spec["normalized_weight"] = float(spec["weight"]) / total if total > 0 else 0.0
        out.append(new_spec)
    return out


def _normalize_weight_series(w: pd.Series) -> pd.Series:
    x = pd.to_numeric(w, errors="coerce").fillna(0.0).clip(lower=0.0)
    total = float(x.sum())
    if total <= 0:
        return x
    return x / total


def _benchmark_weights(g: pd.DataFrame, weight_col: str) -> pd.Series:
    w = pd.to_numeric(g[weight_col], errors="coerce").fillna(0.0) / 100.0
    w.index = g["stock_code"].astype(str).values
    w = w[w > 1e-12]
    return _normalize_weight_series(w).sort_index()


def _build_selected_score(g: pd.DataFrame, specs: list[dict]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    g = g.set_index("stock_code").sort_index()
    score = pd.Series(0.0, index=g.index)
    raw_available = pd.DataFrame(index=g.index)
    score_parts = pd.DataFrame(index=g.index)

    for spec in specs:
        factor = spec["factor"]
        if factor not in g.columns:
            raw = pd.Series(np.nan, index=g.index)
        else:
            raw = pd.to_numeric(g[factor], errors="coerce")
        z = zscore_cross_section(raw) * float(spec["direction"])
        contribution = z * float(spec["normalized_weight"])
        score = score + contribution
        raw_available[factor] = raw.notna()
        score_parts[f"z_{factor}"] = z
        score_parts[f"score_contribution_{factor}"] = contribution

    coverage = raw_available.mean(axis=1).fillna(0.0)
    multiplier = coverage.clip(lower=float(PARAMS["minimum_coverage_multiplier"]), upper=1.0)
    score = score - score.mean()
    adjusted_score = score * multiplier
    adjusted_score = adjusted_score - adjusted_score.mean()

    diagnostics = pd.DataFrame(
        {
            "selected_factor_count": len(specs),
            "usable_selected_factor_count": raw_available.sum(axis=1).astype(int),
            "selected_factor_coverage_ratio": coverage,
            "coverage_score_multiplier": multiplier,
            "raw_selected_score": score,
            "coverage_adjusted_score": adjusted_score,
        },
        index=g.index,
    )
    diagnostics = pd.concat([diagnostics, score_parts], axis=1)
    return diagnostics, adjusted_score, coverage


def _score_to_target(
    base: pd.Series,
    score: pd.Series,
    active_limit: float,
    active_budget: float,
    max_weight: float,
) -> tuple[pd.Series, pd.Series]:
    score = score.reindex(base.index).fillna(0.0)
    centered = score - score.mean()
    denom = float(centered.abs().sum())
    if denom <= 0:
        active = pd.Series(0.0, index=base.index)
    else:
        active = centered / denom * active_budget
    active = active.clip(lower=-active_limit, upper=active_limit)
    target = (base + active).clip(lower=0.0, upper=max_weight)
    target = _normalize_weight_series(target)
    active = target - base.reindex(target.index, fill_value=0.0)
    return target.sort_index(), active.sort_index()


def _apply_turnover_limit(
    previous: pd.Series,
    raw_target: pd.Series,
    turnover_limit: float,
) -> tuple[pd.Series, dict]:
    idx = previous.index.union(raw_target.index)
    prev = previous.reindex(idx, fill_value=0.0)
    raw = raw_target.reindex(idx, fill_value=0.0)
    desired_turnover = 0.5 * float((raw - prev).abs().sum())
    if desired_turnover > turnover_limit and desired_turnover > 0:
        blend = turnover_limit / desired_turnover
        final = prev + blend * (raw - prev)
        binding = True
    else:
        blend = 1.0
        final = raw
        binding = False
    final = _normalize_weight_series(final)
    realized_turnover = 0.5 * float((final - prev).abs().sum())
    return final.sort_index(), {
        "desired_turnover_before_limit": desired_turnover,
        "turnover_limit": turnover_limit,
        "turnover_blend_ratio": blend,
        "realized_turnover_after_limit": realized_turnover,
        "turnover_was_binding": binding,
        "traded_weight_after_limit": realized_turnover * 2.0,
    }


def _active_risk_row(
    data: pd.DataFrame,
    strategy_col: str,
    benchmark_col: str,
    benchmark_name: str,
    benchmark_role: str,
) -> dict:
    aligned = data[[strategy_col, benchmark_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if aligned.empty:
        return {
            "benchmark": benchmark_name,
            "benchmark_role": benchmark_role,
            "observations": 0,
            "strategy_return_correlation_with_benchmark": np.nan,
            "active_return_correlation_with_benchmark": np.nan,
            "tracking_error_annualized": np.nan,
            "active_return_mean_daily": np.nan,
            "active_return_std_daily": np.nan,
            "strategy_correlation_minimum_threshold": 0.70,
            "strategy_correlation_pass": False,
            "active_return_correlation_note": "diagnostic_only_not_active_etf_listing_threshold",
        }
    strategy = aligned[strategy_col]
    benchmark = aligned[benchmark_col]
    active = strategy - benchmark
    active_std = active.std(ddof=1) if len(active) >= 2 else np.nan
    active_corr = active.corr(benchmark) if len(active) >= 2 else np.nan
    strategy_corr = strategy.corr(benchmark) if len(aligned) >= 2 else np.nan
    return {
        "benchmark": benchmark_name,
        "benchmark_role": benchmark_role,
        "observations": int(len(aligned)),
        "strategy_return_correlation_with_benchmark": float(strategy_corr) if pd.notna(strategy_corr) else np.nan,
        "active_return_correlation_with_benchmark": float(active_corr) if pd.notna(active_corr) else np.nan,
        "tracking_error_annualized": float(active_std * np.sqrt(252)) if pd.notna(active_std) else np.nan,
        "active_return_mean_daily": float(active.mean()) if not active.empty else np.nan,
        "active_return_std_daily": float(active_std) if pd.notna(active_std) else np.nan,
        "strategy_correlation_minimum_threshold": 0.70,
        "strategy_correlation_pass": bool(pd.notna(strategy_corr) and strategy_corr >= 0.70),
        "active_return_correlation_note": "diagnostic_only_not_active_etf_listing_threshold",
    }


def run_ic_selected_strategy(
    params_override: dict | None = None,
    output_prefix: str = "strategy_ic_selected",
) -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    params = PARAMS.copy()
    if params_override:
        params.update(params_override)
    panel = pd.read_csv(MODEL_PANEL_FILE, dtype={"stock_code": str}, low_memory=False)
    panel["stock_code"] = panel["stock_code"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])

    source = build_exhaustive_candidate_source(panel)
    source["stock_code"] = source["stock_code"].astype(str).str.zfill(6)
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])

    dates = pd.DatetimeIndex(sorted(source["date"].dropna().unique()))
    rebalance_dates = sorted(set(choose_rebalance_dates(dates, str(params["rebalance_frequency"]))))
    rebalance_set = set(rebalance_dates)
    specs = _normalize_factor_weights(SELECTED_FACTOR_SPECS)

    return_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    stock_names = panel.dropna(subset=["stock_name"]).drop_duplicates("stock_code").set_index("stock_code")[
        "stock_name"
    ].to_dict()

    current = pd.Series(dtype=float)
    rows = []
    weight_rows = []
    signal_rows = []
    turnover_rows = []

    daily_fund_cost = daily_expense_rate(params["annual_fund_expense_rate"])

    for date in dates:
        if not current.empty and date in return_mat.index:
            ret = pd.to_numeric(return_mat.loc[date], errors="coerce").reindex(current.index).fillna(0.0)
            port_ret = float((current * ret).sum())
            denom = 1.0 + port_ret
            if denom != 0:
                current = current * (1.0 + ret) / denom

        g = source[source["date"] == date].copy()
        if g.empty:
            continue
        g["stock_code"] = g["stock_code"].astype(str).str.zfill(6)
        base = _benchmark_weights(g, str(params["benchmark_weight_column"]))
        is_rebalance = date in rebalance_set
        turnover_info = {
            "desired_turnover_before_limit": 0.0,
            "turnover_limit": float(params["one_way_turnover_limit"]),
            "turnover_blend_ratio": 1.0,
            "realized_turnover_after_limit": 0.0,
            "turnover_was_binding": False,
            "traded_weight_after_limit": 0.0,
        }
        trading_cost_return = 0.0
        cost_detail = {
            "scenario": params["cost_scenario"],
            "total_traded_weight": 0.0,
            "buy_weight": 0.0,
            "sell_weight": 0.0,
            "commission": 0.0,
            "agency_fee": 0.0,
            "slippage": 0.0,
            "tax": 0.0,
            "total_cost": 0.0,
            "average_cost_rate_on_traded_weight": 0.0,
            "trade_count": 0,
        }

        if current.empty:
            current = base.copy()

        if is_rebalance:
            diagnostics, score, _ = _build_selected_score(g, specs)
            raw_target, raw_active = _score_to_target(
                base=base,
                score=score,
                active_limit=float(params["individual_active_limit"]),
                active_budget=float(params["active_budget"]),
                max_weight=float(params["individual_max_weight"]),
            )
            previous_before_rebalance = current.copy()
            final, turnover_info = _apply_turnover_limit(
                previous=current,
                raw_target=raw_target,
                turnover_limit=float(params["one_way_turnover_limit"]),
            )
            cost_detail = calc_rebalance_cost_from_weight_change(
                date=date,
                previous_weights=current,
                target_weights=final,
                scenario=str(params["cost_scenario"]),
            )
            trading_cost_return = -float(cost_detail["total_cost"])
            current = final

            diag = diagnostics.reindex(base.index)
            for code in base.index.union(raw_target.index).union(final.index):
                signal_rows.append(
                    {
                        "date": date,
                        "stock_code": code,
                        "stock_name": stock_names.get(code),
                        "benchmark_weight": base.reindex([code], fill_value=0.0).iloc[0],
                        "raw_target_weight_before_turnover_limit": raw_target.reindex([code], fill_value=0.0).iloc[0],
                        "final_weight_after_turnover_limit": final.reindex([code], fill_value=0.0).iloc[0],
                        "raw_active_weight": raw_active.reindex([code], fill_value=0.0).iloc[0],
                        "final_active_weight": final.reindex([code], fill_value=0.0).iloc[0]
                        - base.reindex([code], fill_value=0.0).iloc[0],
                        "desired_trade_weight": raw_target.reindex([code], fill_value=0.0).iloc[0]
                        - previous_before_rebalance.reindex([code], fill_value=0.0).iloc[0],
                        "actual_trade_weight": final.reindex([code], fill_value=0.0).iloc[0]
                        - previous_before_rebalance.reindex([code], fill_value=0.0).iloc[0],
                        "selected_factor_coverage_ratio": diag.reindex([code])[
                            "selected_factor_coverage_ratio"
                        ].iloc[0]
                        if code in diag.index
                        else np.nan,
                        "coverage_adjusted_score": diag.reindex([code])["coverage_adjusted_score"].iloc[0]
                        if code in diag.index
                        else np.nan,
                        "turnover_was_binding": turnover_info["turnover_was_binding"],
                        "turnover_blend_ratio": turnover_info["turnover_blend_ratio"],
                    }
                )

            turnover_rows.append(
                {
                    "date": date,
                    **turnover_info,
                    "cost_scenario": params["cost_scenario"],
                    "buy_weight": cost_detail["buy_weight"],
                    "sell_weight": cost_detail["sell_weight"],
                    "commission_return": -cost_detail["commission"],
                    "agency_fee_return": -cost_detail["agency_fee"],
                    "slippage_return": -cost_detail["slippage"],
                    "sell_tax_return": -cost_detail["tax"],
                    "average_cost_rate_on_traded_weight": cost_detail["average_cost_rate_on_traded_weight"],
                    "trading_cost_return": trading_cost_return,
                    "annual_fund_expense_rate": params["annual_fund_expense_rate"],
                }
            )

        rows.append(
            {
                "date": date,
                "is_rebalance": is_rebalance,
                "turnover": turnover_info["realized_turnover_after_limit"],
                "trading_cost_return": trading_cost_return,
                "position_count": int((current > 0).sum()) if not current.empty else 0,
            }
        )
        for code, weight in current.items():
            weight_rows.append(
                {
                    "date": date,
                    "stock_code": code,
                    "stock_name": stock_names.get(code),
                    "weight": weight,
                    "is_rebalance": is_rebalance,
                }
            )

    daily = pd.DataFrame(rows).sort_values("date")
    weights_long = pd.DataFrame(weight_rows).sort_values(["date", "stock_code"])
    weights = weights_long.pivot(index="date", columns="stock_code", values="weight").fillna(0.0).sort_index()
    returns = return_mat.reindex(weights.index, columns=weights.columns)
    lag_weights = weights.shift(1)
    strategy_return = (lag_weights * returns).sum(axis=1, min_count=1)

    pdf_benchmark_path = OUTPUT_DIR / "benchmark_pdf_returns.csv"
    if pdf_benchmark_path.exists():
        pdf_benchmark = pd.read_csv(pdf_benchmark_path, usecols=["date", "pdf_return"])
        pdf_benchmark["date"] = pd.to_datetime(pdf_benchmark["date"], errors="coerce")
        benchmark_return = pdf_benchmark.set_index("date")["pdf_return"].reindex(weights.index)
    else:
        base_weights = (
            panel.assign(date=pd.to_datetime(panel["date"], errors="coerce"))
            .pivot_table(index="date", columns="stock_code", values=params["benchmark_weight_column"], aggfunc="sum")
            .reindex(index=weights.index, columns=weights.columns)
            .fillna(0.0)
            / 100.0
        )
        base_weights = base_weights.div(base_weights.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
        benchmark_return = (base_weights.shift(1) * returns).sum(axis=1, min_count=1)

    ret = daily.set_index("date").reindex(weights.index)
    cost = pd.to_numeric(ret["trading_cost_return"], errors="coerce").fillna(0.0)
    fund_expense = pd.Series(-daily_fund_cost, index=weights.index)
    fund_expense.loc[benchmark_return.isna()] = 0.0
    cost_reflected_return = strategy_return + cost + fund_expense
    returns_out = pd.DataFrame(
        {
            "date": weights.index,
            "cost_not_reflected_return": strategy_return.values,
            "trading_cost_return": cost.values,
            "fund_expense_return": fund_expense.values,
            "cost_reflected_return": cost_reflected_return.values,
            "benchmark_pdf_return": benchmark_return.values,
            "active_return_cost_reflected": (cost_reflected_return - benchmark_return).values,
            "turnover": pd.to_numeric(ret["turnover"], errors="coerce").fillna(0.0).values,
        }
    )
    returns_out["cumulative_cost_reflected_return"] = (
        1.0 + returns_out["cost_reflected_return"].fillna(0.0)
    ).cumprod() - 1.0
    returns_out["cumulative_benchmark_pdf_return"] = (
        1.0 + returns_out["benchmark_pdf_return"].fillna(0.0)
    ).cumprod() - 1.0
    returns_out["drawdown"] = drawdown_series(returns_out.set_index("date")["cost_reflected_return"]).values

    ret_idx = returns_out.set_index("date")
    summary = pd.DataFrame(
        [
            performance_summary(
                ret_idx["cost_reflected_return"],
                ret_idx["benchmark_pdf_return"],
                "strategy_ic_selected_cost_reflected",
            ),
            performance_summary(
                ret_idx["cost_not_reflected_return"],
                ret_idx["benchmark_pdf_return"],
                "strategy_ic_selected_cost_not_reflected",
            ),
            performance_summary(ret_idx["benchmark_pdf_return"], name="strategy_ic_selected_benchmark_pdf"),
        ]
    )

    common_summary = pd.DataFrame()
    actual_path = OUTPUT_DIR / "benchmark_actual_etf_comparison.csv"
    if actual_path.exists():
        actual = pd.read_csv(actual_path)
        actual["date"] = pd.to_datetime(actual["date"], errors="coerce")
        actual = actual.set_index("date")
        common = pd.concat(
            [
                ret_idx[["cost_reflected_return", "benchmark_pdf_return"]],
                actual[["nav_return", "underlying_index_close_return", "etf_close_return"]],
            ],
            axis=1,
        ).dropna()
        if not common.empty:
            common_summary = pd.DataFrame(
                [
                    performance_summary(
                        common["cost_reflected_return"],
                        common["underlying_index_close_return"],
                        "strategy_ic_selected_common_dates_vs_index",
                    ),
                    performance_summary(
                        common["cost_reflected_return"],
                        common["nav_return"],
                        "strategy_ic_selected_common_dates_vs_nav",
                    ),
                    performance_summary(
                        common["benchmark_pdf_return"],
                        common["underlying_index_close_return"],
                        "pdf_replication_common_dates_vs_index",
                    ),
                    performance_summary(
                        common["nav_return"],
                        common["underlying_index_close_return"],
                        "nav_common_dates_vs_index",
                    ),
                    performance_summary(
                        common["etf_close_return"],
                        common["underlying_index_close_return"],
                        "etf_close_common_dates_vs_index",
                    ),
                ]
            )
            common.to_csv(
                OUTPUT_DIR / f"{output_prefix}_actual_etf_comparison.csv",
                index=True,
                index_label="date",
                encoding="utf-8-sig",
            )
            active_risk = pd.DataFrame(
                [
                    _active_risk_row(
                        common,
                        "cost_reflected_return",
                        "underlying_index_close_return",
                        "underlying_index",
                        "official_strategy_benchmark",
                    ),
                    _active_risk_row(
                        common,
                        "cost_reflected_return",
                        "nav_return",
                        "etf_nav",
                        "official_etf_nav_reference",
                    ),
                    _active_risk_row(
                        common,
                        "cost_reflected_return",
                        "benchmark_pdf_return",
                        "pdf_replication",
                        "internal_replication_benchmark",
                    ),
                    _active_risk_row(
                        common,
                        "cost_reflected_return",
                        "etf_close_return",
                        "etf_market_price",
                        "market_price_reference",
                    ),
                    _active_risk_row(
                        common,
                        "benchmark_pdf_return",
                        "underlying_index_close_return",
                        "pdf_replication_vs_underlying_index",
                        "internal_replication_error",
                    ),
                    _active_risk_row(
                        common,
                        "nav_return",
                        "underlying_index_close_return",
                        "etf_nav_vs_underlying_index",
                        "official_etf_tracking_error",
                    ),
                ]
            )
            active_risk.to_csv(
                OUTPUT_DIR / f"{output_prefix}_active_risk_summary.csv", index=False, encoding="utf-8-sig"
            )

    factor_config = pd.DataFrame(specs)
    turnover_df = pd.DataFrame(turnover_rows).sort_values("date")
    signal_df = pd.DataFrame(signal_rows).sort_values(["date", "stock_code"])
    monthly = monthly_returns(ret_idx["cost_reflected_return"]).rename("strategy_ic_selected_cost_reflected")

    returns_out.to_csv(OUTPUT_DIR / f"{output_prefix}_returns.csv", index=False, encoding="utf-8-sig")
    weights_long.to_csv(OUTPUT_DIR / f"{output_prefix}_weights.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / f"{output_prefix}_performance_summary.csv", index=False, encoding="utf-8-sig")
    common_summary.to_csv(
        OUTPUT_DIR / f"{output_prefix}_common_date_performance_summary.csv", index=False, encoding="utf-8-sig"
    )
    factor_config.to_csv(OUTPUT_DIR / f"{output_prefix}_factor_config.csv", index=False, encoding="utf-8-sig")
    turnover_df.to_csv(OUTPUT_DIR / f"{output_prefix}_turnover_diagnostics.csv", index=False, encoding="utf-8-sig")
    signal_df.to_csv(OUTPUT_DIR / f"{output_prefix}_signal_diagnostics.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(OUTPUT_DIR / f"{output_prefix}_monthly_returns.csv", encoding="utf-8-sig")

    return {
        "returns": returns_out,
        "weights": weights_long,
        "summary": summary,
        "turnover": turnover_df,
        "signals": signal_df,
        "factor_config": factor_config,
    }


if __name__ == "__main__":
    raise SystemExit(
        "strategy_ic_selected.py is kept only for helper functions. "
        "Run active_experiment_runner.py for the final ConsensusCore/MVO strategy."
    )
