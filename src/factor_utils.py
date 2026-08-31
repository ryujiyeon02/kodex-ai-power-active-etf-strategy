from __future__ import annotations

import numpy as np
import pandas as pd


def zscore_cross_section(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score with median fill for missing factor values."""
    x = pd.to_numeric(s, errors="coerce").astype(float)
    x = x.fillna(x.median() if x.notna().any() else 0.0)
    std = x.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (x - x.mean()) / std


def prepare_signal_source(g: pd.DataFrame) -> pd.DataFrame:
    """Create reusable factor columns for IC diagnostics and direct factor tilt."""
    g = g.copy()

    def num(col: str) -> pd.Series:
        if col not in g.columns:
            return pd.Series(np.nan, index=g.index)
        return pd.to_numeric(g[col], errors="coerce")

    def ratio(new_col: str, numer_col: str, denom_col: str) -> None:
        numer = num(numer_col)
        denom = num(denom_col).replace(0.0, np.nan).abs()
        g[new_col] = numer / denom - 1.0

    ratio("sales_growth_fy1_vs_fy0", "sales_fy1", "sales_fy0")
    ratio("op_growth_fy1_vs_fy0", "op_fy1", "op_fy0")
    ratio("ni_growth_fy1_vs_fy0", "ni_fy1", "ni_fy0")
    ratio("eps_growth_fy1_vs_fy0", "eps_fy1", "eps_fy0")
    g["rating_up_ratio"] = num("rating_up_count") / num("rating_total_count").replace(0.0, np.nan)
    g["rating_down_ratio"] = num("rating_down_count") / num("rating_total_count").replace(0.0, np.nan)
    g["target_high_low_spread_pct"] = (num("target_price_high") - num("target_price_low")) / num(
        "target_price_median"
    ).replace(0.0, np.nan)
    g["log_trading_value"] = np.log1p(num("trading_value"))
    g["log_market_cap"] = np.log1p(num("market_cap"))
    g["log_volume"] = np.log1p(num("volume"))
    analyst_cols = [c for c in ["analyst_count_fy0", "analyst_count_fy1"] if c in g.columns]
    if analyst_cols:
        g["analyst_coverage"] = g[analyst_cols].apply(pd.to_numeric, errors="coerce").max(axis=1)
    else:
        g["analyst_coverage"] = np.nan
    return g
