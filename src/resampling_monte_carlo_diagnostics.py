from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from performance import performance_summary


OUTPUT_DIR = Path("output")
FINAL_EXPERIMENT_NAME = "consensus_active_mvo_te20_ra1_min1"
TRADING_DAYS = 252
N_SIMULATIONS = 2000
BLOCK_LENGTH = 5
MONTE_CARLO_DF = 5
RANDOM_SEED = 20260517


def _set_korean_font() -> None:
    try:
        from matplotlib import font_manager, rcParams

        preferred = ["AppleGothic", "NanumGothic", "Malgun Gothic"]
        available = {f.name for f in font_manager.fontManager.ttflist}
        for name in preferred:
            if name in available:
                rcParams["font.family"] = name
                rcParams["axes.unicode_minus"] = False
                return
    except Exception:
        pass


def _read_final_returns() -> pd.DataFrame:
    path = OUTPUT_DIR / "consensus_score_strategy_returns.csv"
    returns = pd.read_csv(path, parse_dates=["date"])
    returns = returns[returns["experiment_name"].eq(FINAL_EXPERIMENT_NAME)].copy()
    returns = returns.sort_values("date")
    returns = returns[["date", "strategy_return", "benchmark_pdf_return"]].dropna()
    returns["active_return"] = returns["strategy_return"] - returns["benchmark_pdf_return"]
    return returns


def _metrics(
    strategy_return: np.ndarray,
    benchmark_return: np.ndarray,
    method: str,
    simulation_id: int,
) -> dict:
    strategy = pd.Series(strategy_return, dtype=float)
    benchmark = pd.Series(benchmark_return, dtype=float)
    perf = performance_summary(strategy, benchmark, name=method)
    active = strategy - benchmark
    perf.update(
        {
            "method": method,
            "simulation_id": simulation_id,
            "benchmark_cumulative_return": float((1.0 + benchmark).prod() - 1.0),
            "excess_cumulative_return_pct_point": float(
                ((1.0 + strategy).prod() - 1.0) - ((1.0 + benchmark).prod() - 1.0)
            ),
            "active_return_mean_annualized": float(active.mean() * TRADING_DAYS),
        }
    )
    return perf


def _sample_block_bootstrap(
    data: pd.DataFrame,
    rng: np.random.Generator,
    block_length: int = BLOCK_LENGTH,
) -> pd.DataFrame:
    n = len(data)
    max_start = max(n - block_length, 0)
    pieces = []
    while sum(len(p) for p in pieces) < n:
        start = int(rng.integers(0, max_start + 1))
        pieces.append(data.iloc[start : start + block_length])
    return pd.concat(pieces, ignore_index=True).iloc[:n].copy()


def _run_block_bootstrap(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(N_SIMULATIONS):
        sample = _sample_block_bootstrap(data, rng)
        rows.append(
            _metrics(
                sample["strategy_return"].to_numpy(),
                sample["benchmark_pdf_return"].to_numpy(),
                method="block_bootstrap_5d",
                simulation_id=i + 1,
            )
        )
    return pd.DataFrame(rows)


def _run_monte_carlo_student_t(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    x = data[["benchmark_pdf_return", "active_return"]].to_numpy(dtype=float)
    mu = x.mean(axis=0)
    cov = np.cov(x, rowvar=False)
    cov = cov + np.eye(cov.shape[0]) * 1e-10
    chol = np.linalg.cholesky(cov)
    n = len(data)

    rows = []
    scale = np.sqrt(MONTE_CARLO_DF / (MONTE_CARLO_DF - 2.0))
    for i in range(N_SIMULATIONS):
        z = rng.standard_t(df=MONTE_CARLO_DF, size=(n, 2)) / scale
        synthetic = mu + z @ chol.T
        benchmark = np.clip(synthetic[:, 0], -0.95, 2.0)
        active = synthetic[:, 1]
        strategy = np.clip(benchmark + active, -0.95, 2.0)
        rows.append(
            _metrics(
                strategy,
                benchmark,
                method="monte_carlo_student_t",
                simulation_id=i + 1,
            )
        )
    return pd.DataFrame(rows)


def _summarize(metrics: pd.DataFrame, historical: dict) -> pd.DataFrame:
    metric_cols = [
        "cumulative_return",
        "benchmark_cumulative_return",
        "excess_cumulative_return_pct_point",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "tracking_error",
        "information_ratio",
        "correlation",
        "active_return_mean_annualized",
    ]

    rows = []
    for method, g in metrics.groupby("method"):
        out = {
            "method": method,
            "simulations": int(len(g)),
            "prob_excess_gt_0": float((g["excess_cumulative_return_pct_point"] > 0).mean()),
            "prob_ir_gt_0": float((g["information_ratio"] > 0).mean()),
            "prob_ir_gt_historical": float(
                (g["information_ratio"] > historical["information_ratio"]).mean()
            ),
            "prob_te_below_20pct": float((g["tracking_error"] <= 0.20).mean()),
        }
        for col in metric_cols:
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            out[f"{col}_p05"] = float(s.quantile(0.05)) if not s.empty else np.nan
            out[f"{col}_median"] = float(s.median()) if not s.empty else np.nan
            out[f"{col}_mean"] = float(s.mean()) if not s.empty else np.nan
            out[f"{col}_p95"] = float(s.quantile(0.95)) if not s.empty else np.nan
        rows.append(out)

    hist = {
        "method": "historical_path",
        "simulations": 1,
        "prob_excess_gt_0": np.nan,
        "prob_ir_gt_0": np.nan,
        "prob_ir_gt_historical": np.nan,
        "prob_te_below_20pct": np.nan,
    }
    for col in metric_cols:
        hist[f"{col}_p05"] = historical.get(col, np.nan)
        hist[f"{col}_median"] = historical.get(col, np.nan)
        hist[f"{col}_mean"] = historical.get(col, np.nan)
        hist[f"{col}_p95"] = historical.get(col, np.nan)
    return pd.concat([pd.DataFrame([hist]), pd.DataFrame(rows)], ignore_index=True)


def _pretty(summary: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "method",
        "simulations",
        "excess_cumulative_return_pct_point_median",
        "excess_cumulative_return_pct_point_p05",
        "excess_cumulative_return_pct_point_p95",
        "tracking_error_median",
        "information_ratio_median",
        "prob_excess_gt_0",
        "prob_ir_gt_0",
        "prob_te_below_20pct",
    ]
    out = summary[keep].copy()
    percent_cols = [
        "excess_cumulative_return_pct_point_median",
        "excess_cumulative_return_pct_point_p05",
        "excess_cumulative_return_pct_point_p95",
        "tracking_error_median",
        "prob_excess_gt_0",
        "prob_ir_gt_0",
        "prob_te_below_20pct",
    ]
    for col in percent_cols:
        out[col] = out[col].map(lambda x: "-" if pd.isna(x) else f"{x * 100:.2f}%")
    out["information_ratio_median"] = out["information_ratio_median"].map(
        lambda x: "-" if pd.isna(x) else f"{x:.3f}"
    )
    out = out.rename(
        columns={
            "method": "검증 방식",
            "simulations": "경로 수",
            "excess_cumulative_return_pct_point_median": "초과 누적수익률 중앙값",
            "excess_cumulative_return_pct_point_p05": "초과 누적수익률 5%",
            "excess_cumulative_return_pct_point_p95": "초과 누적수익률 95%",
            "tracking_error_median": "TE 중앙값",
            "information_ratio_median": "IR 중앙값",
            "prob_excess_gt_0": "초과성과 양수 비율",
            "prob_ir_gt_0": "IR 양수 비율",
            "prob_te_below_20pct": "TE 20% 이하 비율",
        }
    )
    return out


def _plot_distributions(metrics: pd.DataFrame, historical: dict) -> None:
    _set_korean_font()

    fig, ax = plt.subplots(figsize=(10, 5.4))
    colors = {
        "block_bootstrap_5d": "#7f7f7f",
        "monte_carlo_student_t": "#8f1d2c",
    }
    labels = {
        "block_bootstrap_5d": "5일 block bootstrap",
        "monte_carlo_student_t": "Student-t Monte Carlo",
    }
    for method, g in metrics.groupby("method"):
        ax.hist(
            g["excess_cumulative_return_pct_point"] * 100.0,
            bins=45,
            alpha=0.48,
            color=colors.get(method, "#333333"),
            label=labels.get(method, method),
        )
    ax.axvline(
        historical["excess_cumulative_return_pct_point"] * 100.0,
        color="#111111",
        linewidth=2.0,
        linestyle="--",
        label="실제 historical path",
    )
    ax.axvline(0.0, color="#555555", linewidth=1.0)
    ax.set_title("Resampling / Monte Carlo: PDF 대비 초과 누적수익률 분포")
    ax.set_xlabel("PDF 대비 초과 누적수익률 (%p)")
    ax.set_ylabel("시뮬레이션 경로 수")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_resampling_mc_excess_return_distribution.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5.2))
    data = [
        metrics.loc[metrics["method"].eq("block_bootstrap_5d"), "information_ratio"].dropna(),
        metrics.loc[metrics["method"].eq("monte_carlo_student_t"), "information_ratio"].dropna(),
    ]
    ax.boxplot(data, tick_labels=["Block bootstrap", "Monte Carlo"], showfliers=False)
    ax.axhline(historical["information_ratio"], color="#8f1d2c", linestyle="--", linewidth=2.0, label="실제 IR")
    ax.axhline(0.0, color="#555555", linewidth=1.0)
    ax.set_title("Resampling / Monte Carlo: Information Ratio 분포")
    ax.set_ylabel("Information Ratio")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_resampling_mc_ir_distribution.png", dpi=170)
    plt.close(fig)


def _write_note(summary_pretty: pd.DataFrame, historical: dict) -> None:
    lines = [
        "## Appendix. Resampling / Monte Carlo 검증",
        "",
        "선택한 최종 전략이 특정 historical path 하나에만 우연히 맞은 것인지 확인하기 위해 두 가지 추가 검증을 수행했습니다. 핵심 질문은 다음입니다.",
        "",
        "```text",
        "실제 2024-07~2026-05의 날짜 순서가 조금 달랐거나,",
        "비슷한 통계적 성격을 가진 다른 시장 경로가 나타났어도",
        "전략이 PDF 벤치마크 대비 초과성과를 낼 가능성이 있었는가?",
        "```",
        "",
        "이 검증은 전략을 새로 고르거나 파라미터를 다시 맞추는 과정이 아닙니다. 이미 확정한 최종 전략의 비용 반영 일별 수익률과 PDF 벤치마크 일별 수익률을 가지고, 경로만 여러 방식으로 다시 만들어 보는 appendix용 안정성 점검입니다.",
        "",
        "### ResamplingㆍMonte Carlo와 DSR은 무엇이 다른가",
        "",
        "세 검증은 이름이 모두 통계적으로 들리지만, 보는 질문이 다릅니다.",
        "",
        "| 구분 | 무엇을 새로 만드나 | 바뀌는 대상 | 답하려는 질문 | 새 전략 후보를 고르나 |",
        "|---|---|---|---|---|",
        "| Block bootstrap resampling | 실제 과거 수익률 block을 다시 배열한 경로 | 날짜 순서 | 과거 수익률 조각의 순서가 달라도 성과가 유지되는가 | 아니오 |",
        "| Monte Carlo synthetic path | 평균ㆍ공분산이 비슷한 가상 수익률 경로 | 수익률 충격 자체 | 비슷하지만 실제와 다른 시장 경로에서도 성과가 유지되는가 | 아니오 |",
        "| DSR | 새로운 경로를 만들지 않음 | 비교한 전략 후보 수, 즉 trial count | 여러 후보를 돌리다 우연히 Sharpe가 높아진 것 아닌가 | 아니오, 이미 고른 전략을 보정 평가 |",
        "",
        "즉 resampling과 Monte Carlo는 **최종 전략의 수익률 경로를 흔들어 보는 테스트**이고, DSR은 **최종 전략을 고르기 전 여러 후보를 봤다는 선택 편향을 Sharpe에서 할인하는 테스트**입니다.",
        "",
        "간단한 비유로 보면 다음과 같습니다.",
        "",
        "```text",
        "Resampling / Monte Carlo:",
        "  이미 고른 자동차를 여러 도로 조건에서 다시 달려 보게 하는 테스트",
        "",
        "DSR:",
        "  여러 자동차를 시험 주행한 뒤 가장 빨랐던 한 대를 골랐으니,",
        "  그 기록이 운 좋게 나온 최고 기록일 가능성을 할인하는 테스트",
        "```",
        "",
        "### 1. Block bootstrap resampling",
        "",
        "Block bootstrap은 실제 과거 수익률 조각을 잘라서 다시 섞는 방식입니다. 하루 단위로 섞으면 주간 단위의 추세, 반등, 급락 같은 짧은 흐름이 깨질 수 있으므로 여기서는 5거래일, 즉 약 1주일 단위 block을 사용했습니다.",
        "",
        "```text",
        "실제 경로: [1주차] [2주차] [3주차] [4주차] ...",
        "가상 경로: [3주차] [1주차] [1주차] [8주차] ...",
        "```",
        "",
        "복원추출이므로 같은 block이 여러 번 뽑힐 수도 있고, 어떤 block은 한 번도 뽑히지 않을 수도 있습니다. 중요한 점은 전략 수익률과 PDF 수익률을 같은 날짜 쌍으로 묶어 함께 뽑는다는 것입니다. 그래야 시장이 크게 오르는 날에는 전략과 PDF가 같이 움직였던 관계가 깨지지 않습니다.",
        "",
        "예를 들어 실제 데이터에 다음처럼 5일짜리 block이 있다고 하겠습니다.",
        "",
        "| block | 포함 내용 |",
        "|---|---|",
        "| A | 1주차의 PDF 수익률 5개와 전략 수익률 5개 |",
        "| B | 2주차의 PDF 수익률 5개와 전략 수익률 5개 |",
        "| C | 3주차의 PDF 수익률 5개와 전략 수익률 5개 |",
        "| D | 4주차의 PDF 수익률 5개와 전략 수익률 5개 |",
        "",
        "bootstrap 경로는 `C -> A -> A -> D`처럼 만들 수 있습니다. 여기서 A가 두 번 나오는 것은 복원추출이기 때문입니다. 이때 PDF만 따로 뽑고 전략만 따로 뽑지 않습니다. 날짜별 `PDF return, strategy return` 쌍을 같이 움직여야 두 수익률의 상관관계와 active return 구조가 유지됩니다.",
        "",
        f"- block 길이: {BLOCK_LENGTH}거래일",
        f"- 시뮬레이션 경로 수: {N_SIMULATIONS:,}개",
        "- 장점: 실제 관측된 수익률 조각만 사용하므로 가정이 적습니다.",
        "- 한계: 과거에 없었던 완전히 새로운 위기나 국면은 만들지 못합니다.",
        "",
        "### 2. Monte Carlo synthetic path",
        "",
        "Monte Carlo는 실제 날짜 조각을 그대로 쓰는 대신, 수익률의 통계적 특성을 추정한 뒤 새로운 가상 경로를 생성하는 방식입니다. 여기서는 전략 수익률을 직접 생성하지 않고, PDF 벤치마크 수익률과 active return을 나누어 봅니다.",
        "",
        "```text",
        "active return = 최종 전략 수익률 - PDF 벤치마크 수익률",
        "최종 전략 수익률 = PDF 벤치마크 수익률 + active return",
        "```",
        "",
        "이렇게 나눈 이유는 전략의 성과가 두 부분으로 구성되기 때문입니다. 하나는 ETF 테마 자체가 오르내리는 PDF 벤치마크 수익률이고, 다른 하나는 비중조정으로 PDF보다 더 벌거나 덜 번 active return입니다.",
        "",
        "Monte Carlo에서는 PDF return과 active return의 평균, 변동성, 두 값의 공분산을 추정합니다. 이후 금융 수익률의 꼬리가 두꺼운 특성을 반영하기 위해 정규분포가 아니라 Student-t shock을 사용해 2,000개의 가상 경로를 만듭니다.",
        "",
        "예를 들어 과거 데이터에서 다음 관계를 추정했다고 생각하면 됩니다.",
        "",
        "```text",
        "PDF return의 평균과 변동성",
        "active return의 평균과 변동성",
        "PDF return과 active return이 같이 움직이는 정도, 즉 공분산",
        "```",
        "",
        "그다음 매일 새로운 충격을 뽑아 `가상의 PDF return`과 `가상의 active return`을 만듭니다. 마지막에 둘을 더해서 가상의 전략 수익률을 만듭니다.",
        "",
        "```text",
        "synthetic strategy return",
        "= synthetic PDF return + synthetic active return",
        "```",
        "",
        "따라서 Monte Carlo 경로는 과거 날짜 조각을 그대로 재배열한 것이 아니라, 과거와 평균ㆍ변동성ㆍ상관 구조가 비슷한 새 가상 경로입니다.",
        "",
        f"- Student-t 자유도: {MONTE_CARLO_DF}",
        f"- 시뮬레이션 경로 수: {N_SIMULATIONS:,}개",
        "- 장점: block bootstrap보다 다양한 경로를 만들 수 있습니다.",
        "- 한계: 평균ㆍ공분산ㆍ분포 가정이 들어가므로 결과가 모형 가정에 의존합니다.",
        "",
        "### 두 경로 검증의 차이",
        "",
        "| 방식 | 무엇을 다시 만드나 | 장점 | 한계 |",
        "|---|---|---|---|",
        "| Block bootstrap | 실제 5거래일 수익률 block의 순서 | 가정이 적고 실제 관측값 기반 | 과거에 없던 새 국면은 만들기 어려움 |",
        "| Monte Carlo | 평균ㆍ공분산이 비슷한 가상 수익률 경로 | 더 다양한 경로 생성 가능 | 분포와 공분산 가정에 의존 |",
        "",
        "반대로 DSR은 위 표의 두 방식처럼 2,000개의 수익률 경로를 새로 만드는 검증이 아닙니다. 예를 들어 발표 과정에서 `단순 점수 틸트`, `공격형 점수 틸트`, `MVO`, `TE budget 변경`, `max weight 변경` 등 총 15개 후보를 봤다면, 그중 가장 Sharpe가 높은 후보가 우연히 좋아 보였을 가능성이 있습니다. DSR은 이 15개 후보를 봤다는 사실을 반영해서 비교 기준 Sharpe를 더 높게 잡고, 최종 전략의 Sharpe가 그 기준을 넘을 가능성을 계산합니다.",
        "",
        "그래서 발표에서는 다음처럼 구분하는 것이 가장 안전합니다.",
        "",
        "```text",
        "Resampling / Monte Carlo = 경로 안정성 검증",
        "DSR = 후보 선택 편향과 과최적화 가능성 보정",
        "```",
        "",
        "### 설정",
        "",
        "| 항목 | 설정 |",
        "|---|---|",
        "| 학습/관측 데이터 | 최종 전략 비용 반영 일별 수익률, PDF 벤치마크 일별 수익률 |",
        "| 기간 | 2024-07-10 ~ 2026-05-06 |",
        f"| Block length | {BLOCK_LENGTH}거래일 |",
        f"| Monte Carlo paths | {N_SIMULATIONS:,}개 |",
        "| Benchmark | KRX PDF 비중 복제 포트폴리오 |",
        "| 거래비용 | 최종 전략 수익률에 이미 반영 |",
        "",
        "### 결과 요약",
        "",
        summary_pretty.to_markdown(index=False),
        "",
        "해석은 방어적으로 해야 합니다. 이 검증은 미래 성과를 보장하는 테스트가 아니라, 최종 전략의 초과성과가 특정 날짜 순서 하나에만 완전히 의존하는지 확인하는 보조 진단입니다.",
        "",
        f"실제 historical path의 PDF 대비 초과 누적수익률은 {historical['excess_cumulative_return_pct_point'] * 100:.2f}%p, IR은 {historical['information_ratio']:.3f}, TE는 {historical['tracking_error'] * 100:.2f}%입니다.",
        "",
        "결과를 읽는 방법은 다음과 같습니다.",
        "",
        "- 초과성과 양수 비율이 86~88%라는 것은, 2,000개 대체 경로 중 대략 86~88%에서 최종 전략이 PDF보다 누적수익률이 높았다는 뜻입니다.",
        "- TE 20% 이하 비율이 96% 이상이라는 것은, 가상 경로 대부분에서 사전에 둔 active risk 예산 20% 근처 또는 이하로 위험이 유지되었다는 뜻입니다.",
        "- 하지만 초과 누적수익률 5% 분위가 음수라는 것은, 불리한 경로에서는 전략이 PDF보다 못할 수 있다는 뜻입니다.",
        "",
        "따라서 이 표는 '미래에도 반드시 이긴다'는 증명이 아니라, '현재 선택한 전략이 하나의 운 좋은 날짜 순서에만 의존한 결과는 아닐 가능성이 있다'는 보조 근거로 해석해야 합니다.",
        "",
        "![Resampling/Monte Carlo 초과성과 분포](chart_resampling_mc_excess_return_distribution.png)",
        "",
        "![Resampling/Monte Carlo IR 분포](chart_resampling_mc_ir_distribution.png)",
    ]
    (OUTPUT_DIR / "resampling_monte_carlo_appendix.md").write_text("\n".join(lines), encoding="utf-8")


def run_resampling_monte_carlo_diagnostics() -> dict[str, pd.DataFrame]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_final_returns()
    historical = _metrics(
        data["strategy_return"].to_numpy(),
        data["benchmark_pdf_return"].to_numpy(),
        method="historical_path",
        simulation_id=0,
    )

    rng = np.random.default_rng(RANDOM_SEED)
    block = _run_block_bootstrap(data, rng)
    mc = _run_monte_carlo_student_t(data, rng)
    metrics = pd.concat([block, mc], ignore_index=True)

    summary = _summarize(metrics, historical)
    summary_pretty = _pretty(summary)

    metrics.to_csv(OUTPUT_DIR / "resampling_monte_carlo_path_metrics.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / "resampling_monte_carlo_summary.csv", index=False, encoding="utf-8-sig")
    summary_pretty.to_csv(
        OUTPUT_DIR / "resampling_monte_carlo_summary_pretty.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _plot_distributions(metrics, historical)
    _write_note(summary_pretty, historical)
    return {
        "path_metrics": metrics,
        "summary": summary,
        "summary_pretty": summary_pretty,
    }


if __name__ == "__main__":
    result = run_resampling_monte_carlo_diagnostics()
    for name, df in result.items():
        print(f"{name}: {df.shape}")
    print(result["summary_pretty"].to_string(index=False))
