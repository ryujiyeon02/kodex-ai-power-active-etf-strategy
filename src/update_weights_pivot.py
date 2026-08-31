import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"

INPUT_PATH = INPUT_DIR / "kodex_ai_power_pdf_history.csv"
OUTPUT_PATH = INPUT_DIR / "kodex_ai_power_weights_pivot.csv"


def update_weights_pivot():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not INPUT_PATH.exists():
        print(f"원본 파일이 없습니다: {INPUT_PATH}")
        return False

    df = pd.read_csv(
        INPUT_PATH,
        dtype={
            "date": str,
            "stock_code": str,
            "stock_name": str,
        },
    )

    if df.empty:
        print("원본 CSV가 비어 있습니다.")
        return False

    required_cols = {"date", "stock_name", "weight_pct"}
    missing = required_cols - set(df.columns)

    if missing:
        print(f"필수 컬럼이 없습니다: {missing}")
        print("현재 컬럼:", list(df.columns))
        return False

    df["date"] = df["date"].astype(str)

    df["weight_pct"] = (
        df["weight_pct"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["weight_pct"] = pd.to_numeric(df["weight_pct"], errors="coerce")

    df = df.dropna(subset=["date", "stock_name", "weight_pct"])

    weights = df.pivot_table(
        index="date",
        columns="stock_name",
        values="weight_pct",
        aggfunc="sum",
    ).fillna(0)

    weights = weights.sort_index()

    # 컬럼 순서를 최근일 비중 큰 순서로 정렬
    latest_date = weights.index.max()
    latest_weights = weights.loc[latest_date].sort_values(ascending=False)
    weights = weights[latest_weights.index]

    weights.to_csv(OUTPUT_PATH, encoding="utf-8-sig")

    print(f"완료: {OUTPUT_PATH.resolve()}")
    print(f"날짜 수: {weights.shape[0]}")
    print(f"종목 수: {weights.shape[1]}")
    print(f"마지막 날짜: {latest_date}")
    print("\n최근일 비중:")
    print(latest_weights[latest_weights > 0])

    return True


if __name__ == "__main__":
    update_weights_pivot()
