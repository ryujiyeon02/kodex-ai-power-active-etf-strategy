from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import norm


plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = Path("output")
FINAL_EXPERIMENT = "consensus_active_mvo_te20_ra1_min1"
TRADING_DAYS = 252
DSR_MAIN_SCENARIO = "reported_spec_rows_conservative"


def _pct(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return ""
    return f"{x * 100:.{digits}f}%"


def _pctp(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return ""
    return f"{x * 100:.{digits}f}%p"


def _krw_uk(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return ""
    return f"{x / 1e8:.{digits}f}억 원"


def _cumulative_return(r: pd.Series) -> float:
    r = pd.to_numeric(r, errors="coerce").dropna()
    if r.empty:
        return np.nan
    return float((1.0 + r).prod() - 1.0)


def _annualized_vol(r: pd.Series) -> float:
    r = pd.to_numeric(r, errors="coerce").dropna()
    if len(r) < 2:
        return np.nan
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def _drawdown_frame(r: pd.DataFrame) -> pd.DataFrame:
    out = r.dropna(subset=["strategy_return"]).copy()
    out["wealth"] = (1.0 + out["strategy_return"]).cumprod()
    out["running_peak"] = out["wealth"].cummax().clip(lower=1.0)
    out["drawdown"] = out["wealth"] / out["running_peak"] - 1.0
    return out


def _deflated_sharpe_ratio(returns: pd.Series, trial_count: int) -> dict[str, float]:
    """Bailey/Lopez de Prado style DSR using the tested strategy count as trials."""
    r = pd.to_numeric(returns, errors="coerce").dropna()
    n = len(r)
    if n < 5 or r.std(ddof=1) == 0 or trial_count < 1:
        return {
            "deflated_sharpe_ratio": np.nan,
            "expected_max_sharpe_ann": np.nan,
            "trial_count": trial_count,
        }

    sr_daily = float(r.mean() / r.std(ddof=1))
    sr_ann = float(sr_daily * np.sqrt(TRADING_DAYS))
    skew = float(r.skew())
    kurt = float(r.kurtosis() + 3.0)
    denom = 1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * sr_daily**2
    se_daily = float(np.sqrt(max(denom, 1e-12) / (n - 1.0)))

    # Expected maximum of N standard normals, as used in the DSR adjustment.
    gamma = 0.5772156649015329
    trials = max(int(trial_count), 1)
    if trials == 1:
        expected_max_z = 0.0
    else:
        expected_max_z = float(
            (1.0 - gamma) * norm.ppf(1.0 - 1.0 / trials)
            + gamma * norm.ppf(1.0 - 1.0 / (trials * np.e))
        )
    expected_max_sr_daily = se_daily * expected_max_z
    z_value = (sr_daily - expected_max_sr_daily) / se_daily if se_daily > 0 else np.nan

    return {
        "deflated_sharpe_ratio": float(norm.cdf(z_value)) if pd.notna(z_value) else np.nan,
        "sample_sharpe_ann_for_dsr": sr_ann,
        "expected_max_sharpe_ann": float(expected_max_sr_daily * np.sqrt(TRADING_DAYS)),
        "trial_count": trials,
        "skewness": skew,
        "kurtosis": kurt,
        "z_value": float(z_value) if pd.notna(z_value) else np.nan,
    }


def _build_dsr_trial_count_table() -> pd.DataFrame:
    """Define transparent trial-count scenarios for Deflated Sharpe Ratio."""
    before_after = pd.read_csv(OUTPUT_DIR / "final_mvo_before_after_comparison.csv")
    robustness = pd.read_csv(OUTPUT_DIR / "final_strategy_robustness_summary.csv")

    # Two non-MVO score-tilt baselines plus the final MVO candidate.
    core_candidate_count = int(len(before_after))
    non_mvo_candidate_count = max(core_candidate_count - 1, 0)

    metric_cols = [
        "cumulative_return",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "tracking_error",
        "information_ratio",
        "average_turnover",
        "total_trading_cost_return",
    ]
    unique_robustness_paths = int(
        robustness[metric_cols].round(10).astype(str).agg("|".join, axis=1).nunique()
    )

    rows = [
        {
            "scenario": "core_candidate_set",
            "trial_count": core_candidate_count,
            "used_as_main": False,
            "basis": (
                "MVO 적용 전 단순 점수 틸트, MVO 적용 전 공격형 점수 틸트, "
                "최종 Consensus Active MVO의 3개 핵심 후보만 trial로 간주"
            ),
        },
        {
            "scenario": "unique_return_paths_current",
            "trial_count": non_mvo_candidate_count + unique_robustness_paths,
            "used_as_main": False,
            "basis": (
                "MVO 적용 전 2개 후보와, 최종 robustness 표에서 성과 경로가 실제로 다른 "
                f"{unique_robustness_paths}개 MVO 경로를 합산"
            ),
        },
        {
            "scenario": "reported_spec_rows_conservative",
            "trial_count": non_mvo_candidate_count + int(len(robustness)),
            "used_as_main": True,
            "basis": (
                "MVO 적용 전 2개 후보와, 발표/README에 남긴 robustness 설정 "
                f"{len(robustness)}개 행을 모두 trial로 간주. 동일 경로 중복도 포함하므로 보수적"
            ),
        },
        {
            "scenario": "broad_stress_legacy",
            "trial_count": 26,
            "used_as_main": False,
            "basis": (
                "이전 실험 과정에서 검토했던 더 넓은 후보 수를 stress trial count로 사용. "
                "현재 본문 전략 선택 기준은 아니며 민감도 점검용"
            ),
        },
    ]
    return pd.DataFrame(rows)


def _save_dsr_diagnostics(returns: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    trial_counts = _build_dsr_trial_count_table()
    rows = []
    for _, row in trial_counts.iterrows():
        dsr = _deflated_sharpe_ratio(returns, int(row["trial_count"]))
        rows.append({**row.to_dict(), **dsr})
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_DIR / "deflated_sharpe_ratio_scenarios.csv", index=False, encoding="utf-8-sig")

    pretty = out.copy()
    pretty["deflated_sharpe_ratio"] = pretty["deflated_sharpe_ratio"].map(_pct)
    pretty["sample_sharpe_ann_for_dsr"] = pretty["sample_sharpe_ann_for_dsr"].map(
        lambda x: f"{x:.2f}" if pd.notna(x) else ""
    )
    pretty["expected_max_sharpe_ann"] = pretty["expected_max_sharpe_ann"].map(
        lambda x: f"{x:.2f}" if pd.notna(x) else ""
    )
    pretty["z_value"] = pretty["z_value"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    pretty.to_csv(
        OUTPUT_DIR / "deflated_sharpe_ratio_scenarios_pretty.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, ax = plt.subplots(figsize=(9, 4.8))
    plot_df = out.sort_values("trial_count").copy()
    colors = ["#b8b8b8" if not bool(x) else "#9f2a31" for x in plot_df["used_as_main"]]
    labels = [
        f"{row.scenario}\nN={int(row.trial_count)}"
        for row in plot_df.itertuples(index=False)
    ]
    bars = ax.bar(labels, plot_df["deflated_sharpe_ratio"] * 100.0, color=colors)
    ax.axhline(50.0, color="#666666", linewidth=1.0, linestyle="--", label="50% 기준")
    for bar, value in zip(bars, plot_df["deflated_sharpe_ratio"] * 100.0):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            value + 1.2,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylim(0, 105)
    ax.set_title("Deflated Sharpe Ratio: trial count 기준별 민감도")
    ax.set_ylabel("DSR (%)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_deflated_sharpe_ratio_scenarios.png", dpi=170)
    plt.close(fig)

    main = out[out["scenario"].eq(DSR_MAIN_SCENARIO)]
    if main.empty:
        main = out[out["used_as_main"].astype(bool)]
    return out, main.iloc[0]


def _save_hhi(weights: pd.DataFrame) -> pd.DataFrame:
    grouped = []
    for date, g in weights.groupby("date"):
        strategy_hhi = float((g["weight"] ** 2).sum())
        pdf_hhi = float((g["pdf_weight"] ** 2).sum())
        grouped.append(
            {
                "date": date,
                "strategy_hhi": strategy_hhi,
                "pdf_hhi": pdf_hhi,
                "strategy_effective_holding_count": 1.0 / strategy_hhi if strategy_hhi > 0 else np.nan,
                "pdf_effective_holding_count": 1.0 / pdf_hhi if pdf_hhi > 0 else np.nan,
                "stock_count": int((g["weight"] > 0).sum()),
            }
        )
    hhi = pd.DataFrame(grouped).sort_values("date")
    hhi.to_csv(OUTPUT_DIR / "final_hhi_timeseries.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(hhi["date"], hhi["strategy_hhi"], color="#9f2a31", linewidth=2.1, label="최종 전략 HHI")
    ax.plot(hhi["date"], hhi["pdf_hhi"], color="#777777", linewidth=1.8, label="PDF HHI")
    ax.set_title("Herfindahl-Hirschman Index: 비중 집중도")
    ax.set_xlabel("날짜")
    ax.set_ylabel("HHI = sum(weight^2)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_hhi_timeseries.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        hhi["date"],
        hhi["strategy_effective_holding_count"],
        color="#9f2a31",
        linewidth=2.1,
        label="최종 전략 effective holdings",
    )
    ax.plot(
        hhi["date"],
        hhi["pdf_effective_holding_count"],
        color="#777777",
        linewidth=1.8,
        label="PDF effective holdings",
    )
    ax.set_title("Effective Number of Holdings")
    ax.set_xlabel("날짜")
    ax.set_ylabel("1 / HHI")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_effective_holdings.png", dpi=170)
    plt.close(fig)
    return hhi


def build_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    OUTPUT_DIR.mkdir(exist_ok=True)
    returns = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_returns.csv", parse_dates=["date"])
    returns = returns[returns["experiment_name"].eq(FINAL_EXPERIMENT)].sort_values("date")
    returns_clean = returns.dropna(subset=["strategy_return", "benchmark_pdf_return"]).copy()
    summary = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_summary.csv")
    final = summary[summary["experiment_name"].eq(FINAL_EXPERIMENT)].iloc[0]
    capacity = pd.read_csv(OUTPUT_DIR / "strategy_capacity_summary.csv")
    psr = pd.read_csv(OUTPUT_DIR / "probabilistic_sharpe_ratio_key_thresholds.csv")
    weights = pd.read_csv(OUTPUT_DIR / "final_strategy_vs_pdf_weights_long.csv", parse_dates=["date"])
    weights = weights[weights["experiment_name"].eq(FINAL_EXPERIMENT)].copy()

    hhi = _save_hhi(weights)
    hhi_latest = hhi.iloc[-1]
    hhi_avg = hhi.mean(numeric_only=True)

    dd = _drawdown_frame(returns_clean)
    worst_dd = dd.loc[dd["drawdown"].idxmin()]
    strategy_return = returns_clean["strategy_return"]
    benchmark_return = returns_clean["benchmark_pdf_return"]
    active_return = strategy_return - benchmark_return
    cost_not_reflected = returns_clean["strategy_cost_not_reflected_return"]
    cumulative_cost_not_reflected = _cumulative_return(cost_not_reflected)
    cumulative_cost_reflected = _cumulative_return(strategy_return)
    cumulative_cost_drag = cumulative_cost_reflected - cumulative_cost_not_reflected

    turnover = pd.to_numeric(returns["turnover"], errors="coerce").fillna(0.0)
    rebalance_turnover = pd.to_numeric(
        returns.loc[returns["is_rebalance"].fillna(False), "turnover"],
        errors="coerce",
    ).fillna(0.0)
    avg_daily_one_way_turnover = float(turnover.mean())
    annualized_one_way_turnover = avg_daily_one_way_turnover * TRADING_DAYS
    average_holding_period_trading_days = (
        TRADING_DAYS / annualized_one_way_turnover if annualized_one_way_turnover > 0 else np.nan
    )
    average_holding_period_calendar_days = average_holding_period_trading_days * 365.0 / TRADING_DAYS

    cap5 = capacity[capacity["participation_rate"].eq(0.05)].iloc[0]
    cap10 = capacity[capacity["participation_rate"].eq(0.10)].iloc[0]
    cap5_split_3d = float(cap5["p05_capacity_krw"]) * 3.0
    cap10_split_3d_p10 = float(cap10["p10_capacity_krw"]) * 3.0
    cap10_split_3d_p05 = float(cap10["p05_capacity_krw"]) * 3.0
    psr0 = psr[psr["threshold_sharpe_ann"].eq(0.0)].iloc[0]
    psr1 = psr[psr["threshold_sharpe_ann"].eq(1.0)].iloc[0]
    psr2 = psr[psr["threshold_sharpe_ann"].eq(2.0)].iloc[0]
    dsr_scenarios, dsr = _save_dsr_diagnostics(strategy_return)
    trial_count = int(dsr["trial_count"])

    metrics_rows = [
        {
            "metric": "Average Holding Periods",
            "value": f"{average_holding_period_trading_days:.1f}거래일 / 약 {average_holding_period_calendar_days:.1f}일",
            "raw_value": average_holding_period_trading_days,
            "definition": "연환산 one-way turnover의 역수로 본 평균 보유기간입니다.",
            "practical_interpretation": (
                "주간 리밸런싱이지만 모든 비중을 매주 갈아엎는 구조는 아니며, "
                f"평균적으로 약 {average_holding_period_trading_days:.1f}거래일마다 보유비중이 한 바퀴 도는 수준입니다."
            ),
        },
        {
            "metric": "Maximum Strategy Capacity",
            "value": (
                "3일 분할 x 10% ADV x 시계열 하위 10% "
                f"{_krw_uk(cap10_split_3d_p10)}"
            ),
            "raw_value": cap10_split_3d_p10,
            "definition": "리밸런싱 주문이 직전 20거래일 평균 거래대금의 일정 비율을 넘지 않는 운용규모 한도입니다.",
            "practical_interpretation": (
                f"발표 기준 capacity는 3일 분할 체결, 하루 10% ADV 참여율, 시계열 하위 10% 기준 {_krw_uk(cap10_split_3d_p10)}입니다. "
                f"1일 체결ㆍ5% ADVㆍ시계열 하위 5% 기준 {_krw_uk(cap5['p05_capacity_krw'])}과 "
                f"3일 분할ㆍ5% ADVㆍ시계열 하위 5% 기준 {_krw_uk(cap5_split_3d)}은 더 보수적인 참고값입니다. "
                f"3일 분할ㆍ10% ADVㆍ시계열 하위 5% 기준은 {_krw_uk(cap10_split_3d_p05)}입니다."
            ),
        },
        {
            "metric": "Turnover and Costs",
            "value": (
                f"리밸런싱 평균 one-way {_pct(rebalance_turnover.mean())}, "
                f"매매비용 {_pctp(float(final['total_trading_cost_return']))}, "
                f"총보수ㆍ비용 {_pctp(float(final['total_fund_expense_return']))}"
            ),
            "raw_value": float(rebalance_turnover.mean()),
            "definition": "Turnover는 리밸런싱 때 목표비중으로 이동하기 위해 사고파는 비중 변화입니다. 비용은 매매비용과 펀드 총보수ㆍ비용을 분리해 반영했습니다.",
            "practical_interpretation": (
                f"평균 리밸런싱 one-way turnover는 {_pct(rebalance_turnover.mean())}이고, "
                "최대값은 약 30%로 turnover limit 근처입니다. "
                f"비용 반영 누적수익률은 비용 미반영 대비 {_pctp(cumulative_cost_drag)} 낮아집니다."
            ),
        },
        {
            "metric": "Sharpe Ratio",
            "value": f"{float(final['sharpe_ratio']):.3f}",
            "raw_value": float(final["sharpe_ratio"]),
            "definition": "성과표의 Sharpe는 CAGR을 연환산 변동성으로 나눈 값입니다.",
            "practical_interpretation": (
                f"최종 전략은 누적수익률 {_pct(float(final['cumulative_return']))}, "
                f"연환산 변동성 {_pct(float(final['annualized_volatility']))} 기준 Sharpe {float(final['sharpe_ratio']):.2f}입니다. "
                "단, 표본이 짧으므로 PSR/DSR과 함께 봅니다."
            ),
        },
        {
            "metric": "Probabilistic Sharpe Ratio",
            "value": f"PSR(SR*>0) {_pct(float(psr0['psr']))}, PSR(SR*>1) {_pct(float(psr1['psr']))}, PSR(SR*>2) {_pct(float(psr2['psr']))}",
            "raw_value": float(psr0["psr"]),
            "definition": "관측된 표본 Sharpe가 특정 기준 Sharpe를 초과할 확률을 왜도ㆍ첨도를 반영해 계산한 값입니다.",
            "practical_interpretation": (
                f"표본 연율 Sharpe {float(psr0['sample_sharpe_ann']):.2f} 기준, "
                f"장기 Sharpe가 1을 넘을 가능성은 {_pct(float(psr1['psr']))}로 추정됩니다. "
                "PSR은 미래 보장이 아니라 짧은 표본의 Sharpe 신뢰도 점검입니다."
            ),
        },
        {
            "metric": "Deflated Sharpe Ratio",
            "value": f"{_pct(dsr['deflated_sharpe_ratio'])} (trial count {trial_count})",
            "raw_value": dsr["deflated_sharpe_ratio"],
            "definition": "여러 전략 후보를 테스트했을 때 우연히 높아진 Sharpe를 할인한 확률입니다.",
            "practical_interpretation": (
                f"현재 발표에 남긴 후보/민감도 조합 {trial_count}개를 고려해 기대 최대 Sharpe 기준을 "
                f"{dsr['expected_max_sharpe_ann']:.2f}로 높이면 DSR은 {_pct(dsr['deflated_sharpe_ratio'])}입니다. "
                "여러 후보 중 고른 효과를 반영해도 Sharpe가 완전히 우연이라고 보기는 어렵지만, "
                "trial count 정의에 따라 값이 달라지므로 scenario table과 함께 해석합니다."
            ),
        },
        {
            "metric": "Drawdown",
            "value": f"{_pct(float(final['max_drawdown']))} ({worst_dd['date'].date()})",
            "raw_value": float(final["max_drawdown"]),
            "definition": "누적 wealth가 이전 고점 대비 얼마나 하락했는지의 최대값입니다.",
            "practical_interpretation": (
                f"최대낙폭은 {_pct(float(final['max_drawdown']))}로, 수익률은 높지만 테마 ETF 특유의 하락위험은 큽니다. "
                "따라서 이 전략은 저위험 전략이 아니라 active overlay 전략으로 해석해야 합니다."
            ),
        },
        {
            "metric": "Tracking Error",
            "value": f"{_pct(float(final['tracking_error']))}",
            "raw_value": float(final["tracking_error"]),
            "definition": "전략 일별 수익률에서 PDF 벤치마크 일별 수익률을 뺀 active return의 표준편차를 연율화한 값입니다.",
            "practical_interpretation": (
                f"실현 TE는 {_pct(float(final['tracking_error']))}, IR은 {float(final['information_ratio']):.3f}, "
                f"PDF 상관계수는 {float(final['correlation']):.3f}입니다. "
                "TE는 패시브 복제 오차가 아니라 초과성과를 얻기 위해 사용한 active risk 예산입니다."
            ),
        },
        {
            "metric": "Herfindahl-Hirschman Index",
            "value": (
                f"latest HHI {float(hhi_latest['strategy_hhi']):.3f}, "
                f"effective holdings {float(hhi_latest['strategy_effective_holding_count']):.2f}"
            ),
            "raw_value": float(hhi_latest["strategy_hhi"]),
            "definition": "종목별 비중 제곱합입니다. 1/HHI는 실질적으로 몇 종목에 분산된 것처럼 보이는지 보여줍니다.",
            "practical_interpretation": (
                f"최신 전략 HHI는 {float(hhi_latest['strategy_hhi']):.3f}, PDF HHI는 {float(hhi_latest['pdf_hhi']):.3f}입니다. "
                f"전략의 최신 effective holdings는 {float(hhi_latest['strategy_effective_holding_count']):.2f}개로 PDF "
                f"{float(hhi_latest['pdf_effective_holding_count']):.2f}개보다 낮아, 초과성과와 함께 집중위험이 커졌습니다."
            ),
        },
    ]

    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(OUTPUT_DIR / "final_metrics_summary.csv", index=False, encoding="utf-8-sig")

    pretty = metrics[["metric", "value", "definition", "practical_interpretation"]].copy()
    pretty.to_csv(OUTPUT_DIR / "final_metrics_summary_pretty.csv", index=False, encoding="utf-8-sig")

    detail = pd.DataFrame(
        [
            {
                "average_daily_one_way_turnover": avg_daily_one_way_turnover,
                "average_rebalance_one_way_turnover": float(rebalance_turnover.mean()),
                "max_rebalance_one_way_turnover": float(rebalance_turnover.max()),
                "annualized_one_way_turnover": annualized_one_way_turnover,
                "average_holding_period_trading_days": average_holding_period_trading_days,
                "average_holding_period_calendar_days": average_holding_period_calendar_days,
                "total_two_way_traded_weight": float(turnover.sum() * 2.0),
                "cumulative_cost_not_reflected_return": cumulative_cost_not_reflected,
                "cumulative_cost_reflected_return": cumulative_cost_reflected,
                "cumulative_cost_drag_pct_point": cumulative_cost_drag,
                "sample_sharpe_ann_for_psr": float(psr0["sample_sharpe_ann"]),
                "deflated_sharpe_ratio": dsr["deflated_sharpe_ratio"],
                "dsr_expected_max_sharpe_ann": dsr["expected_max_sharpe_ann"],
                "dsr_trial_count": trial_count,
                "dsr_main_scenario": dsr["scenario"],
                "average_strategy_hhi": float(hhi_avg["strategy_hhi"]),
                "average_strategy_effective_holdings": float(hhi_avg["strategy_effective_holding_count"]),
                "average_pdf_hhi": float(hhi_avg["pdf_hhi"]),
                "average_pdf_effective_holdings": float(hhi_avg["pdf_effective_holding_count"]),
                "latest_strategy_hhi": float(hhi_latest["strategy_hhi"]),
                "latest_strategy_effective_holdings": float(hhi_latest["strategy_effective_holding_count"]),
                "latest_pdf_hhi": float(hhi_latest["pdf_hhi"]),
                "latest_pdf_effective_holdings": float(hhi_latest["pdf_effective_holding_count"]),
            }
        ]
    )
    detail.to_csv(OUTPUT_DIR / "final_metrics_detail.csv", index=False, encoding="utf-8-sig")
    return metrics, detail


def write_metrics_appendix(metrics: pd.DataFrame, detail: pd.DataFrame) -> None:
    d = detail.iloc[0]
    dsr_scenarios = pd.read_csv(OUTPUT_DIR / "deflated_sharpe_ratio_scenarios_pretty.csv")
    lines = [
        "## Appendix. 최종 전략 Metrics 산출",
        "",
        "아래 지표는 최종 전략 `consensus_active_mvo_te20_ra1_min1` 기준입니다. 수익률은 비용 반영 후 일별 수익률을 사용했고, benchmark는 KRX PDF 비중 복제 포트폴리오입니다.",
        "",
        "| 지표 | 최종값 | 의미 | 실무적 해석 |",
        "|---|---:|---|---|",
    ]
    for _, row in metrics.iterrows():
        lines.append(
            f"| {row['metric']} | {row['value']} | {row['definition']} | {row['practical_interpretation']} |"
        )
    lines.extend(
        [
            "",
            "### 지표별 핵심 해석",
            "",
            "- **Average Holding Periods**: turnover가 높을수록 평균 보유기간은 짧아집니다. 최종 전략은 주간 리밸런싱이므로 월간 전략보다 빠르게 컨센서스 변화를 반영하지만, 비용과 capacity를 반드시 같이 봐야 합니다.",
            "- **Maximum Strategy Capacity**: 성과가 좋아도 거래대금이 작은 종목을 크게 사고팔아야 하면 실제 운용규모는 제한됩니다. 본문 기준은 3일 분할 체결, 하루 10% ADV 참여율, 시계열 하위 10% capacity이고, 1일 체결 또는 5% ADV 기준은 더 보수적인 참고 시나리오입니다.",
            "- **Turnover and Costs**: turnover는 신호를 얼마나 자주 비중으로 옮기는지 보여주고, 비용은 그 대가입니다. 최종 성과는 매매비용과 펀드 총보수ㆍ비용을 반영한 값으로 설명해야 합니다.",
            "- **Sharpe / PSR / DSR**: Sharpe는 위험 대비 성과, PSR은 Sharpe의 표본 신뢰도, DSR은 여러 후보를 테스트한 효과를 감안한 보수적 Sharpe 검증입니다.",
            "- **Drawdown**: 최종 전략은 초과성과가 있지만 MDD가 작지 않습니다. 저위험 절대수익 전략이 아니라 테마 ETF 위에서 active risk를 쓰는 전략입니다.",
            "- **Tracking Error**: 여기서 TE는 공식 ETF 추적오차가 아니라 PDF benchmark 대비 active return의 변동성입니다. active 전략에서는 TE 자체보다 IR과 함께 해석합니다.",
            "- **HHI**: HHI가 높아질수록 특정 종목에 집중된 포트폴리오입니다. 최종 전략은 PDF보다 effective holdings가 낮아졌으므로 초과성과와 함께 집중위험도 커졌습니다.",
            "",
            "### Deflated Sharpe Ratio의 조합 수 기준",
            "",
            "DSR에서 가장 중요한 선택은 `trial count`, 즉 몇 개의 전략 후보를 비교했다고 볼 것인지입니다. 이 숫자는 정답이 하나로 정해져 있다기보다, 연구자가 실제로 어떤 후보군 안에서 최종 전략을 골랐는지 투명하게 정해야 합니다.",
            "",
            "이번 프로젝트에서는 다음 원칙을 사용했습니다.",
            "",
            "```text",
            "1. Resampling / Monte Carlo 경로는 trial로 세지 않는다.",
            "   이미 선택된 전략의 경로 안정성 검증이지, 새로운 전략 후보가 아니기 때문입니다.",
            "",
            "2. 개별 종목이나 개별 날짜의 IC 관측치도 trial로 세지 않는다.",
            "   이들은 전략 후보가 아니라 신호 검증 단위입니다.",
            "",
            "3. 실제로 최종 전략 선택에 영향을 줄 수 있었던 비중화 방식과 운용 파라미터 조합을 trial로 본다.",
            "   예: 단순 점수 틸트, 공격형 점수 틸트, MVO, TE budget, max weight, 비용, 리밸런싱, factor weight 설정.",
            "```",
            "",
            "본문 기준 DSR은 **reported_spec_rows_conservative**를 사용했습니다. 이는 MVO 적용 전 2개 후보와 현재 발표/README에 남긴 robustness 설정 13개를 모두 포함한 **15개 조합**입니다. 같은 최종 경로가 여러 sensitivity 항목에 중복 등장하더라도 모두 세기 때문에 다소 보수적인 기준입니다.",
            "",
            "여기서 중요한 구분은, resampling이나 Monte Carlo에서 만든 2,000개 가상 경로는 DSR의 trial count에 넣지 않는다는 점입니다. 그 경로들은 이미 선택한 최종 전략의 수익률을 흔들어 보는 안정성 검증이지, 새로 비교한 전략 후보가 아니기 때문입니다. DSR의 trial은 '최종 전략을 고르기 전에 실제로 비교할 수 있었던 전략 설계 조합'입니다.",
            "",
            "| scenario | trial count | DSR | 표본 Sharpe | 기대 최대 Sharpe | 기준 설명 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for _, row in dsr_scenarios.iterrows():
        lines.append(
            f"| {row['scenario']} | {int(row['trial_count'])} | {row['deflated_sharpe_ratio']} | "
            f"{row['sample_sharpe_ann_for_dsr']} | {row['expected_max_sharpe_ann']} | {row['basis']} |"
        )
    lines.extend(
        [
            "",
            "해석은 다음과 같습니다.",
            "",
            "- trial count를 3개 핵심 후보만으로 보면 DSR은 더 높게 나옵니다.",
            "- 중복 경로를 제거한 현재 후보군 기준은 10개입니다.",
            "- 본문에서는 더 보수적으로 15개를 사용했습니다.",
            "- 26개 stress count를 적용해도 DSR은 80%대 후반으로 유지됩니다.",
            "",
            "따라서 DSR은 'Sharpe가 여러 조합을 돌리다 우연히 높아진 것일 수 있다'는 비판을 완전히 없애는 도구는 아니지만, 현재 공개한 후보군 기준에서는 최종 Sharpe가 단순 우연이라고 보기 어렵다는 보조 근거로 사용할 수 있습니다.",
            "",
            "### 추가 산출 파일",
            "",
            "| 파일 | 내용 |",
            "|---|---|",
            "| `output/final_metrics_summary.csv` | 지표별 원자료 요약 |",
            "| `output/final_metrics_summary_pretty.csv` | 발표용 지표 설명 표 |",
            "| `output/final_metrics_detail.csv` | turnover, DSR, HHI 세부 수치 |",
            "| `output/deflated_sharpe_ratio_scenarios.csv` | DSR trial count 시나리오별 원자료 |",
            "| `output/deflated_sharpe_ratio_scenarios_pretty.csv` | DSR trial count 시나리오별 발표용 표 |",
            "| `output/chart_deflated_sharpe_ratio_scenarios.png` | trial count 기준별 DSR 민감도 그래프 |",
            "| `output/final_hhi_timeseries.csv` | 날짜별 전략/PDF HHI 및 effective holdings |",
            "| `output/chart_final_hhi_timeseries.png` | 전략/PDF HHI 변화 |",
            "| `output/chart_final_effective_holdings.png` | 전략/PDF effective holdings 변화 |",
            "",
            "### DSR 그래프 해석",
            "",
            "DSR 그래프는 `trial count`, 즉 몇 개의 전략 후보를 비교했다고 볼 것인지에 따라 Deflated Sharpe Ratio가 어떻게 달라지는지 보여줍니다. x축은 trial count 기준별 시나리오이고, y축은 DSR입니다. 와인색 막대는 본문에서 사용한 기준입니다.",
            "",
            "읽는 방법은 다음과 같습니다.",
            "",
            "- trial count가 커질수록 DSR은 낮아집니다. 여러 조합을 많이 시도할수록 우연히 높은 Sharpe가 나올 가능성이 커지기 때문입니다.",
            "- 핵심 후보 3개만 보면 DSR은 98.93%로 매우 높습니다.",
            "- 본문 기준인 15개 조합에서는 91.65%입니다.",
            "- 더 보수적인 26개 stress 기준에서도 87.27%입니다.",
            "- 50% 기준선보다 충분히 높기 때문에, 현재 공개한 후보군 안에서는 최종 Sharpe가 단순한 후보 선택 운으로만 나온 것이라고 보기는 어렵습니다.",
            "",
            "다만 이 그래프도 미래 성과를 보장하는 증거는 아닙니다. 정확한 발표 표현은 **'과최적화 가능성을 낮춰 보는 보조 진단'**입니다.",
            "",
            "![DSR trial count 민감도](output/chart_deflated_sharpe_ratio_scenarios.png)",
            "",
            "### HHI 그래프 해석",
            "",
            "HHI는 종목별 비중의 제곱합입니다.",
            "",
            "```text",
            "HHI = sum_i weight_i^2",
            "Effective holdings = 1 / HHI",
            "```",
            "",
            "즉 HHI가 높을수록 특정 종목에 비중이 몰려 있고, `1 / HHI`로 계산한 effective holdings는 실질적으로 몇 종목에 분산된 것처럼 보이는지를 나타냅니다.",
            "",
            "첫 번째 HHI 그래프에서는 최종 전략의 HHI가 PDF보다 대체로 높습니다. 이는 전략이 PDF를 그대로 복제한 것이 아니라, consensus score가 좋은 종목에 더 집중해서 초과성과를 만들었다는 뜻입니다.",
            "",
            f"최신 시점 기준으로 전략 HHI는 {float(d['latest_strategy_hhi']):.3f}, PDF HHI는 {float(d['latest_pdf_hhi']):.3f}입니다. 이를 effective holdings로 바꾸면 전략은 약 {float(d['latest_strategy_effective_holdings']):.2f}개, PDF는 약 {float(d['latest_pdf_effective_holdings']):.2f}개입니다.",
            "",
            "따라서 해석은 양면적입니다.",
            "",
            "- 긍정적 해석: 점수가 높은 종목에 집중했기 때문에 PDF 대비 초과성과가 커졌습니다.",
            "- 리스크 해석: 실질 분산 종목 수가 줄어들었기 때문에 특정 종목의 급락이나 신호 오류에 더 민감해졌습니다.",
            "",
            "발표에서는 **'초과성과는 공짜가 아니라, 더 높은 active concentration을 감수한 결과'**라고 설명하는 것이 안전합니다.",
            "",
            "![최종 전략 HHI](output/chart_final_hhi_timeseries.png)",
            "",
            "두 번째 effective holdings 그래프는 같은 내용을 더 직관적으로 보여줍니다. 선이 낮아질수록 포트폴리오가 소수 종목에 집중된다는 의미입니다. 최종 전략의 effective holdings가 PDF보다 낮게 유지되는 구간은, MVO가 컨센서스 점수가 높은 종목으로 비중을 몰아준 구간으로 해석하면 됩니다.",
            "",
            "![최종 전략 effective holdings](output/chart_final_effective_holdings.png)",
            "",
        ]
    )
    (OUTPUT_DIR / "final_metrics_appendix.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    metrics, detail = build_metrics()
    write_metrics_appendix(metrics, detail)
    print(metrics[["metric", "value"]].to_string(index=False))


if __name__ == "__main__":
    main()
