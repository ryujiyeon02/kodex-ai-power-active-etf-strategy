import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_model_panel_v2 import parse_fnguide_wide_xlsx
from project_paths import (
    BACKTEST_START,
    CASH_CODE,
    ETF_DAILY_FILE,
    INDEX_DAILY_FILE,
    INPUT_DIR,
    MODEL_PANEL_FILE,
    MODEL_PANEL_MONTHLY_FILE,
    OUTPUT_DIR,
    PDF_HISTORY_FILE,
    PDF_WEIGHTS_PIVOT_FILE,
    PRICE_FILE,
    PRICE_LONG_FILE,
    TARGET_RATING_LONG_FILE,
    CONSENSUS_FY_PANEL_FILE,
    CONSENSUS_LONG_FILE,
    ensure_output_dir,
)


def normalize_code_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"^A", "", regex=True)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(6)
    )


def normalize_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str), errors="coerce")


def read_index_html_xls(path: Path) -> pd.DataFrame:
    tables = pd.read_html(path)
    if not tables:
        return pd.DataFrame()
    df = tables[0].copy()
    if "일자" in df.columns:
        df = df.rename(columns={"일자": "date", "지수 값": "index_close"})
    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce")
    return df


def valid_excel_input(path: Path) -> bool:
    return path.is_file() and not path.name.startswith("~$")


def profile_dataframe(name: str, path: Path, df: pd.DataFrame, date_col: str | None, code_col: str | None):
    rows = len(df)
    cols = len(df.columns)
    date_min = date_max = pd.NaT
    invalid_dates = np.nan
    if date_col and date_col in df.columns:
        dt = normalize_date_series(df[date_col])
        invalid_dates = int(dt.isna().sum())
        if dt.notna().any():
            date_min = dt.min()
            date_max = dt.max()

    stock_count = np.nan
    invalid_codes = np.nan
    if code_col and code_col in df.columns:
        raw_code = df[code_col].astype(str)
        is_cash = raw_code.eq(CASH_CODE)
        code = normalize_code_series(df.loc[~is_cash, code_col])
        stock_count = int(code[code.str.match(r"^\d{6}$", na=False)].nunique())
        invalid_codes = int((~code.str.match(r"^\d{6}$", na=False)).sum())

    duplicate_keys = np.nan
    keys = [c for c in [date_col, code_col] if c and c in df.columns]
    if "fiscal_year" in df.columns:
        keys.append("fiscal_year")
    if keys:
        duplicate_keys = int(df.duplicated(keys).sum())

    missing_rate = float(df.isna().mean().mean()) if cols else np.nan
    all_null_cols = [c for c in df.columns if df[c].isna().all()]

    summary = {
        "dataset": name,
        "path": str(path),
        "rows": rows,
        "columns": cols,
        "date_min": None if pd.isna(date_min) else date_min.strftime("%Y-%m-%d"),
        "date_max": None if pd.isna(date_max) else date_max.strftime("%Y-%m-%d"),
        "invalid_dates": invalid_dates,
        "stock_count": stock_count,
        "invalid_codes": invalid_codes,
        "duplicate_key_rows": duplicate_keys,
        "overall_missing_rate": missing_rate,
        "all_null_columns": json.dumps(all_null_cols, ensure_ascii=False),
    }

    column_rows = []
    for col in df.columns:
        s = df[col]
        col_row = {
            "dataset": name,
            "column": col,
            "dtype": str(s.dtype),
            "missing_count": int(s.isna().sum()),
            "missing_rate": float(s.isna().mean()),
            "nunique": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            col_row.update(
                {
                    "min": float(s.min()) if s.notna().any() else np.nan,
                    "max": float(s.max()) if s.notna().any() else np.nan,
                }
            )
        column_rows.append(col_row)

    return summary, column_rows


def load_datasets() -> list[tuple[str, Path, pd.DataFrame, str | None, str | None]]:
    datasets = []

    csv_specs = [
        ("kodex_ai_power_pdf_history", PDF_HISTORY_FILE, {"date": str, "stock_code": str, "etf_code": str}, "date", "stock_code"),
        ("kodex_ai_power_weights_pivot", PDF_WEIGHTS_PIVOT_FILE, {"date": str}, "date", None),
        ("etf_daily_market_data", ETF_DAILY_FILE, {"date": str, "etf_code": str}, "date", "etf_code"),
        ("price_long", PRICE_LONG_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
        ("consensus_long", CONSENSUS_LONG_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
        ("consensus_fy_panel", CONSENSUS_FY_PANEL_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
        ("target_rating_long", TARGET_RATING_LONG_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
        ("model_panel", MODEL_PANEL_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
        ("model_panel_monthly", MODEL_PANEL_MONTHLY_FILE, {"date": str, "stock_code": str}, "date", "stock_code"),
    ]

    for name, path, dtype, date_col, code_col in csv_specs:
        if path.exists():
            datasets.append((name, path, pd.read_csv(path, dtype=dtype, low_memory=False), date_col, code_col))

    if PRICE_FILE.exists():
        datasets.append(("fnguide_price_xlsx_parsed", PRICE_FILE, parse_fnguide_wide_xlsx(PRICE_FILE), "date", "stock_code"))

    for fy in [2024, 2025, 2026, 2027]:
        matches = [
            p
            for p in sorted(INPUT_DIR.glob(f"*{str(fy)[-2:]}E.xlsx")) + sorted(INPUT_DIR.glob(f"*{fy}E.xlsx"))
            if valid_excel_input(p)
        ]
        if matches:
            datasets.append(
                (
                    f"fnguide_consensus_{fy}E_xlsx_parsed",
                    matches[0],
                    parse_fnguide_wide_xlsx(matches[0], fiscal_year=fy),
                    "date",
                    "stock_code",
                )
            )

    target_matches = [p for p in INPUT_DIR.glob("*.xlsx") if valid_excel_input(p) and "목표" in p.name and "투자" in p.name]
    if target_matches:
        datasets.append(
            (
                "fnguide_target_rating_xlsx_parsed",
                target_matches[0],
                parse_fnguide_wide_xlsx(target_matches[0]),
                "date",
                "stock_code",
            )
        )

    if INDEX_DAILY_FILE.exists():
        datasets.append(("iselect_index_daily_html_xls", INDEX_DAILY_FILE, read_index_html_xls(INDEX_DAILY_FILE), "date", None))

    return datasets


def write_markdown_report(summary: pd.DataFrame) -> None:
    lines = [
        "# Data Validation Report",
        "",
        f"- Backtest start: `{BACKTEST_START}`",
        "- Stock codes are normalized to six-digit strings in the validation and backtest code.",
        "- Dates are parsed as pandas datetime internally and written as `YYYY-MM-DD` in new outputs.",
        "",
        "## Dataset Summary",
        "",
        summary.to_markdown(index=False),
        "",
        "## Methodology Limits Confirmed From Provided PDFs",
        "",
        "- The iSelect methodology uses NLP keyword filtering plus qualitative review to select AI power equipment related companies.",
        "- Final index weights are free-float market-cap weighted with a 20% ceiling applied at rebalance.",
        "- The document states the free-float ratio is calculated internally by NH Investment & Securities.",
        "- Regular reconstitution is every June and December on the first business day of the week after options expiry.",
        "- The corporate action methodology adjusts base/comparison market cap for non-price capital events.",
        "- With the current files, the internal NLP score, committee decisions, official NH free-float ratios, and full corporate-action event history are not available. They cannot be fully reproduced without additional data.",
        "- This project therefore uses observed KRX PDF holdings as the realized ETF basket and FnGuide float shares/float ratios as proxies for cap20 replication.",
    ]
    (OUTPUT_DIR / "data_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_validation() -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_output_dir()
    summaries = []
    columns = []
    for name, path, df, date_col, code_col in load_datasets():
        summary, column_rows = profile_dataframe(name, path, df, date_col, code_col)
        summaries.append(summary)
        columns.extend(column_rows)

    summary_df = pd.DataFrame(summaries)
    column_df = pd.DataFrame(columns)
    summary_df.to_csv(OUTPUT_DIR / "data_validation_summary.csv", index=False, encoding="utf-8-sig")
    column_df.to_csv(OUTPUT_DIR / "data_column_profile.csv", index=False, encoding="utf-8-sig")
    write_markdown_report(summary_df)
    return summary_df, column_df


if __name__ == "__main__":
    run_validation()
