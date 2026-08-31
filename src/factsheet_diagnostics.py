from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from performance import (
    annualized_return,
    annualized_volatility,
    cumulative_return,
    drawdown_series,
    information_ratio,
    max_drawdown,
    sharpe_ratio,
    tracking_error,
)
from project_paths import OUTPUT_DIR, ensure_output_dir


STRATEGY_NAME = "consensus_active_mvo_te20_ra1_min1"
STRATEGY_LABEL = "AI전력핵심설비액티브"
INDEX_LABEL = "iSelect AI전력핵심설비지수"
WINE = "#9E2A2F"
GREY = "#8A8A8A"
LIGHT_GREY = "#D9D9D9"


plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False


def _pct(x: float) -> str:
    return "" if pd.isna(x) else f"{x * 100:.2f}%"


def _pctp(x: float) -> str:
    return "" if pd.isna(x) else f"{x * 100:+.2f}%p"


def _load_common_returns() -> pd.DataFrame:
    strategy = pd.read_csv(OUTPUT_DIR / "advanced_experiment_returns.csv", parse_dates=["date"])
    strategy = strategy[strategy["experiment_name"].eq(STRATEGY_NAME)].copy()
    strategy = strategy[["date", "strategy_return", "benchmark_pdf_return"]]

    actual = pd.read_csv(OUTPUT_DIR / "benchmark_actual_etf_comparison.csv", parse_dates=["date"])
    actual = actual[["date", "underlying_index_close_return", "nav_return", "etf_close_return", "pdf_return"]]

    merged = strategy.merge(actual, on="date", how="inner").sort_values("date")
    merged = merged.dropna(subset=["strategy_return", "underlying_index_close_return"]).copy()
    merged["active_return_vs_index"] = merged["strategy_return"] - merged["underlying_index_close_return"]
    merged["strategy_wealth"] = (1.0 + merged["strategy_return"]).cumprod() * 100.0
    merged["index_wealth"] = (1.0 + merged["underlying_index_close_return"]).cumprod() * 100.0
    merged["strategy_cumulative_return"] = merged["strategy_wealth"] / 100.0 - 1.0
    merged["index_cumulative_return"] = merged["index_wealth"] / 100.0 - 1.0
    merged.to_csv(OUTPUT_DIR / "factsheet_strategy_vs_index_returns.csv", index=False, encoding="utf-8-sig")
    return merged


def _summary_row(label: str, returns: pd.Series, benchmark: pd.Series | None = None) -> dict:
    out = {
        "name": label,
        "observations": int(returns.dropna().shape[0]),
        "cumulative_return": cumulative_return(returns),
        "annualized_return": annualized_return(returns),
        "annualized_volatility": annualized_volatility(returns),
        "sharpe_ratio": sharpe_ratio(returns),
        "max_drawdown": max_drawdown(returns),
    }
    if benchmark is not None:
        active = returns - benchmark
        out.update(
            {
                "excess_cumulative_return_pct_point": cumulative_return(returns) - cumulative_return(benchmark),
                "tracking_error_vs_index": tracking_error(active),
                "information_ratio_vs_index": information_ratio(active),
                "correlation_vs_index": float(returns.corr(benchmark)) if len(active.dropna()) >= 2 else np.nan,
                "active_mean_daily": float(active.dropna().mean()) if not active.dropna().empty else np.nan,
            }
        )
    else:
        out.update(
            {
                "excess_cumulative_return_pct_point": np.nan,
                "tracking_error_vs_index": np.nan,
                "information_ratio_vs_index": np.nan,
                "correlation_vs_index": np.nan,
                "active_mean_daily": np.nan,
            }
        )
    return out


def _save_summary(common: pd.DataFrame) -> pd.DataFrame:
    s = common.set_index("date")["strategy_return"].astype(float)
    b = common.set_index("date")["underlying_index_close_return"].astype(float)
    rows = [
        _summary_row(STRATEGY_LABEL, s, b),
        _summary_row(INDEX_LABEL, b, None),
    ]
    summary = pd.DataFrame(rows)
    summary["start_date"] = common["date"].min().date().isoformat()
    summary["end_date"] = common["date"].max().date().isoformat()
    summary.to_csv(OUTPUT_DIR / "factsheet_performance_summary.csv", index=False, encoding="utf-8-sig")

    pretty = summary.copy()
    pct_cols = [
        "cumulative_return",
        "annualized_return",
        "annualized_volatility",
        "max_drawdown",
        "excess_cumulative_return_pct_point",
        "tracking_error_vs_index",
        "active_mean_daily",
    ]
    for col in pct_cols:
        if col in pretty.columns:
            pretty[col] = pretty[col].map(_pct if col != "excess_cumulative_return_pct_point" else _pctp)
    for col in ["sharpe_ratio", "information_ratio_vs_index", "correlation_vs_index"]:
        pretty[col] = pretty[col].map(lambda x: "" if pd.isna(x) else f"{x:.3f}")
    pretty.to_csv(OUTPUT_DIR / "factsheet_performance_summary_pretty.csv", index=False, encoding="utf-8-sig")
    return summary


def _period_return(series: pd.Series, dates: pd.DatetimeIndex, start: pd.Timestamp) -> float:
    r = series.loc[dates >= start].dropna()
    return cumulative_return(r)


def _save_period_returns(common: pd.DataFrame) -> pd.DataFrame:
    data = common.set_index("date")
    end = data.index.max()
    periods = [
        ("MTD", pd.Timestamp(end.year, end.month, 1)),
        ("YTD", pd.Timestamp(end.year, 1, 1)),
        ("1M", end - pd.DateOffset(months=1)),
        ("3M", end - pd.DateOffset(months=3)),
        ("6M", end - pd.DateOffset(months=6)),
        ("1Y", end - pd.DateOffset(years=1)),
        ("Since inception", data.index.min()),
    ]
    rows = []
    for label, start in periods:
        strategy_ret = _period_return(data["strategy_return"], data.index, start)
        index_ret = _period_return(data["underlying_index_close_return"], data.index, start)
        rows.append(
            {
                "period": label,
                "start_date": data.index[data.index >= start].min().date().isoformat(),
                "end_date": end.date().isoformat(),
                "strategy_return": strategy_ret,
                "underlying_index_return": index_ret,
                "excess_return_pct_point": strategy_ret - index_ret,
            }
        )
    period = pd.DataFrame(rows)
    period.to_csv(OUTPUT_DIR / "factsheet_period_returns.csv", index=False, encoding="utf-8-sig")
    pretty = period.copy()
    for col in ["strategy_return", "underlying_index_return"]:
        pretty[col] = pretty[col].map(_pct)
    pretty["excess_return_pct_point"] = pretty["excess_return_pct_point"].map(_pctp)
    pretty.to_csv(OUTPUT_DIR / "factsheet_period_returns_pretty.csv", index=False, encoding="utf-8-sig")
    return period


def _save_monthly_and_calendar_returns(common: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = common.set_index("date")
    monthly = pd.DataFrame(
        {
            "strategy_return": (1.0 + data["strategy_return"]).resample("ME").prod() - 1.0,
            "underlying_index_return": (1.0 + data["underlying_index_close_return"]).resample("ME").prod() - 1.0,
        }
    ).dropna()
    monthly["excess_return_pct_point"] = monthly["strategy_return"] - monthly["underlying_index_return"]
    monthly = monthly.reset_index()
    monthly["year"] = monthly["date"].dt.year
    monthly["month"] = monthly["date"].dt.month
    monthly.to_csv(OUTPUT_DIR / "factsheet_monthly_returns.csv", index=False, encoding="utf-8-sig")

    calendar = pd.DataFrame(
        {
            "strategy_return": (1.0 + data["strategy_return"]).resample("YE").prod() - 1.0,
            "underlying_index_return": (1.0 + data["underlying_index_close_return"]).resample("YE").prod() - 1.0,
        }
    ).dropna()
    calendar["excess_return_pct_point"] = calendar["strategy_return"] - calendar["underlying_index_return"]
    calendar = calendar.reset_index()
    calendar["year"] = calendar["date"].dt.year
    calendar = calendar[["year", "strategy_return", "underlying_index_return", "excess_return_pct_point"]]
    calendar.to_csv(OUTPUT_DIR / "factsheet_calendar_year_returns.csv", index=False, encoding="utf-8-sig")

    pretty = calendar.copy()
    for col in ["strategy_return", "underlying_index_return"]:
        pretty[col] = pretty[col].map(_pct)
    pretty["excess_return_pct_point"] = pretty["excess_return_pct_point"].map(_pctp)
    pretty.to_csv(OUTPUT_DIR / "factsheet_calendar_year_returns_pretty.csv", index=False, encoding="utf-8-sig")
    return monthly, calendar


def _save_holdings() -> pd.DataFrame:
    holdings = pd.read_csv(OUTPUT_DIR / "final_latest_weight_comparison.csv", dtype={"stock_code": str})
    holdings["stock_code"] = holdings["stock_code"].str.zfill(6)
    holdings = holdings.sort_values("weight", ascending=False).copy()
    holdings["strategy_weight"] = holdings["weight"]
    holdings["pdf_weight"] = holdings["pdf_weight"]
    cols = ["date", "stock_code", "stock_name", "strategy_weight", "pdf_weight", "active_weight"]
    holdings[cols].to_csv(OUTPUT_DIR / "factsheet_latest_holdings.csv", index=False, encoding="utf-8-sig")
    top = holdings[cols].head(10).copy()
    top.to_csv(OUTPUT_DIR / "factsheet_top10_holdings.csv", index=False, encoding="utf-8-sig")
    pretty = top.copy()
    for col in ["strategy_weight", "pdf_weight", "active_weight"]:
        pretty[col] = pretty[col].map(_pct if col != "active_weight" else _pctp)
    pretty.to_csv(OUTPUT_DIR / "factsheet_top10_holdings_pretty.csv", index=False, encoding="utf-8-sig")
    return top


def _save_key_info(common: pd.DataFrame) -> pd.DataFrame:
    summary = pd.read_csv(OUTPUT_DIR / "advanced_experiment_presentation_summary.csv")
    final = summary[summary["experiment_name"].eq(STRATEGY_NAME)].iloc[0]
    rebalance_one_way = np.nan
    rebalance_total_traded = np.nan
    turnover_path = OUTPUT_DIR / "consensus_score_strategy_turnover_diagnostics.csv"
    if turnover_path.exists():
        turnover = pd.read_csv(turnover_path)
        if "experiment_name" in turnover.columns:
            turnover = turnover[turnover["experiment_name"].eq(STRATEGY_NAME)].copy()
        if not turnover.empty:
            rebalance_one_way = float(turnover["realized_turnover_after_limit"].mean())
            if "traded_weight_after_limit" in turnover.columns:
                rebalance_total_traded = float(turnover["traded_weight_after_limit"].mean())
            elif "total_traded_weight" in turnover.columns:
                rebalance_total_traded = float(turnover["total_traded_weight"].mean())
    rows = [
        ("Factsheet date", common["date"].max().date().isoformat()),
        ("Strategy", "Consensus Active MVO"),
        ("Benchmark", "iSelect AI전력핵심설비 지수"),
        ("Universe", "KODEX AI전력핵심설비 ETF KRX PDF constituents"),
        ("Rebalancing", "Weekly"),
        ("Factor score", "Equal-weighted EPS revision 1M, target upside, rating point"),
        ("MVO TE budget", "20% ex-ante annualized"),
        ("Max stock weight", "50%"),
        ("One-way turnover limit", "30%"),
        ("Average one-way turnover (all dates)", _pct(float(final["average_turnover"]))),
        ("Average one-way turnover (rebalance dates)", _pct(rebalance_one_way)),
        ("Average total traded weight (rebalance dates)", _pct(rebalance_total_traded)),
        ("Trading cost impact", _pctp(float(final["total_trading_cost_return"]))),
        ("Fund fee/expense impact", _pctp(float(final["total_fund_expense_return"]))),
    ]
    info = pd.DataFrame(rows, columns=["item", "value"])
    info.to_csv(OUTPUT_DIR / "factsheet_key_info.csv", index=False, encoding="utf-8-sig")
    return info


def _plot_cumulative(common: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.2))
    strategy_cum = common["strategy_cumulative_return"] * 100.0
    index_cum = common["index_cumulative_return"] * 100.0
    ax.plot(common["date"], index_cum, color=GREY, linewidth=2.2, label=INDEX_LABEL)
    ax.plot(
        common["date"],
        strategy_cum,
        color=WINE,
        linewidth=2.8,
        label=STRATEGY_LABEL,
    )
    ax.set_title("누적수익률")
    ax.set_ylabel("누적수익률(%)")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_factsheet_cumulative_vs_index.png", dpi=220)
    fig.savefig(OUTPUT_DIR / "chart_factsheet_cumulative_vs_index_cost_reflected.png", dpi=220)
    fig.savefig(OUTPUT_DIR / "chart_factsheet_cumulative_return_vs_index_cost_reflected.png", dpi=220)
    fig.savefig(OUTPUT_DIR / "chart_factsheet_cumulative_return_clean_kr.png", dpi=220)
    plt.close(fig)


def _plot_drawdown(common: pd.DataFrame) -> None:
    data = common.set_index("date")
    strategy_dd = drawdown_series(data["strategy_return"])
    index_dd = drawdown_series(data["underlying_index_close_return"])
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.plot(index_dd.index, index_dd * 100.0, color=GREY, linewidth=2.0, label=INDEX_LABEL)
    ax.plot(strategy_dd.index, strategy_dd * 100.0, color=WINE, linewidth=2.4, label=STRATEGY_LABEL)
    ax.fill_between(strategy_dd.index, strategy_dd * 100.0, 0, color=WINE, alpha=0.08)
    ax.set_title("Drawdown")
    ax.set_ylabel("낙폭(%)")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_factsheet_drawdown_vs_index.png", dpi=220)
    plt.close(fig)


def _plot_period_returns(period: pd.DataFrame) -> None:
    plot = period[period["period"].isin(["MTD", "YTD", "1M", "3M", "6M", "1Y", "Since inception"])].copy()
    x = np.arange(len(plot))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(x - width / 2, plot["underlying_index_return"] * 100.0, width=width, color=GREY, label=INDEX_LABEL)
    ax.bar(x + width / 2, plot["strategy_return"] * 100.0, width=width, color=WINE, label=STRATEGY_LABEL)
    ax.set_xticks(x)
    ax.set_xticklabels(plot["period"], rotation=0)
    ax.set_ylabel("수익률(%)")
    ax.set_title("기간별 수익률")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_factsheet_period_returns_vs_index.png", dpi=220)
    plt.close(fig)


def _plot_monthly_active(common: pd.DataFrame) -> None:
    data = common.set_index("date")
    active = data["strategy_return"] - data["underlying_index_close_return"]
    rolling = active.rolling(60, min_periods=30).std() * np.sqrt(252)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(rolling.index, rolling * 100.0, color=WINE, linewidth=2.2, label="60일 Rolling TE")
    ax.axhline(20.0, color=GREY, linestyle="--", linewidth=1.5, label="TE 기준 20%")
    ax.set_title("Rolling Active Risk")
    ax.set_ylabel("연환산 TE(%)")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_factsheet_rolling_te_vs_index.png", dpi=220)
    plt.close(fig)


def run_factsheet_diagnostics() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    common = _load_common_returns()
    summary = _save_summary(common)
    period = _save_period_returns(common)
    monthly, calendar = _save_monthly_and_calendar_returns(common)
    holdings = _save_holdings()
    info = _save_key_info(common)
    _plot_cumulative(common)
    _plot_drawdown(common)
    _plot_period_returns(period)
    _plot_monthly_active(common)
    return {
        "returns": common,
        "summary": summary,
        "period_returns": period,
        "monthly_returns": monthly,
        "calendar_returns": calendar,
        "holdings": holdings,
        "key_info": info,
    }


if __name__ == "__main__":
    outputs = run_factsheet_diagnostics()
    print(outputs["summary"].to_string(index=False))
