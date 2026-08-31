from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

PRICE_FILE = INPUT_DIR / "2022_2026_price_data.xlsx"
COV_ADV_SUPPLEMENT_FILE = INPUT_DIR / "공분산추정,ADV용.xlsx"
ETF_DAILY_FILE = INPUT_DIR / "etf_daily_market_data.csv"
INDEX_DAILY_FILE = INPUT_DIR / "iSelect AI전력핵심설비 지수_지수일별데이터.xls"
PDF_HISTORY_FILE = INPUT_DIR / "kodex_ai_power_pdf_history.csv"
PDF_WEIGHTS_PIVOT_FILE = INPUT_DIR / "kodex_ai_power_weights_pivot.csv"

PRICE_LONG_FILE = OUTPUT_DIR / "price_long.csv"
CONSENSUS_LONG_FILE = OUTPUT_DIR / "consensus_long.csv"
CONSENSUS_FY_PANEL_FILE = OUTPUT_DIR / "consensus_fy_panel.csv"
TARGET_RATING_LONG_FILE = OUTPUT_DIR / "target_rating_long.csv"
MODEL_PANEL_FILE = OUTPUT_DIR / "model_panel.csv"
MODEL_PANEL_MONTHLY_FILE = OUTPUT_DIR / "model_panel_monthly.csv"

BACKTEST_START = "2024-07-09"
CASH_CODE = "KRD010010001"
CASH_NAME = "원화현금"


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
