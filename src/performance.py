import numpy as np
import pandas as pd


TRADING_DAYS = 252


def cumulative_return(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    return float((1.0 + r).prod() - 1.0)


def annualized_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    total = (1.0 + r).prod()
    return float(total ** (periods_per_year / len(r)) - 1.0)


def annualized_volatility(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    ann_vol = annualized_volatility(returns, periods_per_year)
    if pd.isna(ann_vol) or ann_vol == 0:
        return np.nan
    return annualized_return(returns, periods_per_year) / ann_vol


def max_drawdown(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    wealth = (1.0 + r).cumprod()
    running_peak = wealth.cummax().clip(lower=1.0)
    drawdown = wealth / running_peak - 1.0
    return float(drawdown.min())


def drawdown_series(returns: pd.Series) -> pd.Series:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    running_peak = wealth.cummax().clip(lower=1.0)
    return wealth / running_peak - 1.0


def tracking_error(active_returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    ar = active_returns.dropna()
    if len(ar) < 2:
        return np.nan
    return float(ar.std(ddof=1) * np.sqrt(periods_per_year))


def tracking_error_summary(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = TRADING_DAYS,
) -> dict:
    aligned = pd.concat(
        [
            pd.to_numeric(strategy_returns, errors="coerce"),
            pd.to_numeric(benchmark_returns, errors="coerce"),
        ],
        axis=1,
    ).dropna()
    aligned.columns = ["strategy", "benchmark"]
    active = aligned["strategy"] - aligned["benchmark"]
    daily_std = float(active.std(ddof=1)) if len(active) >= 2 else np.nan
    return {
        "annualized_tracking_error": float(daily_std * np.sqrt(periods_per_year)) if pd.notna(daily_std) else np.nan,
        "daily_active_std": daily_std,
        "active_return_mean_daily": float(active.mean()) if not active.empty else np.nan,
        "observations": int(len(active)),
    }


def information_ratio(active_returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    te = tracking_error(active_returns, periods_per_year)
    if pd.isna(te) or te == 0:
        return np.nan
    return float(active_returns.dropna().mean() * periods_per_year / te)


def performance_summary(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    name: str = "strategy",
) -> dict:
    returns = returns.astype(float)
    out = {
        "strategy": name,
        "observations": int(returns.dropna().shape[0]),
        "cumulative_return": cumulative_return(returns),
        "annualized_return": annualized_return(returns),
        "annualized_volatility": annualized_volatility(returns),
        "sharpe_ratio": sharpe_ratio(returns),
        "max_drawdown": max_drawdown(returns),
    }
    if benchmark_returns is not None:
        aligned = pd.concat([returns, benchmark_returns.astype(float)], axis=1).dropna()
        aligned.columns = ["returns", "benchmark"]
        active = aligned["returns"] - aligned["benchmark"]
        out.update(
            {
                "excess_cumulative_return": cumulative_return(aligned["returns"])
                - cumulative_return(aligned["benchmark"]),
                "tracking_error": tracking_error(active),
                "active_tracking_error_annualized": tracking_error(active),
                "information_ratio": information_ratio(active),
                "correlation": float(aligned["returns"].corr(aligned["benchmark"]))
                if len(aligned) >= 2
                else np.nan,
                "active_return_mean_daily": float(active.mean()) if not active.empty else np.nan,
                "active_return_std_daily": float(active.std(ddof=1)) if len(active) >= 2 else np.nan,
            }
        )
    return out


def monthly_returns(returns: pd.Series) -> pd.Series:
    r = returns.dropna().copy()
    if not isinstance(r.index, pd.DatetimeIndex):
        raise TypeError("returns index must be DatetimeIndex")
    return (1.0 + r).resample("ME").prod() - 1.0
