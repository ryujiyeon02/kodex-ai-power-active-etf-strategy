import numpy as np
import pandas as pd

from build_model_panel_v2 import apply_cap
from performance import annualized_volatility, drawdown_series, max_drawdown, performance_summary, tracking_error_summary
from project_paths import (
    BACKTEST_START,
    CASH_CODE,
    CASH_NAME,
    ETF_DAILY_FILE,
    OUTPUT_DIR,
    PDF_HISTORY_FILE,
    PRICE_LONG_FILE,
    ensure_output_dir,
)


def clean_code_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"^A", "", regex=True)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(6)
    )


def load_price() -> pd.DataFrame:
    price = pd.read_csv(PRICE_LONG_FILE, dtype={"stock_code": str}, low_memory=False)
    price["stock_code"] = clean_code_series(price["stock_code"])
    price["date"] = pd.to_datetime(price["date"], errors="coerce")
    price = price.dropna(subset=["date", "stock_code"])
    price = price.sort_values(["stock_code", "date"])
    price["return"] = price.groupby("stock_code")["adj_close"].pct_change()
    price["float_mktcap"] = pd.to_numeric(price["close"], errors="coerce") * pd.to_numeric(
        price["float_shares"], errors="coerce"
    )
    if {"market_cap", "float_ratio_pct"}.issubset(price.columns):
        price["float_mktcap_alt"] = price["market_cap"] * price["float_ratio_pct"] / 100.0
    return price


def load_pdf_history() -> pd.DataFrame:
    pdf = pd.read_csv(PDF_HISTORY_FILE, dtype={"date": str, "stock_code": str, "etf_code": str}, low_memory=False)
    pdf["date"] = pd.to_datetime(pdf["date"], errors="coerce")
    is_cash = pdf["stock_name"].astype(str).eq(CASH_NAME) | pdf["stock_code"].astype(str).eq(CASH_CODE)
    pdf.loc[~is_cash, "stock_code"] = clean_code_series(pdf.loc[~is_cash, "stock_code"])
    pdf.loc[is_cash, "stock_code"] = CASH_CODE
    pdf["weight"] = pd.to_numeric(pdf["weight_pct"], errors="coerce") / 100.0
    pdf = pdf.dropna(subset=["date", "stock_code", "weight"])
    return pdf


def adjust_pdf_cash_substitution(
    pdf: pd.DataFrame,
    cash_spike_threshold: float = 0.05,
    normal_cash_threshold: float = 0.02,
    lookahead_rows: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    KRX PDF에서 기업이벤트/거래정지 종목이 일시적으로 원화현금처럼 표시되는
    구간을 복제 백테스트용 경제적 노출로 보정합니다.

    예: LS ELECTRIC 2026-04-08~2026-04-10은 종목 비중이 0이고 원화현금이
    약 23%로 튀지만, NAV/기초지수는 해당 노출이 사라진 것처럼 움직이지
    않습니다. 이 함수는 비정상 현금 중 정상 현금 수준을 초과한 부분을
    직전/직후에 존재하는 동일 종목 비중으로 되돌립니다.
    """
    if pdf.empty or CASH_CODE not in set(pdf["stock_code"]):
        return pdf.copy(), pd.DataFrame()

    working = pdf.copy()
    dates = pd.DatetimeIndex(sorted(working["date"].dropna().unique()))
    weights = working.pivot_table(index="date", columns="stock_code", values="weight", aggfunc="sum").fillna(0.0)
    weights = weights.reindex(dates).fillna(0.0)
    cash = weights.get(CASH_CODE, pd.Series(0.0, index=weights.index))
    normal_cash = cash[cash <= normal_cash_threshold].median()
    if not np.isfinite(normal_cash):
        normal_cash = 0.0

    name_map = working.drop_duplicates("stock_code").set_index("stock_code")["stock_name"].to_dict()
    audit_rows = []
    stock_cols = [c for c in weights.columns if c != CASH_CODE]

    for pos, date in enumerate(weights.index):
        original_cash = float(weights.at[date, CASH_CODE]) if CASH_CODE in weights.columns else 0.0
        excess_cash = original_cash - float(normal_cash)
        if excess_cash <= cash_spike_threshold:
            continue

        prev_date = weights.index[pos - 1] if pos > 0 else None
        future_dates = weights.index[pos + 1 : pos + 1 + lookahead_rows]
        if prev_date is None or len(future_dates) == 0:
            continue

        prev = weights.loc[prev_date, stock_cols]
        current = weights.loc[date, stock_cols]
        future_max = weights.loc[future_dates, stock_cols].max(axis=0)
        candidate_mask = (
            (prev.reindex(stock_cols).fillna(0.0) > normal_cash_threshold)
            & (current.reindex(stock_cols).fillna(0.0) <= 1e-10)
            & (future_max.reindex(stock_cols).fillna(0.0) > normal_cash_threshold)
        )
        candidates = candidate_mask[candidate_mask].index.tolist()
        if len(candidates) == 0:
            continue

        prev_candidate_weights = prev.reindex(candidates).astype(float)
        denom = float(prev_candidate_weights.sum())
        if denom <= 0:
            continue

        adjusted_cash = max(0.0, float(normal_cash))
        weights.at[date, CASH_CODE] = adjusted_cash
        for code, prev_weight in prev_candidate_weights.items():
            transferred = excess_cash * float(prev_weight) / denom
            original_stock = float(current.get(code, 0.0))
            weights.at[date, code] = original_stock + transferred
            audit_rows.append(
                {
                    "date": date,
                    "stock_code": code,
                    "stock_name": name_map.get(code, code),
                    "original_cash_weight": original_cash,
                    "adjusted_cash_weight": adjusted_cash,
                    "original_stock_weight": original_stock,
                    "adjusted_stock_weight": float(weights.at[date, code]),
                    "transferred_weight": transferred,
                    "reason": "cash_substitution_for_temporary_zero_weight",
                }
            )

    adjusted_long = (
        weights.reset_index(names="date")
        .melt(id_vars="date", var_name="stock_code", value_name="weight")
        .query("weight != 0")
        .copy()
    )
    adjusted_long["stock_name"] = adjusted_long["stock_code"].map(name_map)
    adjusted_long.loc[adjusted_long["stock_code"] == CASH_CODE, "stock_name"] = CASH_NAME
    adjusted_long["weight_pct"] = adjusted_long["weight"] * 100.0
    audit = pd.DataFrame(audit_rows)
    return adjusted_long.sort_values(["date", "stock_code"]), audit


def pivot_stock_returns(price: pd.DataFrame) -> pd.DataFrame:
    return price.pivot(index="date", columns="stock_code", values="return").sort_index()


def pivot_pdf_weights(pdf: pd.DataFrame) -> pd.DataFrame:
    stock_pdf = pdf[pdf["stock_code"] != CASH_CODE].copy()
    weights = stock_pdf.pivot_table(index="date", columns="stock_code", values="weight", aggfunc="sum").fillna(0.0)
    return weights.sort_index()


def pdf_cash_weight(pdf: pd.DataFrame) -> pd.Series:
    cash = pdf[pdf["stock_code"] == CASH_CODE].groupby("date")["weight"].sum().sort_index()
    return cash


def compute_pdf_benchmark(price: pd.DataFrame, pdf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = pivot_stock_returns(price)
    weights = pivot_pdf_weights(pdf)
    common_dates = returns.index.intersection(weights.index)
    returns = returns.loc[common_dates]
    weights = weights.reindex(index=common_dates, columns=returns.columns, fill_value=0.0)
    lag_weights = weights.shift(1)

    pdf_return = (lag_weights * returns).sum(axis=1, min_count=1)
    cash = pdf_cash_weight(pdf).reindex(common_dates).fillna(0.0)
    out = pd.DataFrame(
        {
            "date": common_dates,
            "pdf_return": pdf_return.values,
            "cash_weight": cash.values,
            "cash_weight_lag": cash.shift(1).values,
            "stock_weight_sum": weights.sum(axis=1).values,
            "stock_weight_sum_lag": lag_weights.sum(axis=1).values,
            "positions": (weights > 0).sum(axis=1).values,
            "turnover": 0.5 * weights.diff().abs().sum(axis=1).fillna(0.0).values,
        }
    )
    out["cumulative_return"] = (1.0 + out["pdf_return"].fillna(0.0)).cumprod() - 1.0
    out["drawdown"] = drawdown_series(out.set_index("date")["pdf_return"]).values

    weights_long = (
        weights.reset_index()
        .melt(id_vars="date", var_name="stock_code", value_name="weight")
        .query("weight != 0")
        .sort_values(["date", "stock_code"])
    )
    name_map = pdf.drop_duplicates("stock_code").set_index("stock_code")["stock_name"].to_dict()
    weights_long["stock_name"] = weights_long["stock_code"].map(name_map)
    cash_long = pd.DataFrame(
        {
            "date": cash.index,
            "stock_code": CASH_CODE,
            "weight": cash.values,
            "stock_name": CASH_NAME,
        }
    )
    weights_long = pd.concat([weights_long, cash_long], ignore_index=True).sort_values(["date", "stock_code"])
    return out, weights_long


def second_thursday(year: int, month: int) -> pd.Timestamp:
    d = pd.Timestamp(year=year, month=month, day=1)
    first_thursday = d + pd.Timedelta(days=(3 - d.weekday()) % 7)
    return first_thursday + pd.Timedelta(days=7)


def methodology_rebalance_dates(price_dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    price_dates = pd.DatetimeIndex(sorted(price_dates))
    start, end = price_dates.min(), price_dates.max()
    dates = [start]
    for year in range(start.year, end.year + 1):
        for month in [6, 12]:
            expiry = second_thursday(year, month)
            next_monday = expiry + pd.Timedelta(days=(7 - expiry.weekday()) % 7)
            if next_monday <= expiry:
                next_monday += pd.Timedelta(days=7)
            candidates = price_dates[price_dates >= next_monday]
            if len(candidates) and start <= candidates[0] <= end:
                dates.append(candidates[0])
    return sorted(set(dates))


def month_end_rebalance_dates(price_dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(index=pd.DatetimeIndex(sorted(price_dates)), data=1)
    return list(s.groupby(s.index.to_period("M")).tail(1).index)


def get_pdf_membership_on_or_before(pdf: pd.DataFrame, date: pd.Timestamp) -> list[str]:
    available = pdf.loc[(pdf["date"] <= date) & (pdf["stock_code"] != CASH_CODE), "date"]
    if available.empty:
        return []
    use_date = available.max()
    members = pdf.loc[(pdf["date"] == use_date) & (pdf["stock_code"] != CASH_CODE), "stock_code"].unique().tolist()
    return sorted(members)


def cap20_target_for_date(price: pd.DataFrame, pdf: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    members = get_pdf_membership_on_or_before(pdf, date)
    snap = price[(price["date"] == date) & (price["stock_code"].isin(members))].copy()
    snap = snap.dropna(subset=["float_mktcap"])
    if snap.empty:
        return pd.Series(dtype=float)
    raw = snap.set_index("stock_code")["float_mktcap"].astype(float)
    weights = apply_cap(raw / raw.sum(), cap=0.20)
    return weights.sort_index()


def compute_cap20_drift_benchmark(
    price: pd.DataFrame,
    pdf: pd.DataFrame,
    frequency: str = "methodology",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Approximate the iSelect methodology with the data currently available.

    Confirmed from the provided methodology PDFs:
    - Final constituent weights are free-float market-cap weighted.
    - A 20% ceiling is applied at rebalance by redistributing excess weight.
    - Regular reconstitution is June/December, on the first business day of
      the week after options expiry.
    - Between rebalances, this implementation allows price-driven weight drift.

    Not available in the current files:
    - Official NH NLP scores and committee decisions.
    - Official NH free-float ratios and the full corporate-action adjustment
      history. We therefore use observed KRX PDF membership and FnGuide
      float market cap as proxies, then measure replication error.
    """
    returns = pivot_stock_returns(price)
    returns = returns[returns.index >= pd.Timestamp(BACKTEST_START)].copy()
    if frequency == "monthly":
        rebalance_dates = month_end_rebalance_dates(returns.index)
    elif frequency == "methodology":
        rebalance_dates = methodology_rebalance_dates(returns.index)
    else:
        raise ValueError("frequency must be 'methodology' or 'monthly'")

    current = pd.Series(dtype=float)
    rows = []
    weights_rows = []
    rebalance_set = set(rebalance_dates)

    for date, ret in returns.iterrows():
        pre_rebalance_weight = current.copy()
        port_ret = np.nan
        if not current.empty:
            aligned_ret = ret.reindex(current.index).fillna(0.0)
            port_ret = float((current * aligned_ret).sum())
            denom = 1.0 + port_ret
            if denom != 0:
                current = current * (1.0 + aligned_ret) / denom

        turnover = 0.0
        is_rebalance = date in rebalance_set
        if is_rebalance:
            target = cap20_target_for_date(price, pdf, date)
            if not target.empty:
                all_idx = current.index.union(target.index)
                turnover = 0.5 * (target.reindex(all_idx, fill_value=0.0) - pre_rebalance_weight.reindex(all_idx, fill_value=0.0)).abs().sum()
                current = target

        rows.append(
            {
                "date": date,
                "cap20_return": port_ret,
                "is_rebalance": is_rebalance,
                "turnover": turnover,
                "positions": int((current > 0).sum()) if not current.empty else 0,
                "cash_weight": max(0.0, 1.0 - float(current.sum())) if not current.empty else np.nan,
            }
        )
        for code, weight in current.items():
            weights_rows.append({"date": date, "stock_code": code, "weight": weight, "is_rebalance": is_rebalance})

    out = pd.DataFrame(rows)
    out["cumulative_return"] = (1.0 + out["cap20_return"].fillna(0.0)).cumprod() - 1.0
    out["drawdown"] = drawdown_series(out.set_index("date")["cap20_return"]).values
    weights = pd.DataFrame(weights_rows)
    if not weights.empty:
        name_map = price.drop_duplicates("stock_code").set_index("stock_code")["stock_name"].to_dict()
        weights["stock_name"] = weights["stock_code"].map(name_map)
    return out, weights


def load_etf_actual_returns() -> pd.DataFrame:
    if not ETF_DAILY_FILE.exists():
        return pd.DataFrame()
    etf = pd.read_csv(ETF_DAILY_FILE, dtype={"date": str, "etf_code": str}, low_memory=False)
    etf["date"] = pd.to_datetime(etf["date"], errors="coerce")
    etf = etf.sort_values("date")
    for col in ["etf_close", "nav", "underlying_index_close"]:
        if col in etf.columns:
            values = pd.to_numeric(etf[col], errors="coerce")
            valid_returns = values.dropna().pct_change(fill_method=None)
            etf[f"{col}_return"] = valid_returns.reindex(etf.index)
    return etf


def compare_benchmarks(pdf_returns: pd.DataFrame, cap20_returns: pd.DataFrame) -> pd.DataFrame:
    etf = load_etf_actual_returns()
    merged = pdf_returns[["date", "pdf_return"]].merge(
        cap20_returns[["date", "cap20_return"]], on="date", how="outer"
    )
    if not etf.empty:
        cols = [
            "date",
            "etf_close",
            "nav",
            "aum",
            "underlying_index_close",
            "etf_close_return",
            "nav_return",
            "underlying_index_close_return",
        ]
        cols = [c for c in cols if c in etf.columns]
        merged = merged.merge(etf[cols], on="date", how="left")
    merged = merged.sort_values("date")
    for col in ["pdf_return", "cap20_return", "etf_close_return", "nav_return", "underlying_index_close_return"]:
        if col in merged.columns:
            merged[f"{col}_cum"] = (1.0 + merged[col].fillna(0.0)).cumprod() - 1.0
    return merged


def _period_start(end_date: pd.Timestamp, period: str, first_date: pd.Timestamp) -> pd.Timestamp:
    if period == "1M":
        return max(first_date, end_date - pd.DateOffset(months=1))
    if period == "3M":
        return max(first_date, end_date - pd.DateOffset(months=3))
    if period == "6M":
        return max(first_date, end_date - pd.DateOffset(months=6))
    if period == "1Y":
        return max(first_date, end_date - pd.DateOffset(years=1))
    if period == "3Y":
        return max(first_date, end_date - pd.DateOffset(years=3))
    if period == "since_inception":
        return first_date
    raise ValueError(f"Unknown period: {period}")


def _corr(a: pd.Series, b: pd.Series) -> float:
    if a is None or b is None:
        return np.nan
    aligned = pd.concat([pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")], axis=1).dropna()
    if len(aligned) < 2:
        return np.nan
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def risk_period_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    if comparison.empty or "date" not in comparison.columns:
        return pd.DataFrame()
    comp = comparison.copy()
    comp["date"] = pd.to_datetime(comp["date"], errors="coerce")
    comp = comp.dropna(subset=["date"]).sort_values("date")
    if comp.empty:
        return pd.DataFrame()

    first_date = comp["date"].min()
    end_date = comp["date"].max()
    rows = []
    for period in ["1M", "3M", "6M", "1Y", "3Y", "since_inception"]:
        start_date = _period_start(end_date, period, first_date)
        s = comp[(comp["date"] >= start_date) & (comp["date"] <= end_date)].copy()
        idx = s.set_index("date")

        def te(strategy_col: str, benchmark_col: str) -> float:
            if strategy_col not in idx.columns or benchmark_col not in idx.columns:
                return np.nan
            return tracking_error_summary(idx[strategy_col], idx[benchmark_col])["annualized_tracking_error"]

        rows.append(
            {
                "period": period,
                "start_date": s["date"].min() if not s.empty else pd.NaT,
                "end_date": s["date"].max() if not s.empty else pd.NaT,
                "observations": int(len(s)),
                "official_nav_vs_index_te": te("nav_return", "underlying_index_close_return"),
                "market_price_vs_index_te": te("etf_close_return", "underlying_index_close_return"),
                "pdf_replication_vs_index_te": te("pdf_return", "underlying_index_close_return"),
                "cap20_replication_vs_index_te": te("cap20_return", "underlying_index_close_return"),
                "pdf_replication_vs_nav_te": te("pdf_return", "nav_return"),
                "pdf_replication_vs_index_correlation": _corr(idx.get("pdf_return"), idx.get("underlying_index_close_return")),
                "nav_vs_index_correlation": _corr(idx.get("nav_return"), idx.get("underlying_index_close_return")),
                "etf_close_vs_index_correlation": _corr(idx.get("etf_close_return"), idx.get("underlying_index_close_return")),
                "nav_volatility": annualized_volatility(idx.get("nav_return", pd.Series(dtype=float))),
                "index_volatility": annualized_volatility(idx.get("underlying_index_close_return", pd.Series(dtype=float))),
                "etf_close_volatility": annualized_volatility(idx.get("etf_close_return", pd.Series(dtype=float))),
                "nav_mdd": max_drawdown(idx.get("nav_return", pd.Series(dtype=float))),
                "index_mdd": max_drawdown(idx.get("underlying_index_close_return", pd.Series(dtype=float))),
                "etf_close_mdd": max_drawdown(idx.get("etf_close_return", pd.Series(dtype=float))),
            }
        )
    return pd.DataFrame(rows)


def weight_differences(pdf_weights: pd.DataFrame, cap20_weights: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pdf = pdf_weights[pdf_weights["stock_code"] != CASH_CODE][["date", "stock_code", "stock_name", "weight"]].rename(
        columns={"weight": "pdf_weight"}
    )
    cap = cap20_weights[["date", "stock_code", "stock_name", "weight"]].rename(
        columns={"weight": "cap20_weight", "stock_name": "cap20_stock_name"}
    )
    diff = pdf.merge(cap, on=["date", "stock_code"], how="outer")
    diff["stock_name"] = diff["stock_name"].fillna(diff["cap20_stock_name"]).fillna(diff["stock_code"])
    diff = diff.drop(columns=["cap20_stock_name"])
    diff[["pdf_weight", "cap20_weight"]] = diff[["pdf_weight", "cap20_weight"]].fillna(0.0)
    diff["active_weight"] = diff["cap20_weight"] - diff["pdf_weight"]
    diff["abs_active_weight"] = diff["active_weight"].abs()
    by_stock = (
        diff.groupby(["stock_code", "stock_name"], as_index=False)
        .agg(
            mean_active_weight=("active_weight", "mean"),
            mean_abs_active_weight=("abs_active_weight", "mean"),
            max_abs_active_weight=("abs_active_weight", "max"),
        )
        .sort_values("mean_abs_active_weight", ascending=False)
    )
    return diff.sort_values(["date", "stock_code"]), by_stock


def run_benchmark_replication() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    price = load_price()
    raw_pdf = load_pdf_history()
    pdf, pdf_event_adjustments = adjust_pdf_cash_substitution(raw_pdf)

    pdf_returns, pdf_weights = compute_pdf_benchmark(price, pdf)
    cap20_returns, cap20_weights = compute_cap20_drift_benchmark(price, pdf, frequency="methodology")
    official_rebalance_dates = methodology_rebalance_dates(
        pd.DatetimeIndex(
            sorted(price.loc[price["date"] >= pd.Timestamp(BACKTEST_START), "date"].dropna().unique())
        )
    )
    comparison = compare_benchmarks(pdf_returns, cap20_returns)
    risk_summary = risk_period_summary(comparison)
    pdf_returns.to_csv(OUTPUT_DIR / "benchmark_pdf_returns.csv", index=False, encoding="utf-8-sig")
    pdf_weights.to_csv(OUTPUT_DIR / "benchmark_pdf_weights.csv", index=False, encoding="utf-8-sig")
    pdf_event_adjustments.to_csv(
        OUTPUT_DIR / "benchmark_pdf_event_adjustment_audit.csv", index=False, encoding="utf-8-sig"
    )
    cap20_returns.to_csv(OUTPUT_DIR / "benchmark_cap20_returns.csv", index=False, encoding="utf-8-sig")
    cap20_weights.to_csv(OUTPUT_DIR / "benchmark_cap20_weights.csv", index=False, encoding="utf-8-sig")
    for legacy_monthly_file in [
        OUTPUT_DIR / "benchmark_cap20_monthly_returns.csv",
        OUTPUT_DIR / "benchmark_cap20_monthly_weights.csv",
    ]:
        legacy_monthly_file.unlink(missing_ok=True)
    comparison.to_csv(OUTPUT_DIR / "benchmark_actual_etf_comparison.csv", index=False, encoding="utf-8-sig")
    risk_summary.to_csv(OUTPUT_DIR / "risk_period_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "rebalance_date": [d.strftime("%Y-%m-%d") for d in official_rebalance_dates],
            "rule": "June/December options-expiry next-week first business day; plus ETF listing/start date",
        }
    ).to_csv(OUTPUT_DIR / "benchmark_cap20_rebalance_schedule.csv", index=False, encoding="utf-8-sig")

    ret_idx = comparison.set_index("date")
    summaries = []
    benchmarks = {
        "pdf_replication": ret_idx.get("pdf_return"),
        "cap20_methodology": ret_idx.get("cap20_return"),
        "etf_close": ret_idx.get("etf_close_return"),
        "nav": ret_idx.get("nav_return"),
        "underlying_index": ret_idx.get("underlying_index_close_return"),
    }
    pdf_bm = benchmarks["pdf_replication"]
    for name, series in benchmarks.items():
        if series is not None:
            summaries.append(performance_summary(series, pdf_bm if name != "pdf_replication" else None, name))
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUTPUT_DIR / "benchmark_performance_summary.csv", index=False, encoding="utf-8-sig")

    common_cols = [
        "pdf_return",
        "cap20_return",
        "etf_close_return",
        "nav_return",
        "underlying_index_close_return",
    ]
    common_cols = [c for c in common_cols if c in ret_idx.columns]
    common_ret = ret_idx[common_cols].dropna()
    common_summaries = []
    if not common_ret.empty:
        common_map = {
            "pdf_replication_common_dates": common_ret.get("pdf_return"),
            "cap20_methodology_common_dates": common_ret.get("cap20_return"),
            "etf_close_common_dates": common_ret.get("etf_close_return"),
            "nav_common_dates": common_ret.get("nav_return"),
            "underlying_index_common_dates": common_ret.get("underlying_index_close_return"),
        }
        common_pdf = common_map["pdf_replication_common_dates"]
        for name, series in common_map.items():
            if series is not None:
                common_summaries.append(
                    performance_summary(series, common_pdf if name != "pdf_replication_common_dates" else None, name)
                )
    common_summary_df = pd.DataFrame(common_summaries)
    common_summary_df.to_csv(
        OUTPUT_DIR / "benchmark_performance_summary_common_dates.csv", index=False, encoding="utf-8-sig"
    )

    return {
        "pdf_returns": pdf_returns,
        "pdf_weights": pdf_weights,
        "cap20_returns": cap20_returns,
        "cap20_weights": cap20_weights,
        "comparison": comparison,
        "summary": summary_df,
        "risk_period_summary": risk_summary,
    }


if __name__ == "__main__":
    run_benchmark_replication()
