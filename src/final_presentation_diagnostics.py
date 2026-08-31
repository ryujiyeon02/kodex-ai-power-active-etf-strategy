from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm

from project_paths import OUTPUT_DIR, ensure_output_dir


plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False


PARTICIPATION_RATES = [0.01, 0.03, 0.05, 0.10, 0.20]


def _fmt_code(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)


def _read_strategy_outputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    returns = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_returns.csv", parse_dates=["date"])
    weights = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_weights.csv", parse_dates=["date"])
    signals = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_signal_diagnostics.csv", parse_dates=["date"])
    turnover = pd.read_csv(OUTPUT_DIR / "consensus_score_strategy_turnover_diagnostics.csv", parse_dates=["date"])
    for df in [weights, signals]:
        if "stock_code" in df.columns:
            df["stock_code"] = _fmt_code(df["stock_code"])
    return returns, weights, signals, turnover


def _read_pdf_weights() -> pd.DataFrame:
    pdf = pd.read_csv(OUTPUT_DIR / "benchmark_pdf_weights.csv", parse_dates=["date"])
    pdf["stock_code"] = _fmt_code(pdf["stock_code"])
    return pdf


def _read_supplement() -> pd.DataFrame:
    path = OUTPUT_DIR / "covariance_adv_supplemental_panel.csv"
    if not path.exists():
        return pd.DataFrame()
    supplement = pd.read_csv(path, parse_dates=["date"])
    supplement["stock_code"] = _fmt_code(supplement["stock_code"])
    return supplement


def _save_covariance_lookback_diagnostics(turnover: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "optimizer_cov_hist_start",
        "optimizer_cov_hist_end",
        "optimizer_cov_min_observations",
        "optimizer_cov_median_observations",
        "optimizer_cov_missing_asset_count",
        "optimizer_success",
        "optimizer_predicted_te",
    ]
    available = [c for c in columns if c in turnover.columns]
    diag = turnover[available].copy()
    diag = diag.rename(
        columns={
            "optimizer_cov_hist_start": "lookback_calendar_start",
            "optimizer_cov_hist_end": "lookback_calendar_end",
            "optimizer_cov_min_observations": "min_asset_obs",
            "optimizer_cov_median_observations": "median_asset_obs",
            "optimizer_cov_missing_asset_count": "assets_with_less_than_60_obs",
        }
    )
    if "min_asset_obs" in diag.columns:
        diag["all_assets_have_60_obs"] = pd.to_numeric(diag["min_asset_obs"], errors="coerce") >= 60
    diag.to_csv(OUTPUT_DIR / "mvo_covariance_lookback_availability.csv", index=False, encoding="utf-8-sig")
    return diag


def _save_capacity_diagnostics(signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    supplement = _read_supplement()
    if supplement.empty or "supplement_trading_value" not in supplement.columns:
        return pd.DataFrame(), pd.DataFrame()

    trading_value = supplement.pivot(index="date", columns="stock_code", values="supplement_trading_value").sort_index()
    trades = signals.copy()
    trades["trade_abs_weight"] = pd.to_numeric(trades["actual_trade_weight"], errors="coerce").abs()
    trades = trades[trades["trade_abs_weight"] > 1e-6].copy()

    binding_rows = []
    summary_rows = []
    for rate in PARTICIPATION_RATES:
        date_caps = []
        for date, g in trades.groupby("date"):
            cap_rows = []
            for _, row in g.iterrows():
                code = row["stock_code"]
                if code not in trading_value.columns:
                    continue
                adv20 = pd.to_numeric(trading_value.loc[trading_value.index < date, code], errors="coerce").dropna().tail(20).mean()
                if pd.isna(adv20) or adv20 <= 0 or row["trade_abs_weight"] <= 0:
                    continue
                capacity = float(rate * adv20 / row["trade_abs_weight"])
                cap_rows.append(
                    {
                        "date": date,
                        "participation_rate": rate,
                        "stock_code": code,
                        "stock_name": row.get("stock_name"),
                        "trade_weight": float(row["actual_trade_weight"]),
                        "trade_abs_weight": float(row["trade_abs_weight"]),
                        "adv20_krw": float(adv20),
                        "capacity_krw": capacity,
                    }
                )
            if not cap_rows:
                continue
            day = pd.DataFrame(cap_rows).sort_values("capacity_krw")
            binding_rows.append(day.iloc[0].to_dict())
            date_caps.append(float(day["capacity_krw"].min()))
        cap = pd.Series(date_caps, dtype=float).dropna()
        summary_rows.append(
            {
                "participation_rate": rate,
                "rebalance_count": int(len(cap)),
                "min_capacity_krw": float(cap.min()) if len(cap) else np.nan,
                "p05_capacity_krw": float(cap.quantile(0.05)) if len(cap) else np.nan,
                "p10_capacity_krw": float(cap.quantile(0.10)) if len(cap) else np.nan,
                "median_capacity_krw": float(cap.median()) if len(cap) else np.nan,
                "mean_capacity_krw": float(cap.mean()) if len(cap) else np.nan,
            }
        )

    summary = pd.DataFrame(summary_rows)
    binding = pd.DataFrame(binding_rows)
    summary.to_csv(OUTPUT_DIR / "strategy_capacity_summary.csv", index=False, encoding="utf-8-sig")
    binding.to_csv(OUTPUT_DIR / "strategy_capacity_binding_trades.csv", index=False, encoding="utf-8-sig")
    if not summary.empty:
        presentation_rows = []
        for rate, label in [(0.05, "5% ADV 참여율 (보수적 체결)"), (0.10, "10% ADV 참여율 (중간 체결)")]:
            rows = summary[summary["participation_rate"].eq(rate)]
            if rows.empty:
                continue
            row = rows.iloc[0]
            presentation_rows.append(
                {
                    "adv_participation_assumption": label,
                    "rebalance_count": int(row["rebalance_count"]),
                    "time_series_p05_capacity_krw": float(row["p05_capacity_krw"]),
                    "time_series_p10_capacity_krw": float(row["p10_capacity_krw"]),
                    "time_series_median_capacity_krw": float(row["median_capacity_krw"]),
                    "time_series_min_capacity_krw": float(row["min_capacity_krw"]),
                }
            )
        presentation = pd.DataFrame(presentation_rows)
        if not presentation.empty:
            presentation.to_csv(
                OUTPUT_DIR / "strategy_capacity_presentation_table.csv",
                index=False,
                encoding="utf-8-sig",
            )
            pretty = presentation.copy()
            for col in [
                "time_series_p05_capacity_krw",
                "time_series_p10_capacity_krw",
                "time_series_median_capacity_krw",
                "time_series_min_capacity_krw",
            ]:
                pretty[col] = pretty[col].map(lambda x: f"{x / 1e8:.2f}억 원" if pd.notna(x) else "")
            pretty.to_csv(
                OUTPUT_DIR / "strategy_capacity_presentation_table_pretty.csv",
                index=False,
                encoding="utf-8-sig",
            )

    if not summary.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        x = summary["participation_rate"] * 100.0
        ax.plot(x, summary["min_capacity_krw"] / 1e8, marker="o", label="시계열 최저")
        ax.plot(x, summary["p05_capacity_krw"] / 1e8, marker="o", label="시계열 하위 5%")
        ax.plot(x, summary["p10_capacity_krw"] / 1e8, marker="o", label="시계열 하위 10%")
        ax.plot(x, summary["median_capacity_krw"] / 1e8, marker="o", label="시계열 중앙값")
        ax.set_title("ADV 참여율별 전략 capacity")
        ax.set_xlabel("허용 ADV 참여율 (%)")
        ax.set_ylabel("운용 가능 규모 (억원)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_strategy_capacity_sensitivity.png", dpi=170)
        plt.close(fig)
    return summary, binding


def _probabilistic_sharpe_ratio(
    returns: pd.Series,
    threshold_ann: float,
    periods_per_year: int = 252,
) -> dict[str, float]:
    r = pd.to_numeric(returns, errors="coerce").dropna()
    n = len(r)
    if n < 5 or r.std(ddof=1) == 0:
        return {"psr": np.nan, "sample_sharpe_ann": np.nan, "observations": n}
    sr_daily = float(r.mean() / r.std(ddof=1))
    sr_threshold_daily = float(threshold_ann / np.sqrt(periods_per_year))
    sample_sharpe_ann = float(sr_daily * np.sqrt(periods_per_year))
    skew = float(r.skew())
    kurt = float(r.kurtosis() + 3.0)
    denom = 1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * sr_daily**2
    z_value = ((sr_daily - sr_threshold_daily) * np.sqrt(n - 1.0)) / np.sqrt(max(denom, 1e-12))
    return {
        "psr": float(norm.cdf(z_value)),
        "sample_sharpe_ann": sample_sharpe_ann,
        "observations": n,
        "skew": skew,
        "kurtosis": kurt,
        "z_value": float(z_value),
    }


def _save_psr(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = returns["strategy_return"]
    wine = "#9F2A32"
    wine_dark = "#6F1D24"
    thresholds = np.round(np.arange(-1.0, 5.05, 0.05), 2)
    rows = []
    for threshold in thresholds:
        row = _probabilistic_sharpe_ratio(r, float(threshold))
        row["threshold_sharpe_ann"] = float(threshold)
        rows.append(row)
    psr = pd.DataFrame(rows)
    psr.to_csv(OUTPUT_DIR / "probabilistic_sharpe_ratio.csv", index=False, encoding="utf-8-sig")

    key_thresholds = [0.0, 1.0, 2.0, 3.0, 4.0]
    key = psr[psr["threshold_sharpe_ann"].isin(key_thresholds)].copy()
    key.to_csv(OUTPUT_DIR / "probabilistic_sharpe_ratio_key_thresholds.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(psr["threshold_sharpe_ann"], psr["psr"] * 100.0, linewidth=2, color=wine)
    ax.set_title("Probabilistic Sharpe Ratio")
    ax.set_xlabel("기준 Sharpe Ratio")
    ax.set_ylabel("PSR (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_probabilistic_sharpe_ratio.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(key["threshold_sharpe_ann"].astype(str), key["psr"] * 100.0, color=wine)
    ax.set_title("주요 기준 Sharpe별 PSR")
    ax.set_xlabel("기준 Sharpe Ratio")
    ax.set_ylabel("PSR (%)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_probabilistic_sharpe_ratio_key_thresholds.png", dpi=170)
    plt.close(fig)

    if not psr.empty and psr["sample_sharpe_ann"].notna().any() and psr["z_value"].notna().any():
        sample_sharpe_ann = float(psr["sample_sharpe_ann"].dropna().iloc[0])
        # PSR can be written as Phi((SR_hat - SR*) / SE_SR). The bell curve below
        # is not an empirical histogram of many Sharpe ratios. It is the normal
        # approximation implied by the PSR standard error around the observed
        # sample Sharpe. Under this normal approximation, mean = median = mode.
        r_clean = pd.to_numeric(r, errors="coerce").dropna()
        sr_daily = float(r_clean.mean() / r_clean.std(ddof=1))
        skew = float(r_clean.skew())
        kurt = float(r_clean.kurtosis() + 3.0)
        denom = 1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * sr_daily**2
        observations = len(r_clean)
        sharpe_se_ann = float(np.sqrt(252.0) * np.sqrt(max(denom, 1e-12)) / np.sqrt(observations - 1.0))
        mode_sharpe_ann = sample_sharpe_ann

        if np.isfinite(sharpe_se_ann) and sharpe_se_ann > 0:
            psr_zero = float(
                psr.loc[psr["threshold_sharpe_ann"].eq(0.0), "psr"].iloc[0]
            )
            dist = pd.DataFrame(
                {
                    "sharpe_ann": np.linspace(sample_sharpe_ann - 4.0 * sharpe_se_ann, sample_sharpe_ann + 4.0 * sharpe_se_ann, 400)
                }
            )
            dist["density"] = norm.pdf(dist["sharpe_ann"], loc=sample_sharpe_ann, scale=sharpe_se_ann)
            dist["sample_sharpe_ann"] = sample_sharpe_ann
            dist["sharpe_se_ann"] = sharpe_se_ann
            dist["mode_sharpe_ann_normal_approx"] = mode_sharpe_ann
            dist.to_csv(OUTPUT_DIR / "probabilistic_sharpe_ratio_distribution.csv", index=False, encoding="utf-8-sig")

            fig, ax = plt.subplots(figsize=(9, 5))
            ax.plot(dist["sharpe_ann"], dist["density"], color=wine, linewidth=2.2)
            ax.fill_between(
                dist["sharpe_ann"],
                0,
                dist["density"],
                where=dist["sharpe_ann"] >= 0.0,
                color=wine,
                alpha=0.14,
                label=f"Sharpe > 0 영역 ({psr_zero:.2%})",
            )
            ax.text(
                0.04,
                0.82,
                f"P(Sharpe > 0) = {psr_zero:.2%}",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=10,
                color=wine_dark,
                bbox={
                    "boxstyle": "round,pad=0.35",
                    "facecolor": "white",
                    "edgecolor": wine,
                    "alpha": 0.86,
                },
            )
            ax.axvline(
                mode_sharpe_ann,
                color=wine_dark,
                linestyle=":",
                linewidth=2.6,
                label=f"근사분포 최빈값 {mode_sharpe_ann:.2f}",
            )
            ax.axvline(
                sample_sharpe_ann,
                color=wine,
                linewidth=1.8,
                alpha=0.85,
                label=f"표본 Sharpe {sample_sharpe_ann:.2f}",
            )
            for threshold, color in [(0.0, "#2ca02c"), (1.0, "#9467bd"), (2.0, "#8c564b"), (3.0, "#7f7f7f")]:
                ax.axvline(threshold, color=color, linestyle="--", linewidth=1.2, alpha=0.85)
                ax.text(threshold, ax.get_ylim()[1] * 0.92, f"SR*={threshold:.0f}", rotation=90, va="top", ha="right", fontsize=8)
            ax.set_title("PSR 해석용 Sharpe 분포 근사")
            ax.set_xlabel("연환산 Sharpe Ratio")
            ax.set_ylabel("확률밀도")
            ax.grid(True, alpha=0.25)
            ax.legend(loc="upper left")
            fig.tight_layout()
            fig.savefig(OUTPUT_DIR / "chart_probabilistic_sharpe_ratio_distribution.png", dpi=170)
            plt.close(fig)
    return psr, key


def _save_weight_diagnostics(weights: pd.DataFrame, pdf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = weights.merge(
        pdf[["date", "stock_code", "weight"]].rename(columns={"weight": "pdf_weight"}),
        on=["date", "stock_code"],
        how="left",
    )
    merged["pdf_weight"] = pd.to_numeric(merged["pdf_weight"], errors="coerce").fillna(0.0)
    merged["active_weight"] = pd.to_numeric(merged["weight"], errors="coerce").fillna(0.0) - merged["pdf_weight"]
    merged.to_csv(OUTPUT_DIR / "final_strategy_vs_pdf_weights_long.csv", index=False, encoding="utf-8-sig")

    latest_date = merged["date"].max()
    latest = merged[merged["date"].eq(latest_date)].copy()
    latest = latest.sort_values("weight", ascending=False)
    latest.to_csv(OUTPUT_DIR / "final_latest_weight_comparison.csv", index=False, encoding="utf-8-sig")

    summary = (
        merged.groupby(["stock_code", "stock_name"], dropna=False)["active_weight"]
        .agg(["mean", "min", "max"])
        .reset_index()
        .rename(columns={"mean": "average_active_weight", "min": "min_active_weight", "max": "max_active_weight"})
    )
    summary["average_abs_active_weight"] = merged.groupby(["stock_code", "stock_name"], dropna=False)[
        "active_weight"
    ].apply(lambda x: x.abs().mean()).values
    summary.to_csv(OUTPUT_DIR / "final_strategy_vs_pdf_active_weight_summary.csv", index=False, encoding="utf-8-sig")

    pivot_w = merged.pivot(index="date", columns="stock_name", values="weight").fillna(0.0)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.stackplot(pivot_w.index, [pivot_w[c] * 100.0 for c in pivot_w.columns], labels=pivot_w.columns)
    ax.set_title("최종 전략 종목 비중 변화")
    ax.set_xlabel("날짜")
    ax.set_ylabel("비중 (%)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_strategy_weight_stack.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(latest))
    ax.bar(x - 0.2, latest["pdf_weight"] * 100.0, width=0.4, label="PDF")
    ax.bar(x + 0.2, latest["weight"] * 100.0, width=0.4, label="최종 전략")
    ax.set_xticks(x)
    ax.set_xticklabels(latest["stock_name"], rotation=45, ha="right")
    ax.set_title(f"최근일 PDF 비중과 최종 전략 비중 비교 ({latest_date:%Y-%m-%d})")
    ax.set_ylabel("비중 (%)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_latest_weight_comparison.png", dpi=170)
    plt.close(fig)

    inclusion = pdf[pdf["weight"] > 0].copy()
    inclusion = inclusion[~inclusion["stock_name"].astype(str).str.contains("현금", na=False)]
    first_inclusion = (
        inclusion.sort_values(["date", "weight"], ascending=[True, False])
        .groupby("stock_name", as_index=False)
        .agg(first_pdf_inclusion_date=("date", "min"), first_pdf_weight=("weight", "first"))
    )
    ordered_names = (
        first_inclusion.sort_values(
            ["first_pdf_inclusion_date", "first_pdf_weight", "stock_name"],
            ascending=[True, False, True],
        )["stock_name"]
        .tolist()
    )
    missing_names = [n for n in merged["stock_name"].dropna().unique() if n not in ordered_names]
    ordered_names.extend(sorted(missing_names))
    first_inclusion.to_csv(OUTPUT_DIR / "final_pdf_inclusion_order_for_heatmap.csv", index=False, encoding="utf-8-sig")

    def _plot_active_heatmap(
        frame: pd.DataFrame,
        path: str,
        title: str,
        *,
        vlim: float = 50.0,
        max_xticks: int = 9,
        figsize: tuple[float, float] = (12.5, 6.2),
    ) -> None:
        heat = (
            frame.pivot_table(index="stock_name", columns="date", values="active_weight", aggfunc="last")
            .reindex(ordered_names)
            .fillna(0.0)
            * 100.0
        )
        heat = heat.loc[heat.abs().sum(axis=1) > 1e-8]
        fig, ax = plt.subplots(figsize=figsize)
        im = ax.imshow(heat.values, aspect="auto", cmap="RdBu_r", vmin=-vlim, vmax=vlim)
        ax.set_yticks(range(len(heat.index)))
        ax.set_yticklabels(heat.index)
        sample = np.linspace(0, len(heat.columns) - 1, min(max_xticks, len(heat.columns))).astype(int)
        ax.set_xticks(sample)
        ax.set_xticklabels([pd.Timestamp(heat.columns[i]).strftime("%Y-%m") for i in sample], rotation=45, ha="right")
        ax.set_title(title)
        ax.set_xlabel("날짜")
        ax.set_ylabel("종목")
        fig.colorbar(im, ax=ax, label="PDF 대비 비중 차이(%p)")
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / path, dpi=170)
        plt.close(fig)

    _plot_active_heatmap(
        merged,
        "chart_final_vs_pdf_weight_diff_heatmap.png",
        "PDF 대비 비중 차이: 편입일 기준 정렬",
        vlim=50.0,
        max_xticks=8,
        figsize=(12.5, 6.2),
    )
    _plot_active_heatmap(
        merged,
        "chart_final_active_weight_heatmap.png",
        "PDF 대비 비중 차이: 편입일 기준 정렬",
        vlim=50.0,
        max_xticks=8,
        figsize=(12.5, 6.2),
    )
    _plot_active_heatmap(
        merged,
        "chart_final_active_weight_heatmap_ordered_by_inclusion.png",
        "PDF 대비 비중 차이: 편입일 기준 정렬",
        vlim=50.0,
        max_xticks=8,
        figsize=(12.5, 6.2),
    )

    rebalance_dates = turnover_dates = pd.Series(dtype="datetime64[ns]")
    turnover_path = OUTPUT_DIR / "consensus_score_strategy_turnover_diagnostics.csv"
    if turnover_path.exists():
        turnover_diag = pd.read_csv(turnover_path, parse_dates=["date"])
        turnover_dates = turnover_diag["date"].dropna().drop_duplicates().sort_values()
    if not turnover_dates.empty:
        rebalance_frame = merged[merged["date"].isin(turnover_dates)].copy()
        _plot_active_heatmap(
            rebalance_frame,
            "chart_final_active_weight_heatmap_rebalance_ordered.png",
            "PDF 대비 비중 차이: 주간 리밸런싱일",
            vlim=50.0,
            max_xticks=10,
            figsize=(12.5, 6.2),
        )

        latest_date_for_recent = rebalance_frame["date"].max()
        recent_start = latest_date_for_recent - pd.DateOffset(months=9)
        recent_frame = rebalance_frame[rebalance_frame["date"] >= recent_start].copy()
        _plot_active_heatmap(
            recent_frame,
            "chart_final_active_weight_heatmap_recent_rebalance_ordered.png",
            "PDF 대비 비중 차이: 최근 리밸런싱 구간",
            vlim=50.0,
            max_xticks=8,
            figsize=(10.5, 6.2),
        )

    top_names = summary.reindex(summary["average_abs_active_weight"].sort_values(ascending=False).index).head(5)[
        "stock_name"
    ]
    fig, ax = plt.subplots(figsize=(12, 5.2))
    for name in top_names:
        g = merged[merged["stock_name"].eq(name)].sort_values("date")
        ax.plot(g["date"], g["active_weight"] * 100.0, label=name, linewidth=1.8)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("주요 종목 active weight 변화")
    ax.set_xlabel("날짜")
    ax.set_ylabel("Active weight (%p)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_top_active_weight_lines.png", dpi=170)
    plt.close(fig)

    return merged, latest


def _save_missing_data_checklist(
    covariance_diag: pd.DataFrame,
    capacity_summary: pd.DataFrame,
) -> None:
    total = len(covariance_diag)
    full_60 = int(covariance_diag.get("all_assets_have_60_obs", pd.Series(dtype=bool)).sum()) if total else 0
    missing_any = total - full_60
    non_full = covariance_diag.loc[~covariance_diag.get("all_assets_have_60_obs", pd.Series(False, index=covariance_diag.index))]
    last_non_full = non_full["date"].max() if not non_full.empty else pd.NaT
    first_all_full_after_warmup = (
        covariance_diag.loc[covariance_diag["date"] > last_non_full, "date"].min()
        if pd.notna(last_non_full)
        else covariance_diag["date"].min()
        if total
        else pd.NaT
    )
    cap5 = capacity_summary[capacity_summary["participation_rate"].eq(0.05)] if not capacity_summary.empty else pd.DataFrame()
    cap10 = capacity_summary[capacity_summary["participation_rate"].eq(0.10)] if not capacity_summary.empty else pd.DataFrame()

    lines = [
        "# Final Missing Data Checklist",
        "",
        "## Covariance And ADV Supplement",
        "",
        "`input/공분산추정,ADV용.xlsx`를 추가해 ETF 상장 전 가격/거래대금 이력을 공분산과 ADV 진단에 반영했습니다.",
        "전략 신호와 실제 백테스트 수익률은 기존 `output/model_panel.csv`를 유지하고, MVO 공분산과 capacity 계산만 이 보강 파일을 사용합니다.",
        "",
        "| Item | Result |",
        "|---|---:|",
        f"| Total rebalance count | {total} |",
        f"| Rebalances where every asset has 60 return observations | {full_60} |",
        f"| Rebalances with at least one asset below 60 observations | {missing_any} |",
        f"| Last rebalance with any asset below 60 observations | {pd.Timestamp(last_non_full).date() if pd.notna(last_non_full) else 'N/A'} |",
        f"| First rebalance after which all assets have 60 observations | {pd.Timestamp(first_all_full_after_warmup).date() if pd.notna(first_all_full_after_warmup) else 'N/A'} |",
        "",
        "대부분 종목은 상장 전 60거래일 이력이 보강되었습니다. 다만 산일전기처럼 실제 상장/거래 이력이 뒤늦게 시작되는 종목은 상장 전 수익률을 만들 수 없으므로 개별 종목 관측치 부족은 남습니다.",
        "",
        "## Capacity Snapshot",
        "",
        "| 허용 ADV 참여율 가정 | 시계열 하위 5% | 시계열 하위 10% | 시계열 중앙값 |",
        "|---|---:|---:|---:|",
    ]
    if not cap5.empty:
        row = cap5.iloc[0]
        lines.append(
            f"| 5% ADV 참여율, 보수적 체결 | {row['p05_capacity_krw'] / 1e8:.1f}억원 | "
            f"{row['p10_capacity_krw'] / 1e8:.1f}억원 | {row['median_capacity_krw'] / 1e8:.1f}억원 |"
        )
    if not cap10.empty:
        row = cap10.iloc[0]
        lines.append(
            f"| 10% ADV 참여율, 중간 체결 | {row['p05_capacity_krw'] / 1e8:.1f}억원 | "
            f"{row['p10_capacity_krw'] / 1e8:.1f}억원 | {row['median_capacity_krw'] / 1e8:.1f}억원 |"
        )
    lines.extend(
        [
            "",
            "## Data Still Needed For A Stricter Version",
            "",
            "| Category | Needed Data | Why It Matters |",
            "|---|---|---|",
            "| Consensus timestamp | FnGuide item별 실제 업데이트 시각 | 컨센서스가 리밸런싱 시점에 실제로 관측 가능했는지 더 엄격히 검증 |",
            "| Execution data | 호가 스프레드, 체결강도, 장중 거래대금 | 고정 슬리피지보다 현실적인 거래비용/시장충격 모델링 |",
            "| Corporate action log | 거래정지, 분할, 합병, 배당락, PDF 현금대체 사유 | PDF와 가격 수익률의 일시적 불일치 보정 |",
            "| Quarterly consensus | FQ1/FQ2 EPS와 영업이익 컨센서스 | 삼성 리포트식 다음 분기 revision factor를 직접 구현 |",
        ]
    )
    (OUTPUT_DIR / "final_missing_data_checklist.md").write_text("\n".join(lines), encoding="utf-8")


def run_final_presentation_diagnostics() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    returns, weights, signals, turnover = _read_strategy_outputs()
    pdf = _read_pdf_weights()
    cov_diag = _save_covariance_lookback_diagnostics(turnover)
    capacity_summary, capacity_binding = _save_capacity_diagnostics(signals)
    psr, psr_key = _save_psr(returns)
    weights_long, latest = _save_weight_diagnostics(weights, pdf)
    _save_missing_data_checklist(cov_diag, capacity_summary)
    return {
        "covariance": cov_diag,
        "capacity_summary": capacity_summary,
        "capacity_binding": capacity_binding,
        "psr": psr,
        "psr_key": psr_key,
        "weights_long": weights_long,
        "latest_weight": latest,
    }


if __name__ == "__main__":
    out = run_final_presentation_diagnostics()
    for name, df in out.items():
        print(f"{name}: {df.shape}")
