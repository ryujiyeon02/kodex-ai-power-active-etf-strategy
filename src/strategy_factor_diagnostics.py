import numpy as np
import pandas as pd
import warnings

from project_paths import MODEL_PANEL_FILE, OUTPUT_DIR, ensure_output_dir
from factor_utils import prepare_signal_source, zscore_cross_section
from selected_factor_config import SELECTED_FACTOR_SPECS


warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

FACTOR_SPECS = [
    (spec["factor"], spec["theme"], float(spec["weight"]), float(spec["direction"]))
    for spec in SELECTED_FACTOR_SPECS
]


def make_signal_table(g: pd.DataFrame) -> pd.DataFrame:
    source = prepare_signal_source(g)
    out = source[["stock_code", "stock_name"]].copy()
    score = pd.Series(0.0, index=source.index)
    theme_scores: dict[str, pd.Series] = {}
    theme_weights: dict[str, float] = {}
    for col, theme, weight, direction in FACTOR_SPECS:
        if col in source.columns:
            z = zscore_cross_section(source[col]) * direction
        else:
            z = pd.Series(0.0, index=source.index)
        out[f"z_{col}"] = z.values
        score += weight * z
        theme_scores[theme] = theme_scores.get(theme, pd.Series(0.0, index=source.index)) + weight * z
        theme_weights[theme] = theme_weights.get(theme, 0.0) + weight
    for theme, theme_score in theme_scores.items():
        denom = theme_weights.get(theme, 1.0)
        theme_signal = theme_score / denom if denom else theme_score
        out[theme] = (theme_signal - theme_signal.mean()).values
    out["composite"] = (score - score.mean()).values
    return out.set_index("stock_code").sort_index()


def _spearman_ic(x: pd.Series, y: pd.Series) -> float:
    aligned = pd.concat([x, y], axis=1).dropna()
    if len(aligned) < 4 or aligned.iloc[:, 0].nunique() < 2 or aligned.iloc[:, 1].nunique() < 2:
        return np.nan
    return float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))


def _tercile_return(signal: pd.Series, future_return: pd.Series) -> tuple[float, int, int]:
    aligned = pd.concat([signal, future_return], axis=1).dropna()
    if len(aligned) < 4:
        return np.nan, 0, 0
    aligned.columns = ["signal", "future_return"]
    k = max(2, len(aligned) // 3)
    ranked = aligned.sort_values("signal")
    bottom = ranked.head(k)
    top = ranked.tail(k)
    if len(top) < 2 or len(bottom) < 2:
        return np.nan, len(top), len(bottom)
    return float(top["future_return"].mean() - bottom["future_return"].mean()), len(top), len(bottom)


def build_factor_ic_monthly(panel: pd.DataFrame) -> pd.DataFrame:
    panel = build_exhaustive_candidate_source(panel.copy())
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values(["date", "stock_code"])
    ret_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    month_end_dates = panel.groupby(panel["date"].dt.to_period("M"))["date"].max().sort_values().tolist()

    rows = []
    factor_theme = {factor: theme for factor, theme, _, _ in FACTOR_SPECS}
    for i, date in enumerate(month_end_dates[:-1]):
        next_date = month_end_dates[i + 1]
        g = panel[panel["date"] == date].copy()
        if g.empty:
            continue
        signals = make_signal_table(g)
        forward = (1.0 + ret_mat.loc[(ret_mat.index > date) & (ret_mat.index <= next_date)]).prod() - 1.0
        forward = forward.reindex(signals.index)
        for factor, theme, _, _ in FACTOR_SPECS:
            col = f"z_{factor}"
            if col not in signals.columns:
                continue
            ic = _spearman_ic(signals[col], forward)
            tmb, top_n, bottom_n = _tercile_return(signals[col], forward)
            rows.append(
                {
                    "date": date,
                    "factor": factor,
                    "theme": factor_theme.get(factor, theme),
                    "ic": ic,
                    "top_minus_bottom_return": tmb,
                    "top_group_count": top_n,
                    "bottom_group_count": bottom_n,
                }
            )
    return pd.DataFrame(rows)


def _candidate_theme(col: str) -> str:
    if (
        col.startswith(("forward_per", "per_", "pbr_", "psr_", "dividend_yield"))
        or col.startswith(("neg_forward_per", "neg_per_", "neg_pbr_", "neg_psr_"))
        or col in {"earnings_yield_per", "book_to_price_pbr", "sales_to_price_psr"}
    ):
        return "valuation"
    if col.startswith(("eps_", "op_", "ni_", "sales_")) or col in {"eps_fy0", "eps_fy1", "eps_fy2"}:
        return "consensus_quality_growth"
    if col.startswith("target_"):
        return "target_price"
    if col.startswith("rating_"):
        return "rating"
    if col.startswith("momentum"):
        return "momentum"
    if col.startswith("vol_") or "std" in col or "cv" in col:
        return "risk"
    if col in {"trading_value", "volume", "market_cap", "float_mktcap", "float_shares", "log_trading_value", "log_volume", "log_market_cap"}:
        return "liquidity_size"
    return "other"


def candidate_factor_columns(panel: pd.DataFrame) -> list[str]:
    excluded = {
        "return",
        "date",
        "month",
        "stock_code",
        "stock_name",
        "etf_weight_pct",
        "etf_weight_lag1_pct",
        "raw_float_weight",
        "cap20_weight",
        "raw_float_weight_pct",
        "cap20_weight_pct",
        "close",
        "adj_close",
        "fy0",
        "fy1",
        "fy2",
        "fy3",
        "ev_ebitda",
        "ev_ebitda_lag1",
        "neg_ev_ebitda",
        "neg_ev_ebitda_lag1",
        "dps_common_cash_krw",
        "dps_common_cash_krw_lag1",
        "cash_dividend_total_thousand_krw",
        "cash_dividend_total_thousand_krw_lag1",
    }
    source = prepare_signal_source(panel)
    numeric_cols = []
    for col in source.columns:
        if col in excluded or col.startswith("fiscal_year") or col.startswith("latest_report_date"):
            continue
        if col.startswith("momentum"):
            continue
        s = pd.to_numeric(source[col], errors="coerce")
        if s.notna().sum() >= 20 and s.nunique(dropna=True) >= 3:
            numeric_cols.append(col)
    preferred = [factor for factor, _, _, _ in FACTOR_SPECS]
    ordered = preferred + [c for c in numeric_cols if c not in preferred]
    return ordered


def build_exhaustive_candidate_source(panel: pd.DataFrame) -> pd.DataFrame:
    source = prepare_signal_source(panel.copy())
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.sort_values(["stock_code", "date"])

    def num(col: str) -> pd.Series:
        if col not in source.columns:
            return pd.Series(np.nan, index=source.index)
        return pd.to_numeric(source[col], errors="coerce")

    for fy in range(4):
        sales = num(f"sales_fy{fy}")
        op = num(f"op_fy{fy}")
        ni = num(f"ni_fy{fy}")
        eps = num(f"eps_fy{fy}")
        close = num("close").replace(0, np.nan)
        source[f"op_margin_fy{fy}"] = op / sales.replace(0, np.nan)
        source[f"ni_margin_fy{fy}"] = ni / sales.replace(0, np.nan)
        source[f"eps_yield_fy{fy}"] = eps / close
        source[f"log_sales_fy{fy}"] = np.log1p(sales.where(sales > 0))
        source[f"log_op_fy{fy}"] = np.log1p(op.where(op > 0))
        source[f"log_ni_fy{fy}"] = np.log1p(ni.where(ni > 0))

    for left, right in [(0, 1), (1, 2), (2, 3), (0, 2), (1, 3)]:
        for metric in ["sales", "op", "ni", "eps", "op_margin", "ni_margin", "eps_yield"]:
            a = num(f"{metric}_fy{left}")
            b = num(f"{metric}_fy{right}")
            source[f"{metric}_growth_fy{right}_vs_fy{left}"] = (b - a) / a.abs().replace(0, np.nan)
            source[f"{metric}_spread_fy{right}_minus_fy{left}"] = b - a

    def positive_inverse(new_col: str, base_col: str) -> None:
        x = num(base_col)
        source[new_col] = 1.0 / x.where(x > 0)

    positive_inverse("earnings_yield_per", "per_ifrs_consolidated")
    positive_inverse("book_to_price_pbr", "pbr_ifrs_consolidated")
    positive_inverse("sales_to_price_psr", "psr_ifrs_consolidated")
    for fy in range(4):
        positive_inverse(f"earnings_yield_forward_per_fy{fy}", f"forward_per_fy{fy}")

    trading_value = num("trading_value")
    volume = num("volume")
    float_mktcap = num("float_mktcap").replace(0, np.nan)
    market_cap = num("market_cap").replace(0, np.nan)
    float_shares = num("float_shares").replace(0, np.nan)
    source["trading_value_to_float_mktcap"] = trading_value / float_mktcap
    source["trading_value_to_market_cap"] = trading_value / market_cap
    source["volume_to_float_shares"] = volume / float_shares

    ret = num("return")
    adj_close = num("adj_close")
    for window in [60, 120]:
        source[f"vol_{window}d_ann"] = (
            ret.groupby(source["stock_code"]).rolling(window).std().reset_index(level=0, drop=True)
            * np.sqrt(252)
        )
        rolling_high = (
            adj_close.groupby(source["stock_code"])
            .rolling(window)
            .max()
            .reset_index(level=0, drop=True)
        )
        source[f"drawdown_{window}d"] = adj_close / rolling_high.replace(0, np.nan) - 1.0

    revision_base = []
    for fy in range(4):
        for metric in ["sales", "op", "ni", "eps", "op_margin", "ni_margin", "eps_yield", "analyst_count"]:
            col = f"{metric}_fy{fy}"
            if col in source.columns:
                revision_base.append(col)
    revision_base += [
        col for col in [
            "target_price",
            "target_price_high",
            "target_price_low",
            "target_price_median",
            "target_gap_pct",
            "target_upside",
            "target_confidence",
            "target_total_count",
            "target_revision_balance",
            "rating_point",
            "rating_total_count",
            "rating_revision_balance",
            "per_ifrs_consolidated",
            "pbr_ifrs_consolidated",
            "psr_ifrs_consolidated",
            "dividend_yield_pct",
            "earnings_yield_per",
            "book_to_price_pbr",
            "sales_to_price_psr",
            "trading_value_to_float_mktcap",
            "trading_value_to_market_cap",
            "volume_to_float_shares",
        ] if col in source.columns
    ]
    for horizon in [21, 63, 126]:
        for col in revision_base:
            lag = source.groupby("stock_code")[col].shift(horizon)
            cur = num(col)
            source[f"{col}_revision_{horizon}d"] = (cur - lag) / lag.abs().replace(0, np.nan)
            source[f"{col}_change_{horizon}d"] = cur - lag

    for col in [
        "vol_20d_ann",
        "target_price_cv",
        "target_price_std",
        "target_high_low_spread_pct",
        "float_mktcap_check_ratio",
        "per_ifrs_consolidated",
        "pbr_ifrs_consolidated",
        "psr_ifrs_consolidated",
        "forward_per_fy0",
        "forward_per_fy1",
        "forward_per_fy2",
        "forward_per_fy3",
        "forward_per_current_year",
        "forward_per_next_year",
        "forward_per_year_after_next",
        "forward_per_three_year_forward",
    ]:
        if col in source.columns:
            source[f"neg_{col}"] = -pd.to_numeric(source[col], errors="coerce")

    for col in ["trading_value", "volume", "market_cap", "market_cap_mn", "float_mktcap", "float_shares"]:
        if col in source.columns:
            source[f"log_{col}"] = np.log1p(pd.to_numeric(source[col], errors="coerce").where(pd.to_numeric(source[col], errors="coerce") > 0))

    return source


def exhaustive_factor_columns(source: pd.DataFrame) -> list[str]:
    excluded = {
        "return", "date", "month", "stock_code", "stock_name",
        "etf_weight_pct", "etf_weight_lag1_pct", "raw_float_weight", "cap20_weight",
        "raw_float_weight_pct", "cap20_weight_pct", "close", "adj_close",
        "fy0", "fy1", "fy2",
        "fy3",
        "ev_ebitda",
        "ev_ebitda_lag1",
        "neg_ev_ebitda",
        "neg_ev_ebitda_lag1",
        "dps_common_cash_krw",
        "dps_common_cash_krw_lag1",
        "cash_dividend_total_thousand_krw",
        "cash_dividend_total_thousand_krw_lag1",
    }
    cols = []
    for col in source.columns:
        if col in excluded or col.startswith("fiscal_year") or col.startswith("latest_report_date"):
            continue
        if col.startswith("momentum"):
            continue
        s = pd.to_numeric(source[col], errors="coerce")
        if s.notna().sum() >= 20 and s.nunique(dropna=True) >= 3:
            cols.append(col)
    return cols


def build_candidate_ic_monthly(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values(["date", "stock_code"])
    ret_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    month_end_dates = panel.groupby(panel["date"].dt.to_period("M"))["date"].max().sort_values().tolist()
    candidates = candidate_factor_columns(panel)
    rows = []
    for i, date in enumerate(month_end_dates[:-1]):
        next_date = month_end_dates[i + 1]
        g = prepare_signal_source(panel[panel["date"] == date].copy())
        if g.empty:
            continue
        g = g.set_index("stock_code")
        forward = (1.0 + ret_mat.loc[(ret_mat.index > date) & (ret_mat.index <= next_date)]).prod() - 1.0
        forward = forward.reindex(g.index)
        for col in candidates:
            if col not in g.columns:
                continue
            raw = pd.to_numeric(g[col], errors="coerce")
            if raw.notna().sum() < 4:
                continue
            z = zscore_cross_section(raw)
            ic = _spearman_ic(z, forward)
            tmb, top_n, bottom_n = _tercile_return(z, forward)
            rows.append(
                {
                    "date": date,
                    "factor": col,
                    "theme": _candidate_theme(col),
                    "ic": ic,
                    "top_minus_bottom_return": tmb,
                    "top_group_count": top_n,
                    "bottom_group_count": bottom_n,
                    "raw_non_missing_count": int(raw.notna().sum()),
                }
            )
    return pd.DataFrame(rows)


def build_exhaustive_ic_monthly(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values(["date", "stock_code"])
    source = build_exhaustive_candidate_source(panel)
    ret_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    month_end_dates = panel.groupby(panel["date"].dt.to_period("M"))["date"].max().sort_values().tolist()
    candidates = exhaustive_factor_columns(source)
    rows = []
    for i, date in enumerate(month_end_dates[:-1]):
        next_date = month_end_dates[i + 1]
        g = source[source["date"] == date].copy()
        if g.empty:
            continue
        g = g.set_index("stock_code")
        forward = (1.0 + ret_mat.loc[(ret_mat.index > date) & (ret_mat.index <= next_date)]).prod() - 1.0
        forward = forward.reindex(g.index)
        for col in candidates:
            if col not in g.columns:
                continue
            raw = pd.to_numeric(g[col], errors="coerce")
            if raw.notna().sum() < 4:
                continue
            z = zscore_cross_section(raw)
            ic = _spearman_ic(z, forward)
            tmb, top_n, bottom_n = _tercile_return(z, forward)
            rows.append(
                {
                    "date": date,
                    "factor": col,
                    "theme": _candidate_theme(col),
                    "ic": ic,
                    "top_minus_bottom_return": tmb,
                    "top_group_count": top_n,
                    "bottom_group_count": bottom_n,
                    "raw_non_missing_count": int(raw.notna().sum()),
                    "candidate_source": "exhaustive_generated",
                }
            )
    return pd.DataFrame(rows)


def summarize_factor_ic(monthly: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return pd.DataFrame()
    rows = []
    for (factor, theme), g in monthly.groupby(["factor", "theme"]):
        ic = pd.to_numeric(g["ic"], errors="coerce").dropna()
        tmb = pd.to_numeric(g["top_minus_bottom_return"], errors="coerce").dropna()
        ic_std = ic.std(ddof=1) if len(ic) >= 2 else np.nan
        rows.append(
            {
                "factor": factor,
                "theme": theme,
                "observations": int(len(ic)),
                "mean_ic": float(ic.mean()) if len(ic) else np.nan,
                "median_ic": float(ic.median()) if len(ic) else np.nan,
                "ic_std": float(ic_std) if pd.notna(ic_std) else np.nan,
                "ic_ir": float(ic.mean() / ic_std) if pd.notna(ic_std) and ic_std != 0 else np.nan,
                "hit_ratio_ic_positive": float((ic > 0).mean()) if len(ic) else np.nan,
                "mean_top_minus_bottom_return": float(tmb.mean()) if len(tmb) else np.nan,
                "hit_ratio_top_minus_bottom_positive": float((tmb > 0).mean()) if len(tmb) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("mean_ic", ascending=False)


def build_factor_family_validation(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    families = ["composite"] + sorted({theme for _, theme, _, _ in FACTOR_SPECS})
    for family in families:
        related = summary.copy() if family == "composite" else summary[summary["theme"] == family].copy()
        observations = int(related["observations"].sum()) if not related.empty else 0
        mean_ic = related["mean_ic"].mean() if not related.empty else np.nan
        hit = related["hit_ratio_ic_positive"].mean() if not related.empty else np.nan
        mean_tmb = related["mean_top_minus_bottom_return"].mean() if not related.empty else np.nan
        if observations < 6:
            comment = "insufficient data"
        elif pd.notna(mean_ic) and mean_ic <= 0:
            comment = "not supported"
        elif pd.notna(mean_ic) and pd.notna(hit) and mean_ic > 0 and hit > 0.5:
            comment = "supported"
        else:
            comment = "mixed"
        rows.append(
            {
                "factor_family": family,
                "related_factors": ",".join(related["factor"].tolist()) if not related.empty else "",
                "mean_related_factor_ic": mean_ic,
                "hit_ratio_related_factor_ic_positive": hit,
                "mean_related_top_minus_bottom_return": mean_tmb,
                "observations": observations,
                "comment": comment,
            }
        )
    return pd.DataFrame(rows)


def run_strategy_factor_diagnostics() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    panel = pd.read_csv(MODEL_PANEL_FILE, dtype={"stock_code": str}, low_memory=False)
    monthly = build_factor_ic_monthly(panel)
    summary = summarize_factor_ic(monthly)
    candidate_monthly = build_candidate_ic_monthly(panel)
    candidate_summary = summarize_factor_ic(candidate_monthly)
    exhaustive_monthly = build_exhaustive_ic_monthly(panel)
    exhaustive_summary = summarize_factor_ic(exhaustive_monthly)
    validation = build_factor_family_validation(summary)
    monthly.to_csv(OUTPUT_DIR / "strategy_factor_ic_monthly.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / "strategy_factor_ic_summary.csv", index=False, encoding="utf-8-sig")
    candidate_monthly.to_csv(OUTPUT_DIR / "strategy_factor_candidate_ic_monthly.csv", index=False, encoding="utf-8-sig")
    candidate_summary.to_csv(OUTPUT_DIR / "strategy_factor_candidate_ic_summary.csv", index=False, encoding="utf-8-sig")
    exhaustive_monthly.to_csv(OUTPUT_DIR / "strategy_factor_exhaustive_ic_monthly.csv", index=False, encoding="utf-8-sig")
    exhaustive_summary.to_csv(OUTPUT_DIR / "strategy_factor_exhaustive_ic_summary.csv", index=False, encoding="utf-8-sig")
    validation.to_csv(OUTPUT_DIR / "strategy_factor_family_validation.csv", index=False, encoding="utf-8-sig")
    return {
        "monthly": monthly,
        "summary": summary,
        "candidate_monthly": candidate_monthly,
        "candidate_summary": candidate_summary,
        "exhaustive_monthly": exhaustive_monthly,
        "exhaustive_summary": exhaustive_summary,
        "factor_family_validation": validation,
    }


if __name__ == "__main__":
    run_strategy_factor_diagnostics()
