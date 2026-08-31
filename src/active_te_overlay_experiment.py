from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from performance import performance_summary
from project_paths import OUTPUT_DIR, ensure_output_dir


BASE_EXPERIMENTS = [
    "consensus_multiplier_balanced",
    "consensus_multiplier_return_focus",
    "revision_momentum_proxy_balanced",
    "revision_momentum_proxy_return_focus",
]

SELECTED_OVERLAY_EXPERIMENT = "consensus_multiplier_return_focus_te_overlay_12_20d_floor25"


def run_active_te_overlay_experiments() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    returns = pd.read_csv(OUTPUT_DIR / "advanced_experiment_returns.csv", parse_dates=["date"])
    rows = []
    return_rows = []
    targets = [0.06, 0.08, 0.10, 0.12]
    lookbacks = [10, 20, 40, 60]
    floors = [0.25, 0.50, 0.75]

    for base in BASE_EXPERIMENTS:
        g = returns[returns["experiment_name"].eq(base)].sort_values("date").copy()
        if g.empty:
            continue
        benchmark = pd.to_numeric(g["benchmark_pdf_return"], errors="coerce")
        active = pd.to_numeric(g["strategy_return"], errors="coerce") - benchmark

        for lookback in lookbacks:
            min_periods = max(5, lookback // 2)
            rolling_te = active.shift(1).rolling(lookback, min_periods=min_periods).std() * np.sqrt(252)
            for target in targets:
                for floor in floors:
                    scale = (target / rolling_te).clip(upper=1.0).fillna(1.0).clip(lower=floor)
                    managed_return = benchmark + scale * active
                    name = f"{base}_te_overlay_{int(target * 100):02d}_{lookback}d_floor{int(floor * 100)}"
                    out = pd.DataFrame(
                        {
                            "date": g["date"].values,
                            "experiment_name": name,
                            "base_experiment": base,
                            "strategy_return": managed_return.values,
                            "benchmark_pdf_return": benchmark.values,
                            "active_scale": scale.values,
                            "rolling_active_te": rolling_te.values,
                            "te_target": target,
                            "lookback_days": lookback,
                            "min_active_scale": floor,
                        }
                    )
                    ret_idx = out.set_index("date")
                    summary = performance_summary(
                        ret_idx["strategy_return"],
                        ret_idx["benchmark_pdf_return"],
                        name,
                    )
                    cumulative = float((1.0 + out["strategy_return"].fillna(0.0)).prod() - 1.0)
                    benchmark_cumulative = float((1.0 + out["benchmark_pdf_return"].fillna(0.0)).prod() - 1.0)
                    summary.update(
                        {
                            "experiment_name": name,
                            "base_experiment": base,
                            "te_target": target,
                            "lookback_days": lookback,
                            "min_active_scale": floor,
                            "cumulative_return": cumulative,
                            "benchmark_cumulative_return": benchmark_cumulative,
                            "excess_cumulative_return_pct_point": cumulative - benchmark_cumulative,
                            "average_active_scale": float(scale.mean()),
                            "min_active_scale_realized": float(scale.min()),
                        }
                    )
                    rows.append(summary)
                    return_rows.append(out)

    overlay_returns = pd.concat(return_rows, ignore_index=True) if return_rows else pd.DataFrame()
    overlay_summary = pd.DataFrame(rows)
    if not overlay_summary.empty:
        overlay_summary = overlay_summary.sort_values(
            ["sharpe_ratio", "information_ratio", "cumulative_return"],
            ascending=False,
        )
    overlay_returns.to_csv(OUTPUT_DIR / "active_te_overlay_experiment_returns.csv", index=False, encoding="utf-8-sig")
    overlay_summary.to_csv(OUTPUT_DIR / "active_te_overlay_experiment_summary.csv", index=False, encoding="utf-8-sig")
    selected_returns = overlay_returns[overlay_returns["experiment_name"].eq(SELECTED_OVERLAY_EXPERIMENT)].copy()
    selected_summary = overlay_summary[overlay_summary["experiment_name"].eq(SELECTED_OVERLAY_EXPERIMENT)].copy()
    selected_returns.to_csv(OUTPUT_DIR / "active_te_overlay_selected_returns.csv", index=False, encoding="utf-8-sig")
    selected_summary.to_csv(OUTPUT_DIR / "active_te_overlay_selected_summary.csv", index=False, encoding="utf-8-sig")
    if not overlay_returns.empty and not overlay_summary.empty:
        _plot_overlay_charts(overlay_returns, overlay_summary, selected_returns)
    return {"returns": overlay_returns, "summary": overlay_summary}


def _plot_overlay_charts(
    overlay_returns: pd.DataFrame,
    overlay_summary: pd.DataFrame,
    selected_returns: pd.DataFrame,
) -> None:
    top_names = overlay_summary.head(6)["experiment_name"].tolist()
    ret = overlay_returns[overlay_returns["experiment_name"].isin(top_names)].copy()
    ret["date"] = pd.to_datetime(ret["date"], errors="coerce")

    fig, ax = plt.subplots(figsize=(12, 5.5))
    for name, g in ret.groupby("experiment_name"):
        g = g.sort_values("date")
        strategy_cum = (1.0 + g["strategy_return"].fillna(0.0)).cumprod() - 1.0
        benchmark_cum = (1.0 + g["benchmark_pdf_return"].fillna(0.0)).cumprod() - 1.0
        ax.plot(g["date"], (strategy_cum - benchmark_cum) * 100.0, label=name, linewidth=1.8)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Active TE Overlay: Cumulative Return Difference vs PDF")
    ax.set_xlabel("Date")
    ax.set_ylabel("Strategy cumulative return - PDF cumulative return (%p)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_active_te_overlay_active_return.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    x = overlay_summary["tracking_error"] * 100.0
    y = overlay_summary["excess_cumulative_return_pct_point"] * 100.0
    c = overlay_summary["sharpe_ratio"]
    scatter = ax.scatter(x, y, c=c, s=70, cmap="viridis", alpha=0.85)
    selected = overlay_summary[overlay_summary["experiment_name"].eq(SELECTED_OVERLAY_EXPERIMENT)]
    if not selected.empty:
        row = selected.iloc[0]
        ax.scatter(
            [row["tracking_error"] * 100.0],
            [row["excess_cumulative_return_pct_point"] * 100.0],
            s=150,
            facecolors="none",
            edgecolors="red",
            linewidths=2,
            label="selected 20D TE overlay",
        )
        ax.legend(fontsize=8)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_xlabel("Tracking error vs PDF (% annualized)")
    ax.set_ylabel("Final cumulative return difference vs PDF (%p)")
    ax.set_title("Active TE Overlay Grid: Active Return vs TE")
    ax.grid(True, alpha=0.3)
    fig.colorbar(scatter, ax=ax, label="Sharpe ratio")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_active_te_overlay_return_vs_te.png", dpi=170)
    plt.close(fig)

    if not selected_returns.empty:
        g = selected_returns.sort_values("date").copy()
        fig, ax1 = plt.subplots(figsize=(12, 5.0))
        ax1.plot(g["date"], g["active_scale"], color="#1f77b4", linewidth=2, label="active scale")
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Active scale")
        ax1.set_ylim(0.0, 1.05)
        ax1.grid(True, alpha=0.3)
        ax2 = ax1.twinx()
        ax2.plot(
            g["date"],
            g["rolling_active_te"] * 100.0,
            color="#d62728",
            linewidth=1.5,
            alpha=0.85,
            label="rolling active TE",
        )
        ax2.axhline(float(g["te_target"].iloc[0]) * 100.0, color="#d62728", linestyle="--", linewidth=1.0)
        ax2.set_ylabel("Rolling active TE (% annualized)")
        fig.suptitle("Selected Active TE Overlay: Risk Budget Scaling")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="lower left")
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_active_te_overlay_scale.png", dpi=170)
        plt.close(fig)


if __name__ == "__main__":
    result = run_active_te_overlay_experiments()
    cols = [
        "experiment_name",
        "base_experiment",
        "cumulative_return",
        "excess_cumulative_return_pct_point",
        "sharpe_ratio",
        "tracking_error",
        "information_ratio",
        "correlation",
        "average_active_scale",
        "te_target",
        "lookback_days",
        "min_active_scale",
    ]
    print(result["summary"][cols].head(20).to_string(index=False))
