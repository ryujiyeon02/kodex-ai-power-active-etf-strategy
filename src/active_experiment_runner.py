from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from cost_utils import ETF_OFFICIAL_COSTS, calc_rebalance_cost_from_weight_change, daily_expense_rate
from factor_utils import zscore_cross_section
from performance import drawdown_series, performance_summary
from project_paths import COV_ADV_SUPPLEMENT_FILE, MODEL_PANEL_FILE, OUTPUT_DIR, ensure_output_dir
from strategy_factor_diagnostics import build_exhaustive_candidate_source
from strategy_ic_selected import (
    _apply_turnover_limit,
    _benchmark_weights,
    _score_to_target,
    choose_rebalance_dates,
)

plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False


_COV_ADV_SUPPLEMENT_CACHE: pd.DataFrame | None = None


PARAMS = {
    "benchmark_weight_column": "etf_weight_pct",
    "rebalance_frequency": "weekly",
    "score_profile": "consensus_core_equal",
    "target_method": "multiplicative",
    "score_gamma": 0.8,
    "individual_active_limit": 0.035,
    "active_budget": 0.10,
    "individual_min_weight": 0.0,
    "individual_max_weight": 0.50,
    "one_way_turnover_limit": 0.15,
    "cost_scenario": "base",
    "annual_fund_expense_rate": ETF_OFFICIAL_COSTS["annual_total_fee_expense_rate"],
    "score_direction": 1.0,
    "active_te_budget_enabled": False,
    "active_te_target": 0.12,
    "active_te_lookback_days": 20,
    "active_te_min_observations": 10,
    "active_te_min_scale": 0.25,
    "optimizer_cov_lookback_days": 60,
    "optimizer_cov_shrinkage_to_diag": 0.30,
    "optimizer_te_target": 0.12,
    "optimizer_risk_aversion": 5.0,
    "optimizer_turnover_penalty": 0.05,
    "dynamic_slippage_enabled": False,
    "slippage_aum_krw": 10_000_000_000.0,
    "slippage_execution_days": 3,
    "market_impact_coefficient": 0.0050,
    "market_impact_exponent": 0.5,
    "market_impact_max_rate": 0.0050,
}

FINAL_EXPERIMENT_NAME = "consensus_active_mvo_te20_ra1_min1"
DYNAMIC_COST_EXPERIMENT_NAME = "consensus_active_mvo_te20_ra1_min1_dynamic_cost"
FINAL_TE_TARGET = 0.20


SCORE_PROFILES = {
    "consensus_core": [
        ("eps_revision_1m", 0.50, 1.0),
        ("target_upside", 0.30, 1.0),
        ("rating_point", 0.20, 1.0),
    ],
    "consensus_core_equal": [
        ("eps_revision_1m", 1.0 / 3.0, 1.0),
        ("target_upside", 1.0 / 3.0, 1.0),
        ("rating_point", 1.0 / 3.0, 1.0),
    ],
    "korea_research_core": [
        ("eps_revision_1m", 0.25, 1.0),
        ("eps_revision_3m", 0.10, 1.0),
        ("op_revision_3m", 0.10, 1.0),
        ("target_upside", 0.15, 1.0),
        ("rating_point", 0.10, 1.0),
        ("earnings_yield_per", 0.05, 1.0),
        ("book_to_price_pbr", 0.05, 1.0),
        ("sales_to_price_psr", 0.05, 1.0),
        ("op_margin_fy1", 0.05, 1.0),
        ("ni_margin_fy1", 0.05, 1.0),
        ("log_market_cap", 0.025, 1.0),
        ("log_trading_value", 0.025, 1.0),
        ("vol_20d_ann", 0.025, -1.0),
        ("drawdown_60d", 0.025, 1.0),
    ],
    "earnings_revision_momentum_proxy": [
        ("eps_revision_1m", 0.40, 1.0),
        ("eps_revision_3m", 0.20, 1.0),
        ("op_revision_3m", 0.15, 1.0),
        ("target_price_revision_21d", 0.10, 1.0),
        ("target_upside", 0.10, 1.0),
        ("rating_revision_balance", 0.05, 1.0),
    ],
    "consensus_core_risk_adjusted": [
        ("eps_revision_1m", 0.40, 1.0),
        ("target_upside", 0.25, 1.0),
        ("rating_point", 0.15, 1.0),
        ("drawdown_60d", 0.10, 1.0),
        ("vol_20d_ann", 0.10, -1.0),
    ],
    "revision_momentum_risk_adjusted": [
        ("eps_revision_1m", 0.35, 1.0),
        ("eps_revision_3m", 0.18, 1.0),
        ("op_revision_3m", 0.12, 1.0),
        ("target_price_revision_21d", 0.08, 1.0),
        ("target_upside", 0.10, 1.0),
        ("rating_revision_balance", 0.05, 1.0),
        ("drawdown_60d", 0.07, 1.0),
        ("vol_20d_ann", 0.05, -1.0),
    ],
    "value_profitability_lowrisk": [
        ("earnings_yield_per", 0.15, 1.0),
        ("book_to_price_pbr", 0.15, 1.0),
        ("sales_to_price_psr", 0.10, 1.0),
        ("op_margin_fy1", 0.15, 1.0),
        ("ni_margin_fy1", 0.10, 1.0),
        ("eps_yield_fy1", 0.10, 1.0),
        ("log_market_cap", 0.10, 1.0),
        ("log_trading_value", 0.05, 1.0),
        ("vol_20d_ann", 0.07, -1.0),
        ("drawdown_60d", 0.03, 1.0),
    ],
    "ic_supported_information_growth": [
        ("log_market_cap", 0.15, 1.0),
        ("rating_total_count", 0.10, 1.0),
        ("target_total_count", 0.10, 1.0),
        ("target_confidence", 0.10, 1.0),
        ("analyst_coverage", 0.10, 1.0),
        ("sales_next_year_e", 0.10, 1.0),
        ("sales_current_year_e", 0.05, 1.0),
        ("sales_spread_fy1_minus_fy0", 0.10, 1.0),
        ("op_spread_fy1_minus_fy0", 0.05, 1.0),
        ("eps_growth_fy2_vs_fy0", 0.07, 1.0),
        ("ni_growth_fy2_vs_fy0", 0.05, 1.0),
        ("earnings_yield_per", 0.03, 1.0),
    ],
}


EXPERIMENTS = {
    "consensus_multiplier_defensive": {
        "score_profile": "consensus_core",
        "target_method": "multiplicative",
        "score_gamma": 0.8,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.15,
    },
    "consensus_multiplier_balanced": {
        "score_profile": "consensus_core",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "consensus_multiplier_return_focus": {
        "score_profile": "consensus_core",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "consensus_return_focus_te_budget": {
        "score_profile": "consensus_core",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "active_te_budget_enabled": True,
        "active_te_target": 0.12,
        "active_te_lookback_days": 20,
        "active_te_min_observations": 10,
        "active_te_min_scale": 0.25,
    },
    "consensus_active_mvo_te08": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.08,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 5.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te10": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.10,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 5.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te12": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.12,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 5.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te14": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.14,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 5.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te14_ra1": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.14,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te16_ra1": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.16,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te20_ra1": {
        "score_profile": "consensus_core_equal",
        "target_method": "active_mvo_te",
        "individual_min_weight": 0.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": FINAL_TE_TARGET,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te20_ra1_min1": {
        "score_profile": "consensus_core_equal",
        "target_method": "active_mvo_te",
        "individual_min_weight": 0.01,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": FINAL_TE_TARGET,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
    },
    "consensus_active_mvo_te20_ra1_min1_dynamic_cost": {
        "score_profile": "consensus_core_equal",
        "target_method": "active_mvo_te",
        "individual_min_weight": 0.01,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": FINAL_TE_TARGET,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
        "dynamic_slippage_enabled": True,
        "slippage_aum_krw": 10_000_000_000.0,
        "slippage_execution_days": 3,
        "market_impact_coefficient": 0.0050,
        "market_impact_exponent": 0.5,
        "market_impact_max_rate": 0.0050,
    },
    "consensus_active_mvo_te14_ra025": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.14,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 0.25,
        "optimizer_turnover_penalty": 0.02,
    },
    "consensus_active_mvo_te16_ra025": {
        "score_profile": "consensus_core",
        "target_method": "active_mvo_te",
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": 0.16,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 0.25,
        "optimizer_turnover_penalty": 0.02,
    },
    "research_core_balanced": {
        "score_profile": "korea_research_core",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "research_core_return_focus": {
        "score_profile": "korea_research_core",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "revision_momentum_proxy_balanced": {
        "score_profile": "earnings_revision_momentum_proxy",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "revision_momentum_proxy_return_focus": {
        "score_profile": "earnings_revision_momentum_proxy",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "consensus_risk_adjusted_balanced": {
        "score_profile": "consensus_core_risk_adjusted",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "consensus_risk_adjusted_return_focus": {
        "score_profile": "consensus_core_risk_adjusted",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "revision_risk_adjusted_balanced": {
        "score_profile": "revision_momentum_risk_adjusted",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "revision_risk_adjusted_return_focus": {
        "score_profile": "revision_momentum_risk_adjusted",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "value_profitability_lowrisk_balanced": {
        "score_profile": "value_profitability_lowrisk",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "value_profitability_lowrisk_return_focus": {
        "score_profile": "value_profitability_lowrisk",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
    "ic_supported_information_growth_balanced": {
        "score_profile": "ic_supported_information_growth",
        "target_method": "multiplicative",
        "score_gamma": 1.0,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.20,
    },
    "ic_supported_information_growth_return_focus": {
        "score_profile": "ic_supported_information_growth",
        "target_method": "multiplicative",
        "score_gamma": 1.5,
        "individual_max_weight": 0.70,
        "one_way_turnover_limit": 0.30,
    },
}


PRESENTATION_EXPERIMENTS = [
    "consensus_multiplier_balanced",
    "consensus_multiplier_return_focus",
    FINAL_EXPERIMENT_NAME,
]

PRESENTATION_LABELS = {
    "consensus_multiplier_balanced": "단순 점수 틸트",
    "consensus_multiplier_return_focus": "공격형 점수 틸트",
    FINAL_EXPERIMENT_NAME: "최종 전략",
}


def _add_eps_revision_1m(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["eps_next_year_e"] = pd.to_numeric(panel.get("eps_next_year_e"), errors="coerce")
    panel = panel.sort_values(["stock_code", "date"])
    lag = panel.groupby("stock_code")["eps_next_year_e"].shift(21)
    denom = lag.abs().replace(0.0, np.nan)
    panel["eps_revision_1m"] = (panel["eps_next_year_e"] - lag) / denom
    return panel


def _load_panel() -> pd.DataFrame:
    panel = pd.read_csv(MODEL_PANEL_FILE, dtype={"stock_code": str}, low_memory=False)
    panel["stock_code"] = panel["stock_code"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])
    panel = _add_eps_revision_1m(panel)
    panel = build_exhaustive_candidate_source(panel)
    panel["stock_code"] = panel["stock_code"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    return panel.dropna(subset=["date", "stock_code"]).sort_values(["date", "stock_code"])


def load_covariance_adv_supplement() -> pd.DataFrame:
    """Load the DataGuide supplement used only for covariance and ADV diagnostics.

    The file is a DataGuide-style wide sheet with metadata rows. It contains two
    columns per stock: adjusted price and trading value. It intentionally does
    not replace the strategy panel, because factor signals and backtest returns
    should remain tied to the validated model panel.
    """

    global _COV_ADV_SUPPLEMENT_CACHE
    if _COV_ADV_SUPPLEMENT_CACHE is not None:
        return _COV_ADV_SUPPLEMENT_CACHE.copy()
    if not COV_ADV_SUPPLEMENT_FILE.exists():
        _COV_ADV_SUPPLEMENT_CACHE = pd.DataFrame()
        return pd.DataFrame()

    raw = pd.read_excel(COV_ADV_SUPPLEMENT_FILE, header=None)
    if raw.shape[0] <= 14 or raw.shape[1] <= 1:
        _COV_ADV_SUPPLEMENT_CACHE = pd.DataFrame()
        return pd.DataFrame()

    dates = pd.to_datetime(raw.iloc[14:, 0], errors="coerce")
    frames: dict[str, pd.DataFrame] = {}
    for col in range(1, raw.shape[1]):
        raw_code = raw.iloc[8, col]
        item_name = str(raw.iloc[12, col])
        if pd.isna(raw_code) or item_name == "nan":
            continue
        code = str(raw_code).strip().upper().replace("A", "").zfill(6)
        stock_name = raw.iloc[9, col] if pd.notna(raw.iloc[9, col]) else None
        if code not in frames:
            frames[code] = pd.DataFrame(
                {
                    "date": dates,
                    "stock_code": code,
                    "stock_name": stock_name,
                }
            )
        values = pd.to_numeric(raw.iloc[14:, col], errors="coerce").to_numpy()
        if "수정주가" in item_name:
            frames[code]["supplement_adj_close"] = values
        elif "거래대금" in item_name:
            frames[code]["supplement_trading_value"] = values

    if not frames:
        _COV_ADV_SUPPLEMENT_CACHE = pd.DataFrame()
        return pd.DataFrame()

    supplement = pd.concat(frames.values(), ignore_index=True)
    supplement = supplement.dropna(subset=["date", "stock_code"]).sort_values(["stock_code", "date"])
    supplement["stock_code"] = supplement["stock_code"].astype(str).str.zfill(6)
    supplement["supplement_return"] = supplement.groupby("stock_code")["supplement_adj_close"].pct_change(
        fill_method=None
    )
    supplement = supplement.sort_values(["date", "stock_code"]).reset_index(drop=True)
    supplement.to_csv(OUTPUT_DIR / "covariance_adv_supplemental_panel.csv", index=False, encoding="utf-8-sig")
    _COV_ADV_SUPPLEMENT_CACHE = supplement
    return supplement.copy()


def _build_covariance_return_matrix(strategy_return_mat: pd.DataFrame) -> pd.DataFrame:
    supplement = load_covariance_adv_supplement()
    if supplement.empty or "supplement_return" not in supplement.columns:
        return strategy_return_mat
    supplemental_returns = supplement.pivot(
        index="date",
        columns="stock_code",
        values="supplement_return",
    ).sort_index()
    supplemental_returns.columns = supplemental_returns.columns.astype(str).str.zfill(6)
    strategy_return_mat = strategy_return_mat.copy()
    strategy_return_mat.columns = strategy_return_mat.columns.astype(str).str.zfill(6)
    combined = strategy_return_mat.combine_first(supplemental_returns).sort_index()

    rows = []
    for code in sorted(combined.columns):
        strategy_obs = int(strategy_return_mat.get(code, pd.Series(dtype=float)).notna().sum())
        supplemental_obs = int(supplemental_returns.get(code, pd.Series(dtype=float)).notna().sum())
        combined_obs = int(combined[code].notna().sum())
        first = combined[code].dropna().index.min()
        last = combined[code].dropna().index.max()
        rows.append(
            {
                "stock_code": code,
                "strategy_return_observations": strategy_obs,
                "supplemental_return_observations": supplemental_obs,
                "combined_return_observations": combined_obs,
                "first_combined_return_date": first,
                "last_combined_return_date": last,
            }
        )
    pd.DataFrame(rows).to_csv(
        OUTPUT_DIR / "covariance_return_matrix_source_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return combined


def _build_trading_value_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Build daily trading-value matrix used for ADV-based cost diagnostics."""
    if "trading_value" in panel.columns:
        tv = panel.pivot(index="date", columns="stock_code", values="trading_value").sort_index()
        tv.columns = tv.columns.astype(str).str.zfill(6)
    else:
        tv = pd.DataFrame()

    supplement = load_covariance_adv_supplement()
    if not supplement.empty and "supplement_trading_value" in supplement.columns:
        sup_tv = supplement.pivot(
            index="date",
            columns="stock_code",
            values="supplement_trading_value",
        ).sort_index()
        sup_tv.columns = sup_tv.columns.astype(str).str.zfill(6)
        tv = tv.combine_first(sup_tv).sort_index() if not tv.empty else sup_tv
    return tv.sort_index()


def _adv20_map_for_date(trading_value_mat: pd.DataFrame, date: pd.Timestamp) -> dict[str, float]:
    if trading_value_mat.empty:
        return {}
    hist = trading_value_mat.loc[trading_value_mat.index < pd.Timestamp(date)].tail(20)
    if hist.empty:
        return {}
    adv = hist.apply(pd.to_numeric, errors="coerce").mean()
    return {str(code).zfill(6): float(value) for code, value in adv.dropna().items() if value > 0}


def _score_components(profile: str | None) -> list[tuple[str, float, float]]:
    profile_name = profile or "consensus_core"
    if profile_name not in SCORE_PROFILES:
        raise ValueError(f"Unknown score profile: {profile_name}")
    components = SCORE_PROFILES[profile_name]
    total = sum(float(weight) for _, weight, _ in components)
    if total <= 0:
        raise ValueError(f"Score profile has non-positive total weight: {profile_name}")
    return [(factor, float(weight) / total, float(direction)) for factor, weight, direction in components]


def _score_formula(components: list[tuple[str, float, float]]) -> str:
    parts = []
    for factor, weight, direction in components:
        sign = "" if direction >= 0 else "-"
        parts.append(f"{weight:.2f}*{sign}z({factor})")
    return " + ".join(parts)


def _build_consensus_score(
    g: pd.DataFrame,
    score_direction: float = 1.0,
    score_profile: str | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    g = g.set_index("stock_code").sort_index()
    raw = pd.DataFrame(index=g.index)
    z = pd.DataFrame(index=g.index)
    components = _score_components(score_profile)

    score = pd.Series(0.0, index=g.index)
    for col, weight, direction in components:
        raw[col] = pd.to_numeric(g[col], errors="coerce") if col in g.columns else np.nan
        z_col = zscore_cross_section(raw[col]) * direction
        z[f"z_{col}"] = z_col
        score = score + weight * z_col
    score = (score - score.mean()) * float(score_direction)

    diagnostics = pd.concat([raw, z], axis=1)
    diagnostics["consensus_score"] = score
    diagnostics["usable_signal_count"] = raw.notna().sum(axis=1).astype(int)
    diagnostics["signal_coverage_ratio"] = diagnostics["usable_signal_count"] / len(components)
    diagnostics["score_direction"] = float(score_direction)
    diagnostics["score_profile"] = score_profile or "consensus_core"
    diagnostics["score_formula"] = _score_formula(components)
    return diagnostics, score


def _compound_forward_returns(
    return_mat: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    codes: pd.Index,
) -> pd.Series:
    period = return_mat.loc[(return_mat.index > start_date) & (return_mat.index <= end_date), codes]
    if period.empty:
        return pd.Series(np.nan, index=codes)
    return (1.0 + period).prod(min_count=1) - 1.0


def _top_minus_bottom(factor: pd.Series, future_return: pd.Series) -> tuple[float, int, int]:
    data = pd.DataFrame({"factor": factor, "future_return": future_return}).dropna()
    if len(data) < 4:
        return np.nan, 0, 0
    data = data.sort_values("factor")
    group_n = max(2, len(data) // 3)
    bottom = data.head(group_n)
    top = data.tail(group_n)
    return float(top["future_return"].mean() - bottom["future_return"].mean()), int(len(top)), int(len(bottom))


def _normalize_with_cap(w: pd.Series, max_weight: float) -> pd.Series:
    x = pd.to_numeric(w, errors="coerce").fillna(0.0).clip(lower=0.0)
    if x.sum() <= 0:
        return x
    capped = pd.Series(False, index=x.index)
    out = x.copy()
    for _ in range(50):
        uncapped = ~capped
        remaining = 1.0 - float(out[capped].sum())
        if remaining <= 0 or not uncapped.any():
            break
        scaled = out[uncapped] / float(out[uncapped].sum()) * remaining
        breach = scaled > max_weight
        out.loc[uncapped] = scaled
        if not breach.any():
            break
        newly_capped = scaled[breach].index
        out.loc[newly_capped] = max_weight
        capped.loc[newly_capped] = True
    total = float(out.sum())
    return out / total if total > 0 else out


def _normalize_with_bounds(w: pd.Series, min_weight: float, max_weight: float) -> pd.Series:
    x = pd.to_numeric(w, errors="coerce").fillna(0.0)
    min_weight = max(float(min_weight), 0.0)
    max_weight = float(max_weight)
    n = len(x)
    if n == 0:
        return x
    if min_weight * n > 1.0 + 1e-12:
        raise ValueError("individual_min_weight is infeasible for the number of assets")
    if max_weight * n < 1.0 - 1e-12:
        raise ValueError("individual_max_weight is infeasible for the number of assets")
    out = x.clip(lower=min_weight, upper=max_weight)
    for _ in range(100):
        total = float(out.sum())
        diff = 1.0 - total
        if abs(diff) < 1e-12:
            break
        if diff > 0:
            room = max_weight - out
            eligible = room > 1e-12
            if not eligible.any():
                break
            add = diff * room[eligible] / float(room[eligible].sum())
            out.loc[eligible] += add
        else:
            room = out - min_weight
            eligible = room > 1e-12
            if not eligible.any():
                break
            sub = (-diff) * room[eligible] / float(room[eligible].sum())
            out.loc[eligible] -= sub
    total = float(out.sum())
    return out / total if total > 0 else out


def _score_to_multiplicative_target(
    base: pd.Series,
    score: pd.Series,
    gamma: float,
    max_weight: float,
) -> tuple[pd.Series, pd.Series]:
    score = score.reindex(base.index).fillna(0.0)
    multiplier = np.exp(float(gamma) * score.clip(lower=-5.0, upper=5.0))
    raw = base * multiplier
    target = _normalize_with_cap(raw, float(max_weight))
    active = target - base.reindex(target.index, fill_value=0.0)
    return target.sort_index(), active.sort_index()


def _estimate_daily_covariance(
    return_mat: pd.DataFrame,
    date: pd.Timestamp,
    codes: pd.Index,
    lookback_days: int,
    shrinkage_to_diag: float,
) -> pd.DataFrame:
    hist = return_mat.loc[return_mat.index < date, codes].tail(int(lookback_days)).apply(pd.to_numeric, errors="coerce")
    if hist.empty:
        diag = pd.Series(0.0004, index=codes)
        return pd.DataFrame(np.diag(diag.values), index=codes, columns=codes)

    cov = hist.cov(min_periods=max(5, min(20, int(lookback_days) // 3))).reindex(index=codes, columns=codes)
    diag = hist.var(skipna=True).reindex(codes)
    fallback_var = float(diag.dropna().median()) if diag.notna().any() else 0.0004
    diag = diag.fillna(fallback_var).clip(lower=1e-8)
    cov = cov.fillna(0.0)
    for code in codes:
        cov.loc[code, code] = diag.loc[code]
    shrink = float(np.clip(shrinkage_to_diag, 0.0, 1.0))
    diag_cov = pd.DataFrame(np.diag(np.diag(cov.values)), index=codes, columns=codes)
    cov = (1.0 - shrink) * cov + shrink * diag_cov
    cov = (cov + cov.T) / 2.0
    cov.values[np.diag_indices_from(cov.values)] += 1e-8
    return cov


def _score_to_active_mvo_target(
    base: pd.Series,
    score: pd.Series,
    previous: pd.Series,
    return_mat: pd.DataFrame,
    date: pd.Timestamp,
    params: dict,
) -> tuple[pd.Series, pd.Series, dict]:
    idx = base.index.sort_values()
    base = base.reindex(idx).fillna(0.0)
    base = base / base.sum() if base.sum() > 0 else base
    prev = previous.reindex(idx, fill_value=0.0)
    score = score.reindex(idx).fillna(0.0)
    score = score - score.mean()
    if float(score.abs().sum()) == 0:
        return base.copy(), pd.Series(0.0, index=idx), {
            "optimizer_success": False,
            "optimizer_message": "flat score",
            "optimizer_predicted_te": 0.0,
            "optimizer_score_exposure": 0.0,
        }

    cov = _estimate_daily_covariance(
        return_mat=return_mat,
        date=pd.Timestamp(date),
        codes=idx,
        lookback_days=int(params["optimizer_cov_lookback_days"]),
        shrinkage_to_diag=float(params["optimizer_cov_shrinkage_to_diag"]),
    )
    hist = return_mat.loc[return_mat.index < pd.Timestamp(date), idx].tail(
        int(params["optimizer_cov_lookback_days"])
    )
    hist_counts = hist.notna().sum() if not hist.empty else pd.Series(0, index=idx)
    hist_start = hist.index.min() if not hist.empty else pd.NaT
    hist_end = hist.index.max() if not hist.empty else pd.NaT
    ann_cov = cov.values * 252.0
    base_vec = base.values.astype(float)
    prev_vec = prev.values.astype(float)
    score_vec = score.values.astype(float)
    min_weight = float(params.get("individual_min_weight", 0.0))
    max_weight = float(params["individual_max_weight"])
    te_target = float(params["optimizer_te_target"])
    risk_aversion = float(params["optimizer_risk_aversion"])
    turnover_penalty = float(params["optimizer_turnover_penalty"])

    def active_var(x: np.ndarray) -> float:
        active = x - base_vec
        return float(active @ ann_cov @ active)

    def objective(x: np.ndarray) -> float:
        active = x - base_vec
        score_exposure = float(score_vec @ active)
        risk_penalty = risk_aversion * active_var(x)
        turnover_pen = turnover_penalty * float(np.square(x - prev_vec).sum())
        return -score_exposure + risk_penalty + turnover_pen

    constraints = [
        {"type": "eq", "fun": lambda x: float(np.sum(x) - 1.0)},
        {"type": "ineq", "fun": lambda x: float(te_target**2 - active_var(x))},
    ]
    bounds = [(min_weight, max_weight) for _ in idx]
    result = minimize(
        objective,
        x0=base_vec,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-10, "disp": False},
    )
    if not result.success:
        return base.copy(), pd.Series(0.0, index=idx), {
            "optimizer_success": False,
            "optimizer_message": str(result.message),
            "optimizer_predicted_te": 0.0,
            "optimizer_score_exposure": 0.0,
            "optimizer_cov_min_observations": int(hist_counts.min()) if len(hist_counts) else 0,
            "optimizer_cov_median_observations": float(hist_counts.median()) if len(hist_counts) else 0.0,
            "optimizer_cov_missing_asset_count": int(
                (hist_counts < int(params["optimizer_cov_lookback_days"])).sum()
            )
            if len(hist_counts)
            else 0,
            "optimizer_cov_hist_start": hist_start,
            "optimizer_cov_hist_end": hist_end,
        }

    target = pd.Series(result.x, index=idx)
    target = _normalize_with_bounds(target, min_weight, max_weight)
    active = target - base.reindex(target.index, fill_value=0.0)
    predicted_te = float(np.sqrt(max(active.values @ ann_cov @ active.values, 0.0)))
    return target.sort_index(), active.sort_index(), {
        "optimizer_success": True,
        "optimizer_message": str(result.message),
        "optimizer_predicted_te": predicted_te,
        "optimizer_score_exposure": float(score_vec @ active.values),
        "optimizer_cov_min_observations": int(hist_counts.min()) if len(hist_counts) else 0,
        "optimizer_cov_median_observations": float(hist_counts.median()) if len(hist_counts) else 0.0,
        "optimizer_cov_missing_asset_count": int(
            (hist_counts < int(params["optimizer_cov_lookback_days"])).sum()
        )
        if len(hist_counts)
        else 0,
        "optimizer_cov_hist_start": hist_start,
        "optimizer_cov_hist_end": hist_end,
    }


def run_consensus_signal_ic(panel: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    panel = _load_panel() if panel is None else panel.copy()
    dates = pd.DatetimeIndex(sorted(panel["date"].dropna().unique()))
    rebalance_dates = sorted(set(choose_rebalance_dates(dates, "month_end")))
    return_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    return_mat.columns = return_mat.columns.astype(str).str.zfill(6)
    component_factors = []
    for components in SCORE_PROFILES.values():
        component_factors.extend([factor for factor, _, _ in components])
    component_factors = list(dict.fromkeys(component_factors))

    rows = []
    for idx, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[idx + 1]
        g = panel[panel["date"].eq(date)].copy()
        if g.empty:
            continue
        g_idx = g.set_index("stock_code").sort_index()
        future_return = _compound_forward_returns(
            return_mat,
            pd.Timestamp(date),
            pd.Timestamp(next_date),
            g_idx.index,
        )
        factors = {}
        for factor_name in component_factors:
            factors[factor_name] = (
                pd.to_numeric(g_idx[factor_name], errors="coerce")
                if factor_name in g_idx.columns
                else pd.Series(np.nan, index=g_idx.index)
            )
        for profile_name in SCORE_PROFILES:
            diagnostics, score = _build_consensus_score(g, score_profile=profile_name)
            factors[f"{profile_name}_score"] = score
        for factor_name, factor in factors.items():
            data = pd.DataFrame({"factor": factor, "future_return": future_return}).dropna()
            ic = float(data["factor"].rank().corr(data["future_return"].rank())) if len(data) >= 4 else np.nan
            tmb, top_n, bottom_n = _top_minus_bottom(factor, future_return)
            rows.append(
                {
                    "date": date,
                    "next_rebalance_date": next_date,
                    "factor": factor_name,
                    "observations": int(len(data)),
                    "spearman_ic": ic,
                    "top_minus_bottom_return": tmb,
                    "top_group_count": top_n,
                    "bottom_group_count": bottom_n,
                }
            )

    monthly = pd.DataFrame(rows)
    if monthly.empty:
        summary = pd.DataFrame()
    else:
        summary_rows = []
        for factor_name, g in monthly.groupby("factor"):
            ic = pd.to_numeric(g["spearman_ic"], errors="coerce").dropna()
            tmb = pd.to_numeric(g["top_minus_bottom_return"], errors="coerce").dropna()
            summary_rows.append(
                {
                    "factor": factor_name,
                    "observations": int(len(ic)),
                    "mean_ic": float(ic.mean()) if len(ic) else np.nan,
                    "median_ic": float(ic.median()) if len(ic) else np.nan,
                    "hit_ratio_ic_positive": float((ic > 0).mean()) if len(ic) else np.nan,
                    "mean_top_minus_bottom_return": float(tmb.mean()) if len(tmb) else np.nan,
                    "hit_ratio_top_minus_bottom_positive": float((tmb > 0).mean()) if len(tmb) else np.nan,
                }
            )
        summary = pd.DataFrame(summary_rows).sort_values("mean_ic", ascending=False)

    monthly.to_csv(OUTPUT_DIR / "consensus_score_signal_ic_monthly.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / "consensus_score_signal_ic_summary.csv", index=False, encoding="utf-8-sig")

    final_weekly_rows = []
    weekly_dates = sorted(set(choose_rebalance_dates(dates, "weekly")))
    final_factor_names = ["eps_revision_1m", "target_upside", "rating_point", "consensus_score"]
    for idx, date in enumerate(weekly_dates[:-1]):
        next_date = weekly_dates[idx + 1]
        g = panel[panel["date"].eq(date)].copy()
        if g.empty:
            continue
        g_idx = g.set_index("stock_code").sort_index()
        future_return = _compound_forward_returns(
            return_mat,
            pd.Timestamp(date),
            pd.Timestamp(next_date),
            g_idx.index,
        )
        diagnostics, consensus_score = _build_consensus_score(g, score_profile="consensus_core_equal")
        factors = {
            "eps_revision_1m": pd.to_numeric(g_idx.get("eps_revision_1m"), errors="coerce"),
            "target_upside": pd.to_numeric(g_idx.get("target_upside"), errors="coerce"),
            "rating_point": pd.to_numeric(g_idx.get("rating_point"), errors="coerce"),
            "consensus_score": consensus_score,
        }
        for factor_name in final_factor_names:
            factor = factors[factor_name]
            data = pd.DataFrame({"factor": factor, "future_return": future_return}).dropna()
            ic = float(data["factor"].rank().corr(data["future_return"].rank())) if len(data) >= 4 else np.nan
            tmb, top_n, bottom_n = _top_minus_bottom(factor, future_return)
            final_weekly_rows.append(
                {
                    "date": date,
                    "next_rebalance_date": next_date,
                    "factor": factor_name,
                    "observations": int(len(data)),
                    "spearman_ic": ic,
                    "top_minus_bottom_return": tmb,
                    "top_group_count": top_n,
                    "bottom_group_count": bottom_n,
                }
            )
    final_weekly = pd.DataFrame(final_weekly_rows)
    if final_weekly.empty:
        final_weekly_summary = pd.DataFrame()
    else:
        final_weekly_summary_rows = []
        for factor_name, g in final_weekly.groupby("factor"):
            ic = pd.to_numeric(g["spearman_ic"], errors="coerce").dropna()
            tmb = pd.to_numeric(g["top_minus_bottom_return"], errors="coerce").dropna()
            final_weekly_summary_rows.append(
                {
                    "factor": factor_name,
                    "observations": int(len(ic)),
                    "mean_ic": float(ic.mean()) if len(ic) else np.nan,
                    "median_ic": float(ic.median()) if len(ic) else np.nan,
                    "hit_ratio_ic_positive": float((ic > 0).mean()) if len(ic) else np.nan,
                    "mean_top_minus_bottom_return": float(tmb.mean()) if len(tmb) else np.nan,
                    "hit_ratio_top_minus_bottom_positive": float((tmb > 0).mean()) if len(tmb) else np.nan,
                }
            )
        final_weekly_summary = pd.DataFrame(final_weekly_summary_rows).sort_values("mean_ic", ascending=False)
    final_weekly.to_csv(
        OUTPUT_DIR / "consensus_score_final_weekly_ic.csv",
        index=False,
        encoding="utf-8-sig",
    )
    final_weekly_summary.to_csv(
        OUTPUT_DIR / "consensus_score_final_weekly_ic_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return {
        "monthly": monthly,
        "summary": summary,
        "final_weekly": final_weekly,
        "final_weekly_summary": final_weekly_summary,
    }


def run_consensus_score_strategy(
    params_override: dict | None = None,
    experiment_name: str = "consensus_current",
    panel: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    params = {**PARAMS, **(params_override or {})}
    panel = _load_panel() if panel is None else panel.copy()

    dates = pd.DatetimeIndex(sorted(panel["date"].dropna().unique()))
    rebalance_dates = sorted(set(choose_rebalance_dates(dates, str(params["rebalance_frequency"]))))
    rebalance_set = set(rebalance_dates)

    return_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    return_mat.columns = return_mat.columns.astype(str).str.zfill(6)
    covariance_return_mat = _build_covariance_return_matrix(return_mat)
    trading_value_mat = _build_trading_value_matrix(panel)
    stock_names = panel.dropna(subset=["stock_name"]).drop_duplicates("stock_code").set_index("stock_code")[
        "stock_name"
    ].to_dict()

    benchmark_returns = pd.read_csv(OUTPUT_DIR / "benchmark_pdf_returns.csv", parse_dates=["date"]).set_index("date")[
        "pdf_return"
    ]

    current = pd.Series(dtype=float)
    daily_rows = []
    weight_rows = []
    signal_rows = []
    turnover_rows = []
    active_history = []
    daily_fund_cost = daily_expense_rate(float(params["annual_fund_expense_rate"]))

    for date in dates:
        port_ret = np.nan
        current_active_return = np.nan
        if not current.empty and date in return_mat.index:
            ret = pd.to_numeric(return_mat.loc[date], errors="coerce").reindex(current.index).fillna(0.0)
            port_ret = float((current * ret).sum())
            benchmark_ret_today = benchmark_returns.get(pd.Timestamp(date), np.nan)
            if pd.notna(benchmark_ret_today):
                current_active_return = port_ret - float(benchmark_ret_today)
            denom = 1.0 + port_ret
            if denom != 0:
                current = current * (1.0 + ret) / denom

        g = panel[panel["date"].eq(date)].copy()
        if g.empty:
            if pd.notna(current_active_return):
                active_history.append(float(current_active_return))
            continue

        base = _benchmark_weights(g, str(params["benchmark_weight_column"]))
        if current.empty:
            current = base.copy()

        is_rebalance = date in rebalance_set
        trading_cost_return = 0.0
        turnover_info = {
            "desired_turnover_before_limit": 0.0,
            "turnover_limit": float(params["one_way_turnover_limit"]),
            "turnover_blend_ratio": 1.0,
            "realized_turnover_after_limit": 0.0,
            "turnover_was_binding": False,
            "traded_weight_after_limit": 0.0,
            "forced_pdf_universe_cleanup": False,
        }
        active_te_scale = 1.0
        active_te_rolling = np.nan
        optimizer_info = {
            "optimizer_success": np.nan,
            "optimizer_message": "",
            "optimizer_predicted_te": np.nan,
            "optimizer_score_exposure": np.nan,
        }

        if is_rebalance:
            score_profile = str(params.get("score_profile", "consensus_core"))
            score_components = _score_components(score_profile)
            diagnostics, score = _build_consensus_score(
                g,
                float(params["score_direction"]),
                score_profile,
            )
            target_method = str(params.get("target_method", "multiplicative"))
            if target_method == "multiplicative":
                raw_target, raw_active = _score_to_multiplicative_target(
                    base=base,
                    score=score,
                    gamma=float(params["score_gamma"]),
                    max_weight=float(params["individual_max_weight"]),
                )
            elif target_method == "active_mvo_te":
                raw_target, raw_active, optimizer_info = _score_to_active_mvo_target(
                    base=base,
                    score=score,
                    previous=current,
                    return_mat=covariance_return_mat,
                    date=pd.Timestamp(date),
                    params=params,
                )
            else:
                raw_target, raw_active = _score_to_target(
                    base=base,
                    score=score,
                    active_limit=float(params["individual_active_limit"]),
                    active_budget=float(params["active_budget"]),
                    max_weight=float(params["individual_max_weight"]),
                )
            if bool(params.get("active_te_budget_enabled", False)):
                lookback = int(params.get("active_te_lookback_days", 20))
                min_obs = int(params.get("active_te_min_observations", max(5, lookback // 2)))
                history = pd.Series(active_history, dtype=float).dropna().tail(lookback)
                if len(history) >= min_obs:
                    active_te_rolling = float(history.std(ddof=1) * np.sqrt(252))
                    if np.isfinite(active_te_rolling) and active_te_rolling > 0:
                        active_te_scale = min(1.0, float(params["active_te_target"]) / active_te_rolling)
                        active_te_scale = max(float(params["active_te_min_scale"]), active_te_scale)
                raw_target = base + active_te_scale * (raw_target.reindex(base.index, fill_value=0.0) - base)
                raw_target = _normalize_with_cap(raw_target, float(params["individual_max_weight"]))
                raw_active = raw_target - base.reindex(raw_target.index, fill_value=0.0)
            previous = current.copy()
            final, turnover_info = _apply_turnover_limit(
                previous=current,
                raw_target=raw_target,
                turnover_limit=float(params["one_way_turnover_limit"]),
            )
            turnover_info.setdefault("forced_pdf_universe_cleanup", False)
            if not final.index.difference(base.index).empty:
                cleaned_final = final.reindex(base.index, fill_value=0.0)
                cleaned_final = _normalize_with_cap(cleaned_final, float(params["individual_max_weight"]))
                turnover_idx = previous.index.union(cleaned_final.index)
                prev_for_turnover = previous.reindex(turnover_idx, fill_value=0.0)
                cleaned_for_turnover = cleaned_final.reindex(turnover_idx, fill_value=0.0)
                realized_turnover = 0.5 * float((cleaned_for_turnover - prev_for_turnover).abs().sum())
                final = cleaned_final
                turnover_info["realized_turnover_after_limit"] = realized_turnover
                turnover_info["traded_weight_after_limit"] = realized_turnover * 2.0
                turnover_info["forced_pdf_universe_cleanup"] = True
            min_weight = float(params.get("individual_min_weight", 0.0))
            if min_weight > 0:
                floored_final = _normalize_with_bounds(
                    final.reindex(base.index, fill_value=0.0),
                    min_weight,
                    float(params["individual_max_weight"]),
                )
                turnover_idx = previous.index.union(floored_final.index)
                prev_for_turnover = previous.reindex(turnover_idx, fill_value=0.0)
                floored_for_turnover = floored_final.reindex(turnover_idx, fill_value=0.0)
                realized_turnover = 0.5 * float((floored_for_turnover - prev_for_turnover).abs().sum())
                final = floored_final
                turnover_info["realized_turnover_after_limit"] = realized_turnover
                turnover_info["traded_weight_after_limit"] = realized_turnover * 2.0
                turnover_info["min_weight_floor_applied"] = True
            else:
                turnover_info["min_weight_floor_applied"] = False
            cost_detail = calc_rebalance_cost_from_weight_change(
                date=date,
                previous_weights=current,
                target_weights=final,
                scenario=str(params["cost_scenario"]),
                adv20_map=_adv20_map_for_date(trading_value_mat, pd.Timestamp(date)),
                dynamic_slippage=bool(params.get("dynamic_slippage_enabled", False)),
                portfolio_aum_krw=float(params.get("slippage_aum_krw", 0.0)),
                execution_days=int(params.get("slippage_execution_days", 1)),
                impact_coefficient=float(params.get("market_impact_coefficient", 0.0050)),
                impact_exponent=float(params.get("market_impact_exponent", 0.5)),
                max_impact_rate=float(params.get("market_impact_max_rate", 0.0050)),
            )
            trading_cost_return = -float(cost_detail["total_cost"])
            current = final

            for code in base.index.union(raw_target.index).union(final.index).union(previous.index):
                diag = diagnostics.reindex([code])

                def diag_float(col: str) -> float:
                    if code not in diag.index or col not in diag.columns:
                        return np.nan
                    value = pd.to_numeric(diag[col], errors="coerce").iloc[0]
                    return float(value) if pd.notna(value) else np.nan

                signal_rows.append(
                    {
                        "date": date,
                        "experiment_name": experiment_name,
                        "score_profile": score_profile,
                        "stock_code": code,
                        "stock_name": stock_names.get(code),
                        "benchmark_weight": float(base.reindex([code], fill_value=0.0).iloc[0]),
                        "raw_target_weight_before_turnover_limit": float(
                            raw_target.reindex([code], fill_value=0.0).iloc[0]
                        ),
                        "final_weight_after_turnover_limit": float(final.reindex([code], fill_value=0.0).iloc[0]),
                        "raw_active_weight": float(raw_active.reindex([code], fill_value=0.0).iloc[0]),
                        "final_active_weight": float(
                            final.reindex([code], fill_value=0.0).iloc[0]
                            - base.reindex([code], fill_value=0.0).iloc[0]
                        ),
                        "desired_trade_weight": float(
                            raw_target.reindex([code], fill_value=0.0).iloc[0]
                            - previous.reindex([code], fill_value=0.0).iloc[0]
                        ),
                        "actual_trade_weight": float(
                            final.reindex([code], fill_value=0.0).iloc[0]
                            - previous.reindex([code], fill_value=0.0).iloc[0]
                        ),
                        "eps_revision_1m": diag_float("eps_revision_1m"),
                        "eps_revision_3m": diag_float("eps_revision_3m"),
                        "op_revision_3m": diag_float("op_revision_3m"),
                        "target_upside": diag_float("target_upside"),
                        "rating_point": diag_float("rating_point"),
                        "earnings_yield_per": diag_float("earnings_yield_per"),
                        "book_to_price_pbr": diag_float("book_to_price_pbr"),
                        "sales_to_price_psr": diag_float("sales_to_price_psr"),
                        "vol_20d_ann": diag_float("vol_20d_ann"),
                        "z_eps_revision_1m": diag_float("z_eps_revision_1m"),
                        "z_target_upside": diag_float("z_target_upside"),
                        "z_rating_point": diag_float("z_rating_point"),
                        "consensus_score": diag_float("consensus_score"),
                        "usable_signal_count": int(diag_float("usable_signal_count"))
                        if pd.notna(diag_float("usable_signal_count"))
                        else 0,
                        "signal_coverage_ratio": diag_float("signal_coverage_ratio"),
                        "active_te_scale": active_te_scale,
                        "active_te_rolling": active_te_rolling,
                        "active_te_target": float(params["active_te_target"]),
                        **optimizer_info,
                        "turnover_was_binding": turnover_info["turnover_was_binding"],
                        "turnover_blend_ratio": turnover_info["turnover_blend_ratio"],
                        "forced_pdf_universe_cleanup": turnover_info["forced_pdf_universe_cleanup"],
                    }
                )

            turnover_rows.append(
                {
                    "date": date,
                    "experiment_name": experiment_name,
                    **turnover_info,
                    "trading_cost_return": trading_cost_return,
                    "cost_scenario": params["cost_scenario"],
                    "dynamic_slippage_enabled": bool(params.get("dynamic_slippage_enabled", False)),
                    "slippage_aum_krw": float(params.get("slippage_aum_krw", 0.0)),
                    "slippage_execution_days": int(params.get("slippage_execution_days", 1)),
                    "market_impact_coefficient": float(params.get("market_impact_coefficient", 0.0050)),
                    "market_impact_exponent": float(params.get("market_impact_exponent", 0.5)),
                    "market_impact_max_rate": float(params.get("market_impact_max_rate", 0.0050)),
                    "annual_fund_expense_rate": params["annual_fund_expense_rate"],
                    "total_traded_weight": cost_detail["total_traded_weight"],
                    "buy_weight": cost_detail["buy_weight"],
                    "sell_weight": cost_detail["sell_weight"],
                    "commission_return": -cost_detail["commission"],
                    "agency_fee_return": -cost_detail["agency_fee"],
                    "fixed_slippage_return": -cost_detail.get("base_slippage", 0.0),
                    "market_impact_slippage_return": -cost_detail.get("market_impact_slippage", 0.0),
                    "slippage_return": -cost_detail["slippage"],
                    "sell_tax_return": -cost_detail["tax"],
                    "average_cost_rate_on_traded_weight": cost_detail["average_cost_rate_on_traded_weight"],
                    "average_slippage_rate_on_traded_weight": cost_detail.get(
                        "average_slippage_rate_on_traded_weight", 0.0
                    ),
                    "max_slippage_rate": cost_detail.get("max_slippage_rate", 0.0),
                    "average_participation_rate": cost_detail.get("average_participation_rate", 0.0),
                    "max_participation_rate": cost_detail.get("max_participation_rate", 0.0),
                    "missing_adv_trade_weight": cost_detail.get("missing_adv_trade_weight", 0.0),
                    "active_te_budget_enabled": bool(params.get("active_te_budget_enabled", False)),
                    "active_te_scale": active_te_scale,
                    "active_te_rolling": active_te_rolling,
                    "active_te_target": float(params["active_te_target"]),
                    "active_te_lookback_days": int(params["active_te_lookback_days"]),
                    **optimizer_info,
                }
            )

        daily_rows.append(
            {
                "date": date,
                "experiment_name": experiment_name,
                "is_rebalance": is_rebalance,
                "turnover": turnover_info["realized_turnover_after_limit"],
                "trading_cost_return": trading_cost_return,
                "fund_expense_return": -daily_fund_cost,
                "active_te_scale": active_te_scale,
                "active_te_rolling": active_te_rolling,
                **optimizer_info,
                "position_count": int((current > 0).sum()) if not current.empty else 0,
            }
        )
        for code, weight in current.items():
            weight_rows.append(
                {
                    "date": date,
                    "experiment_name": experiment_name,
                    "stock_code": code,
                    "stock_name": stock_names.get(code),
                    "weight": float(weight),
                    "is_rebalance": is_rebalance,
                }
            )
        if pd.notna(current_active_return):
            active_history.append(float(current_active_return))

    daily = pd.DataFrame(daily_rows).sort_values("date")
    weights_long = pd.DataFrame(weight_rows).sort_values(["date", "stock_code"])
    weights = weights_long.pivot(index="date", columns="stock_code", values="weight").fillna(0.0).sort_index()
    returns = return_mat.reindex(index=weights.index, columns=weights.columns)
    strategy_before_cost = (weights.shift(1) * returns).sum(axis=1, min_count=1)

    daily_idx = daily.set_index("date").reindex(weights.index)
    trading_cost = pd.to_numeric(daily_idx["trading_cost_return"], errors="coerce").fillna(0.0)
    fund_expense = pd.to_numeric(daily_idx["fund_expense_return"], errors="coerce").fillna(0.0)
    benchmark = benchmark_returns.reindex(weights.index)
    strategy_cost_reflected = strategy_before_cost + trading_cost + fund_expense

    returns_out = pd.DataFrame(
        {
            "date": weights.index,
            "experiment_name": experiment_name,
            "strategy_return": strategy_cost_reflected.values,
            "strategy_cost_not_reflected_return": strategy_before_cost.values,
            "benchmark_pdf_return": benchmark.values,
            "active_return_cost_reflected": (strategy_cost_reflected - benchmark).values,
            "trading_cost_return": trading_cost.values,
            "fund_expense_return": fund_expense.values,
            "turnover": pd.to_numeric(daily_idx["turnover"], errors="coerce").fillna(0.0).values,
            "active_te_scale": pd.to_numeric(daily_idx["active_te_scale"], errors="coerce").fillna(1.0).values,
            "active_te_rolling": pd.to_numeric(daily_idx["active_te_rolling"], errors="coerce").values,
            "optimizer_success": pd.to_numeric(
                daily_idx.get("optimizer_success", pd.Series(index=daily_idx.index, dtype=float)),
                errors="coerce",
            ).values,
            "optimizer_predicted_te": pd.to_numeric(
                daily_idx.get("optimizer_predicted_te", pd.Series(index=daily_idx.index, dtype=float)),
                errors="coerce",
            ).values,
            "optimizer_score_exposure": pd.to_numeric(
                daily_idx.get("optimizer_score_exposure", pd.Series(index=daily_idx.index, dtype=float)),
                errors="coerce",
            ).values,
            "is_rebalance": daily_idx["is_rebalance"].fillna(False).astype(bool).values,
        }
    )
    returns_out["cumulative_strategy_return"] = (
        1.0 + returns_out["strategy_return"].fillna(0.0)
    ).cumprod() - 1.0
    returns_out["cumulative_benchmark_pdf_return"] = (
        1.0 + returns_out["benchmark_pdf_return"].fillna(0.0)
    ).cumprod() - 1.0
    returns_out["cumulative_active_return_pct_point"] = (
        returns_out["cumulative_strategy_return"] - returns_out["cumulative_benchmark_pdf_return"]
    )
    returns_out["cumulative_active_return"] = (
        (1.0 + returns_out["strategy_return"].fillna(0.0)).cumprod()
        / (1.0 + returns_out["benchmark_pdf_return"].fillna(0.0)).cumprod()
        - 1.0
    )
    returns_out["drawdown"] = drawdown_series(returns_out.set_index("date")["strategy_return"]).values

    ret_idx = returns_out.set_index("date")
    turnover_for_summary = pd.DataFrame(turnover_rows)
    summary_row = performance_summary(
        ret_idx["strategy_return"],
        ret_idx["benchmark_pdf_return"],
        experiment_name,
    )
    summary_row.update(
        {
            "experiment_name": experiment_name,
            "experiment_group": "consensus_score",
            "benchmark_cumulative_return": float(returns_out["cumulative_benchmark_pdf_return"].iloc[-1]),
            "excess_cumulative_return_pct_point": float(
                returns_out["cumulative_active_return_pct_point"].iloc[-1]
            ),
            "relative_active_cumulative_return": float(returns_out["cumulative_active_return"].iloc[-1]),
            "final_cumulative_active_return": float(returns_out["cumulative_active_return"].iloc[-1]),
            "average_turnover": float(returns_out["turnover"].mean()),
            "turnover_binding_count": int(
                turnover_for_summary.get("turnover_was_binding", pd.Series(dtype=bool)).sum()
            ),
            "total_trading_cost_return": float(returns_out["trading_cost_return"].sum()),
            "total_fund_expense_return": float(returns_out["fund_expense_return"].sum()),
            "average_active_te_scale": float(returns_out["active_te_scale"].mean()),
            "min_active_te_scale": float(returns_out["active_te_scale"].min()),
            "optimizer_success_rate": float(
                pd.to_numeric(turnover_for_summary.get("optimizer_success", pd.Series(dtype=float)), errors="coerce")
                .dropna()
                .mean()
            )
            if not turnover_for_summary.empty and "optimizer_success" in turnover_for_summary.columns
            else np.nan,
            "average_optimizer_predicted_te": float(
                pd.to_numeric(
                    turnover_for_summary.get("optimizer_predicted_te", pd.Series(dtype=float)), errors="coerce"
                ).mean()
            )
            if not turnover_for_summary.empty and "optimizer_predicted_te" in turnover_for_summary.columns
            else np.nan,
            "average_abs_active_weight": float(pd.DataFrame(signal_rows)["final_active_weight"].abs().mean())
            if signal_rows
            else np.nan,
            "max_abs_active_weight": float(pd.DataFrame(signal_rows)["final_active_weight"].abs().max())
            if signal_rows
            else np.nan,
            **params,
            "score_formula": _score_formula(_score_components(str(params.get("score_profile", "consensus_core")))),
            "target_formula": "target_weight ∝ etf_pdf_weight * exp(score_gamma * consensus_score)"
            if params.get("target_method") == "multiplicative"
            else (
                "maximize score_exposure - lambda*active_variance - eta*turnover_penalty "
                "subject to active_TE <= optimizer_te_target"
            )
            if params.get("target_method") == "active_mvo_te"
            else "target_weight = etf_pdf_weight + score_scaled_active_weight",
            "eps_revision_definition": "eps_next_year_e 21-trading-day percent change",
        }
    )
    summary = pd.DataFrame([summary_row])
    turnover = pd.DataFrame(turnover_rows).sort_values("date")
    signals = pd.DataFrame(signal_rows).sort_values(["date", "stock_code"])

    return {
        "returns": returns_out,
        "weights": weights_long,
        "signals": signals,
        "turnover": turnover,
        "summary": summary,
    }


def _save_final_stock_contribution(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    final_weights = weights[weights["experiment_name"].eq(FINAL_EXPERIMENT_NAME)].copy()
    final_returns = returns[returns["experiment_name"].eq(FINAL_EXPERIMENT_NAME)].copy()
    if final_weights.empty or final_returns.empty:
        return pd.DataFrame(), pd.DataFrame()

    final_weights["stock_code"] = final_weights["stock_code"].astype(str).str.zfill(6)
    stock_names = (
        panel.dropna(subset=["stock_name"])
        .drop_duplicates("stock_code")
        .set_index("stock_code")["stock_name"]
        .to_dict()
    )

    strategy_w = final_weights.pivot(index="date", columns="stock_code", values="weight").fillna(0.0).sort_index()
    return_mat = panel.pivot(index="date", columns="stock_code", values="return").sort_index()
    return_mat.columns = return_mat.columns.astype(str).str.zfill(6)

    pdf_raw = (
        panel.assign(pdf_weight=pd.to_numeric(panel["etf_weight_pct"], errors="coerce") / 100.0)
        .pivot(index="date", columns="stock_code", values="pdf_weight")
        .fillna(0.0)
        .sort_index()
    )
    pdf_raw.columns = pdf_raw.columns.astype(str).str.zfill(6)
    pdf_w = pdf_raw.clip(lower=0.0)
    pdf_w = pdf_w.div(pdf_w.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)

    all_codes = sorted(set(strategy_w.columns).union(pdf_w.columns).union(return_mat.columns))
    strategy_w = strategy_w.reindex(columns=all_codes, fill_value=0.0)
    pdf_w = pdf_w.reindex(index=strategy_w.index, columns=all_codes, fill_value=0.0)
    stock_ret = return_mat.reindex(index=strategy_w.index, columns=all_codes).fillna(0.0)

    active_lag = strategy_w.shift(1).fillna(0.0) - pdf_w.shift(1).fillna(0.0)
    contrib = active_lag * stock_ret
    overweight_contrib = contrib.where(active_lag > 0.0, 0.0)
    underweight_contrib = contrib.where(active_lag < 0.0, 0.0)

    long = (
        contrib.stack()
        .rename("active_contribution_return")
        .reset_index()
        .rename(columns={"level_0": "date", "level_1": "stock_code"})
    )
    long["active_weight_lag1"] = active_lag.stack().values
    long["stock_return"] = stock_ret.stack().values
    long["stock_name"] = long["stock_code"].map(stock_names)
    long = long[
        [
            "date",
            "stock_code",
            "stock_name",
            "active_weight_lag1",
            "stock_return",
            "active_contribution_return",
        ]
    ]
    long.to_csv(OUTPUT_DIR / "final_stock_active_contribution_daily.csv", index=False, encoding="utf-8-sig")

    summary_rows = []
    for code in all_codes:
        aw = active_lag[code]
        c = contrib[code]
        ow = overweight_contrib[code]
        uw = underweight_contrib[code]
        summary_rows.append(
            {
                "stock_code": code,
                "stock_name": stock_names.get(code),
                "total_active_contribution_return": float(c.sum()),
                "overweight_contribution_return": float(ow.sum()),
                "underweight_contribution_return": float(uw.sum()),
                "average_active_weight": float(aw.mean()),
                "average_abs_active_weight": float(aw.abs().mean()),
                "max_overweight": float(aw.max()),
                "max_underweight": float(aw.min()),
                "overweight_days": int((aw > 1e-12).sum()),
                "underweight_days": int((aw < -1e-12).sum()),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary["total_active_contribution_pct_point"] = summary["total_active_contribution_return"] * 100.0
    summary["overweight_contribution_pct_point"] = summary["overweight_contribution_return"] * 100.0
    summary["underweight_contribution_pct_point"] = summary["underweight_contribution_return"] * 100.0
    summary = summary.sort_values("total_active_contribution_return", ascending=False)
    summary.to_csv(OUTPUT_DIR / "final_stock_active_contribution_summary.csv", index=False, encoding="utf-8-sig")

    cost_breakdown = pd.DataFrame(
        [
            {
                "component": "stock_active_contribution_before_cost",
                "return_sum": float(contrib.sum(axis=1).sum()),
                "pct_point": float(contrib.sum(axis=1).sum() * 100.0),
            },
            {
                "component": "trading_cost",
                "return_sum": float(final_returns["trading_cost_return"].sum()),
                "pct_point": float(final_returns["trading_cost_return"].sum() * 100.0),
            },
            {
                "component": "fund_expense",
                "return_sum": float(final_returns["fund_expense_return"].sum()),
                "pct_point": float(final_returns["fund_expense_return"].sum() * 100.0),
            },
            {
                "component": "total_arithmetic_active_return_after_cost",
                "return_sum": float(final_returns["active_return_cost_reflected"].sum()),
                "pct_point": float(final_returns["active_return_cost_reflected"].sum() * 100.0),
            },
        ]
    )
    cost_breakdown.to_csv(
        OUTPUT_DIR / "final_active_contribution_cost_breakdown.csv",
        index=False,
        encoding="utf-8-sig",
    )

    top = pd.concat([summary.head(6), summary.tail(6)], ignore_index=True)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = np.where(top["total_active_contribution_return"] >= 0, "#2ca02c", "#d62728")
    ax.barh(top["stock_name"], top["total_active_contribution_return"] * 100.0, color=colors)
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_title("종목별 PDF 대비 초과성과 기여도")
    ax.set_xlabel("누적 active contribution (%p, 단순합)")
    ax.set_ylabel("종목")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_stock_active_contribution.png", dpi=170)
    plt.close(fig)

    return long, summary


def _run_final_robustness_checks(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    base_override = {
        "score_profile": "consensus_core_equal",
        "target_method": "active_mvo_te",
        "individual_min_weight": 0.01,
        "individual_max_weight": 0.50,
        "one_way_turnover_limit": 0.30,
        "optimizer_te_target": FINAL_TE_TARGET,
        "optimizer_cov_lookback_days": 60,
        "optimizer_cov_shrinkage_to_diag": 0.30,
        "optimizer_risk_aversion": 1.0,
        "optimizer_turnover_penalty": 0.05,
        "cost_scenario": "base",
        "rebalance_frequency": "weekly",
    }
    specs = [
        ("baseline", "최종 기준", {}),
        ("te10", "TE budget", {"optimizer_te_target": 0.10}),
        ("te15", "TE budget", {"optimizer_te_target": 0.15}),
        ("te20", "TE budget", {"optimizer_te_target": 0.20}),
        ("max_weight30", "Max weight", {"individual_max_weight": 0.30}),
        ("max_weight50", "Max weight", {"individual_max_weight": 0.50}),
        ("max_weight70", "Max weight", {"individual_max_weight": 0.70}),
        ("cost_base", "Cost", {"cost_scenario": "base"}),
        ("cost_stress", "Cost", {"cost_scenario": "stress"}),
        (
            "cost_dynamic",
            "Cost",
            {
                "cost_scenario": "base",
                "dynamic_slippage_enabled": True,
                "slippage_aum_krw": 10_000_000_000.0,
                "slippage_execution_days": 3,
                "market_impact_coefficient": 0.0050,
                "market_impact_exponent": 0.5,
            },
        ),
        ("rebalance_weekly", "Rebalance", {"rebalance_frequency": "weekly"}),
        ("rebalance_biweekly", "Rebalance", {"rebalance_frequency": "biweekly"}),
        ("factor_503020", "Factor weight", {"score_profile": "consensus_core"}),
        ("factor_equal", "Factor weight", {"score_profile": "consensus_core_equal"}),
    ]

    results = []
    category_rows = []
    for name, category, override in specs:
        params = {**base_override, **override}
        result = run_consensus_score_strategy(params, f"robust_{name}", panel)
        summary = result["summary"].copy()
        summary["robustness_category"] = category
        summary["robustness_setting"] = name
        summary["setting_label"] = _robustness_setting_label(name, params)
        category_rows.append(summary)
        results.append(result)

    summary = pd.concat(category_rows, ignore_index=True)
    returns = pd.concat([r["returns"] for r in results], ignore_index=True)
    summary_cols = [
        "robustness_category",
        "robustness_setting",
        "setting_label",
        "experiment_name",
        "cumulative_return",
        "benchmark_cumulative_return",
        "excess_cumulative_return_pct_point",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "tracking_error",
        "information_ratio",
        "correlation",
        "average_turnover",
        "turnover_binding_count",
        "total_trading_cost_return",
        "individual_min_weight",
        "individual_max_weight",
        "optimizer_te_target",
        "cost_scenario",
        "dynamic_slippage_enabled",
        "slippage_aum_krw",
        "slippage_execution_days",
        "market_impact_coefficient",
        "rebalance_frequency",
        "score_profile",
    ]
    available = [c for c in summary_cols if c in summary.columns]
    summary = summary[available].copy()
    summary.to_csv(OUTPUT_DIR / "final_strategy_robustness_summary.csv", index=False, encoding="utf-8-sig")
    returns.to_csv(OUTPUT_DIR / "final_strategy_robustness_returns.csv", index=False, encoding="utf-8-sig")

    presentation = summary[
        summary["robustness_setting"].isin(
            [
                "baseline",
                "te10",
                "te15",
                "te20",
                "max_weight30",
                "max_weight50",
                "cost_stress",
                "cost_dynamic",
                "rebalance_biweekly",
            ]
        )
    ].copy()
    presentation.to_csv(
        OUTPUT_DIR / "final_strategy_robustness_presentation_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, ax = plt.subplots(figsize=(9, 5.5))
    plot_df = presentation.drop_duplicates("robustness_setting").copy()
    ax.scatter(
        plot_df["tracking_error"] * 100.0,
        plot_df["excess_cumulative_return_pct_point"] * 100.0,
        s=85,
        c=plot_df["information_ratio"],
        cmap="viridis",
    )
    for _, row in plot_df.iterrows():
        ax.annotate(row["setting_label"], (row["tracking_error"] * 100.0, row["excess_cumulative_return_pct_point"] * 100.0), fontsize=8)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("강건성 검증: 초과성과 vs TE")
    ax.set_xlabel("PDF 대비 realized TE (% 연율화)")
    ax.set_ylabel("PDF 대비 누적 초과성과 (%p)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_final_robustness_return_vs_te.png", dpi=170)
    plt.close(fig)

    return {"summary": summary, "returns": returns, "presentation": presentation}


def _robustness_setting_label(name: str, params: dict) -> str:
    if name == "baseline":
        return "최종 기준"
    if name.startswith("te"):
        return f"TE {float(params['optimizer_te_target']) * 100:.0f}%"
    if name.startswith("max_weight"):
        return f"Max {float(params['individual_max_weight']) * 100:.0f}%"
    if name == "cost_dynamic":
        return "Dynamic cost"
    if name.startswith("cost"):
        return f"Cost {params['cost_scenario']}"
    if name.startswith("rebalance"):
        return "주간" if params["rebalance_frequency"] == "weekly" else "격주"
    if name == "factor_equal":
        return "팩터 동일가중"
    if name == "factor_503020":
        return "팩터 50/30/20"
    return name


def _save_cost_model_comparison(summary: pd.DataFrame, turnover: pd.DataFrame) -> pd.DataFrame:
    """Compare the fixed base cost result with the ADV-linked slippage scenario."""
    experiments = [FINAL_EXPERIMENT_NAME, DYNAMIC_COST_EXPERIMENT_NAME]
    base = summary[summary["experiment_name"].isin(experiments)].copy()
    if base.empty:
        return pd.DataFrame()

    order = {name: idx for idx, name in enumerate(experiments)}
    base["_order"] = base["experiment_name"].map(order).fillna(99)

    return_cols = [
        "trading_cost_return",
        "commission_return",
        "agency_fee_return",
        "fixed_slippage_return",
        "market_impact_slippage_return",
        "slippage_return",
        "sell_tax_return",
    ]
    diag_cols = [
        "average_cost_rate_on_traded_weight",
        "average_slippage_rate_on_traded_weight",
        "max_slippage_rate",
        "average_participation_rate",
        "max_participation_rate",
        "missing_adv_trade_weight",
    ]
    available_returns = [c for c in return_cols if c in turnover.columns]
    available_diag = [c for c in diag_cols if c in turnover.columns]

    grouped_returns = turnover[turnover["experiment_name"].isin(experiments)].groupby(
        "experiment_name", as_index=False
    )[available_returns].sum()
    grouped_diag = turnover[turnover["experiment_name"].isin(experiments)].groupby(
        "experiment_name", as_index=False
    )[available_diag].mean()
    grouped = grouped_returns.merge(grouped_diag, on="experiment_name", how="outer")

    cols = [
        "experiment_name",
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
        "average_turnover",
        "dynamic_slippage_enabled",
        "slippage_aum_krw",
        "slippage_execution_days",
        "market_impact_coefficient",
        "market_impact_exponent",
        "market_impact_max_rate",
        "_order",
    ]
    comp = base[[c for c in cols if c in base.columns]].merge(grouped, on="experiment_name", how="left")
    comp["cost_model_label"] = np.where(
        comp.get("dynamic_slippage_enabled", False),
        "ADV20 participation dynamic slippage",
        "Fixed base slippage 3bp",
    )
    comp["average_slippage_bp_on_traded_weight"] = (
        comp.get("average_slippage_rate_on_traded_weight", np.nan) * 10000.0
    )
    comp["max_slippage_bp_on_traded_weight"] = comp.get("max_slippage_rate", np.nan) * 10000.0
    comp["average_participation_pct"] = comp.get("average_participation_rate", np.nan) * 100.0
    comp["max_participation_pct"] = comp.get("max_participation_rate", np.nan) * 100.0
    comp = comp.sort_values("_order").drop(columns=["_order"], errors="ignore")

    comp.to_csv(OUTPUT_DIR / "final_cost_model_comparison.csv", index=False, encoding="utf-8-sig")

    pretty = comp.copy()
    pretty["비용 모델"] = pretty["cost_model_label"].replace(
        {
            "Fixed base slippage 3bp": "기존 base: 고정 슬리피지 3bp",
            "ADV20 participation dynamic slippage": "추가 점검: 20D ADV 참여율 연동 슬리피지",
        }
    )
    pretty["누적수익률"] = pretty["cumulative_return"].map(lambda x: f"{x * 100:.2f}%")
    pretty["PDF 대비 초과"] = pretty["excess_cumulative_return_pct_point"].map(lambda x: f"{x * 100:+.2f}%p")
    pretty["Sharpe"] = pretty["sharpe_ratio"].map(lambda x: f"{x:.3f}")
    pretty["TE"] = pretty["tracking_error"].map(lambda x: f"{x * 100:.2f}%")
    pretty["IR"] = pretty["information_ratio"].map(lambda x: f"{x:.3f}")
    pretty["총 매매비용"] = pretty["trading_cost_return"].map(lambda x: f"{x * 100:.2f}%p")
    pretty["시장충격 슬리피지"] = pretty["market_impact_slippage_return"].map(lambda x: f"{x * 100:.2f}%p")
    pretty["평균 슬리피지"] = pretty["average_slippage_bp_on_traded_weight"].map(lambda x: f"{x:.2f}bp")
    pretty["평균 ADV 참여율"] = pretty["average_participation_pct"].map(lambda x: f"{x:.2f}%")
    pretty["최대 ADV 참여율"] = pretty["max_participation_pct"].map(lambda x: f"{x:.2f}%")
    pretty_cols = [
        "비용 모델",
        "누적수익률",
        "PDF 대비 초과",
        "Sharpe",
        "TE",
        "IR",
        "총 매매비용",
        "시장충격 슬리피지",
        "평균 슬리피지",
        "평균 ADV 참여율",
        "최대 ADV 참여율",
    ]
    pretty[pretty_cols].to_csv(
        OUTPUT_DIR / "final_cost_model_comparison_pretty.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return comp


def _plot_experiment_charts(returns: pd.DataFrame, summary: pd.DataFrame, signals: pd.DataFrame) -> None:
    ret = returns[returns["experiment_name"].isin(PRESENTATION_EXPERIMENTS)].copy()
    visible_summary = summary[summary["experiment_name"].isin(PRESENTATION_EXPERIMENTS)].copy()
    ret["date"] = pd.to_datetime(ret["date"], errors="coerce")
    final = returns[returns["experiment_name"].eq(FINAL_EXPERIMENT_NAME)].copy()
    final["date"] = pd.to_datetime(final["date"], errors="coerce")

    if not final.empty:
        final = final.sort_values("date")
        fig, ax = plt.subplots(figsize=(12, 5.5))
        ax.plot(
            final["date"],
            final["cumulative_strategy_return"] * 100.0,
            label="최종 전략",
            linewidth=2.4,
            color="#1f77b4",
        )
        ax.plot(
            final["date"],
            final["cumulative_benchmark_pdf_return"] * 100.0,
            label="PDF 벤치마크",
            linewidth=2.0,
            color="#ff7f0e",
            linestyle="--",
        )
        ax.set_title("최종 전략과 PDF 벤치마크 누적수익률")
        ax.set_xlabel("날짜")
        ax.set_ylabel("누적수익률 (%)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_final_cumulative_return.png", dpi=170)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.plot(
            final["date"],
            final["cumulative_active_return_pct_point"] * 100.0,
            label="최종 전략 - PDF",
            linewidth=2.3,
            color="#2ca02c",
        )
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title("PDF 대비 누적 초과성과")
        ax.set_xlabel("날짜")
        ax.set_ylabel("누적 초과성과 (%p)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_final_cumulative_active_return.png", dpi=170)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.plot(
            final["date"],
            final["drawdown"] * 100.0,
            label="최종 전략",
            linewidth=2.0,
            color="#d62728",
        )
        ax.set_title("최종 전략 Drawdown")
        ax.set_xlabel("날짜")
        ax.set_ylabel("고점 대비 낙폭 (%)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_final_drawdown.png", dpi=170)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5.5))
    for name, g in ret.groupby("experiment_name"):
        g = g.sort_values("date")
        y_col = "cumulative_active_return_pct_point"
        ax.plot(
            g["date"],
            g[y_col] * 100.0,
            label=PRESENTATION_LABELS.get(name, name),
            linewidth=2,
        )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("같은 컨센서스 점수를 비중에 반영하는 방식별 초과성과")
    ax.set_xlabel("날짜")
    ax.set_ylabel("PDF 대비 누적 초과성과 (%p)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_consensus_score_experiment_active_return.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    x = visible_summary["tracking_error"] * 100.0
    y = visible_summary["excess_cumulative_return_pct_point"] * 100.0
    c = visible_summary["information_ratio"]
    scatter = ax.scatter(x, y, c=c, s=95, cmap="viridis")
    for _, row in visible_summary.iterrows():
        ax.annotate(
            PRESENTATION_LABELS.get(row["experiment_name"], row["experiment_name"]),
            (row["tracking_error"] * 100.0, row["excess_cumulative_return_pct_point"] * 100.0),
            fontsize=8,
        )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_xlabel("PDF 대비 tracking error (% 연율화)")
    ax.set_ylabel("PDF 대비 누적 초과성과 (%p)")
    ax.set_title("초과성과와 active risk의 관계")
    ax.grid(True, alpha=0.3)
    fig.colorbar(scatter, ax=ax, label="Information ratio")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "chart_consensus_score_return_vs_te.png", dpi=170)
    plt.close(fig)

    if not signals.empty:
        latest_date = pd.to_datetime(signals["date"]).max()
        latest = signals[
            pd.to_datetime(signals["date"]).eq(latest_date)
            & signals["experiment_name"].eq(FINAL_EXPERIMENT_NAME)
        ].copy()
        if latest.empty:
            latest = signals[pd.to_datetime(signals["date"]).eq(latest_date)].copy()
        latest = latest.sort_values("consensus_score")
        fig, ax = plt.subplots(figsize=(11, 5.5))
        ax.barh(
            latest["stock_name"],
            latest["consensus_score"],
            color=np.where(latest["consensus_score"] >= 0, "#2ca02c", "#d62728"),
        )
        ax.axvline(0.0, color="black", linewidth=0.8)
        ax.set_title(f"최근 리밸런싱일 종목별 컨센서스 점수 ({latest_date:%Y-%m-%d})")
        ax.set_xlabel("컨센서스 점수")
        ax.set_ylabel("종목")
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_consensus_score_latest_scores.png", dpi=170)
        plt.close(fig)


def run_all_active_experiments() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    panel = _load_panel()
    ic = run_consensus_signal_ic(panel)
    weekly_ic_summary = ic.get("final_weekly_summary", pd.DataFrame())
    if not weekly_ic_summary.empty:
        display_names = {
            "eps_revision_1m": "EPS revision 1M",
            "target_upside": "Target upside",
            "rating_point": "Rating point",
            "consensus_score": "Consensus score",
        }
        plot_df = weekly_ic_summary.copy()
        plot_df["label"] = plot_df["factor"].map(display_names).fillna(plot_df["factor"])
        order = ["EPS revision 1M", "Target upside", "Rating point", "Consensus score"]
        plot_df["label"] = pd.Categorical(plot_df["label"], categories=order, ordered=True)
        plot_df = plot_df.sort_values("label")
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        ax.bar(
            plot_df["label"].astype(str),
            plot_df["mean_ic"],
            color="#1f77b4",
            alpha=0.85,
        )
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title("최종 3개 신호의 주간 Spearman IC")
        ax.set_xlabel("신호")
        ax.set_ylabel("평균 IC")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "chart_final_weekly_ic.png", dpi=170)
        plt.close(fig)

    results = []
    for name, override in EXPERIMENTS.items():
        results.append(run_consensus_score_strategy(override, name, panel))

    returns = pd.concat([r["returns"] for r in results], ignore_index=True)
    weights = pd.concat([r["weights"] for r in results], ignore_index=True)
    signals = pd.concat([r["signals"] for r in results], ignore_index=True)
    turnover = pd.concat([r["turnover"] for r in results], ignore_index=True)
    summary = pd.concat([r["summary"] for r in results], ignore_index=True).sort_values(
        "information_ratio", ascending=False
    )

    returns.to_csv(OUTPUT_DIR / "advanced_experiment_returns.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(OUTPUT_DIR / "advanced_experiment_weights.csv", index=False, encoding="utf-8-sig")
    signals.to_csv(OUTPUT_DIR / "advanced_experiment_signals.csv", index=False, encoding="utf-8-sig")
    turnover.to_csv(OUTPUT_DIR / "advanced_experiment_turnover.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / "advanced_experiment_summary.csv", index=False, encoding="utf-8-sig")
    summary[summary["experiment_name"].isin(PRESENTATION_EXPERIMENTS)].to_csv(
        OUTPUT_DIR / "advanced_experiment_presentation_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    cost_model_comparison = _save_cost_model_comparison(summary, turnover)

    presentation_summary = summary[summary["experiment_name"].isin(PRESENTATION_EXPERIMENTS)]
    if FINAL_EXPERIMENT_NAME in set(presentation_summary["experiment_name"]):
        primary_name = FINAL_EXPERIMENT_NAME
    else:
        primary = presentation_summary.sort_values("cumulative_return", ascending=False).head(1)
        primary_name = primary["experiment_name"].iloc[0] if not primary.empty else summary["experiment_name"].iloc[0]
    returns[returns["experiment_name"].eq(primary_name)].to_csv(
        OUTPUT_DIR / "consensus_score_strategy_returns.csv", index=False, encoding="utf-8-sig"
    )
    weights[weights["experiment_name"].eq(primary_name)].to_csv(
        OUTPUT_DIR / "consensus_score_strategy_weights.csv", index=False, encoding="utf-8-sig"
    )
    signals[signals["experiment_name"].eq(primary_name)].to_csv(
        OUTPUT_DIR / "consensus_score_strategy_signal_diagnostics.csv", index=False, encoding="utf-8-sig"
    )
    turnover[turnover["experiment_name"].eq(primary_name)].to_csv(
        OUTPUT_DIR / "consensus_score_strategy_turnover_diagnostics.csv", index=False, encoding="utf-8-sig"
    )
    summary[summary["experiment_name"].eq(primary_name)].to_csv(
        OUTPUT_DIR / "consensus_score_strategy_summary.csv", index=False, encoding="utf-8-sig"
    )

    _plot_experiment_charts(returns, summary, signals)
    contribution_daily, contribution_summary = _save_final_stock_contribution(panel, weights, returns)
    robustness = _run_final_robustness_checks(panel)
    from active_te_overlay_experiment import run_active_te_overlay_experiments
    from final_presentation_diagnostics import run_final_presentation_diagnostics

    overlay = run_active_te_overlay_experiments()
    final_diagnostics = run_final_presentation_diagnostics()

    return {
        "returns": returns,
        "weights": weights,
        "signals": signals,
        "turnover": turnover,
        "summary": summary,
        "overlay_returns": overlay["returns"],
        "overlay_summary": overlay["summary"],
        "contribution_daily": contribution_daily,
        "contribution_summary": contribution_summary,
        "robustness_summary": robustness["summary"],
        "robustness_returns": robustness["returns"],
        "cost_model_comparison": cost_model_comparison,
        "final_diagnostics": final_diagnostics,
        "ic_monthly": ic["monthly"],
        "ic_summary": ic["summary"],
    }


if __name__ == "__main__":
    result = run_all_active_experiments()
    print(result["ic_summary"].to_string(index=False))
    print(result["summary"].to_string(index=False))
