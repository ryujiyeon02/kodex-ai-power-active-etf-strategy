import os
import time
from pathlib import Path

import pandas as pd
from pykrx_openapi import KRXOpenAPI


ETF_CODE = "487240"
ETF_NAME_KEYWORD = "AI전력핵심설비"

START_DATE = "20240709"
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUT_PATH = INPUT_DIR / "etf_daily_market_data.csv"


RENAME_MAP = {
    "BAS_DD": "date",
    "ISU_CD": "etf_code",
    "ISU_NM": "etf_name",
    "TDD_CLSPRC": "etf_close",
    "CMPPREVDD_PRC": "etf_change",
    "FLUC_RT": "etf_return_pct",
    "NAV": "nav",
    "TDD_OPNPRC": "etf_open",
    "TDD_HGPRC": "etf_high",
    "TDD_LWPRC": "etf_low",
    "ACC_TRDVOL": "etf_volume",
    "ACC_TRDVAL": "etf_trading_value",
    "MKTCAP": "etf_market_cap",
    "INVSTASST_NETASST_TOTAMT": "aum",
    "LIST_SHRS": "listed_shares",
    "IDX_IND_NM": "underlying_index_name",
    "OBJ_STKPRC_IDX": "underlying_index_close",
    "CMPPREVDD_IDX": "underlying_index_change",
    "FLUC_RT_IDX": "underlying_index_return_pct",
}


FINAL_COLS = [
    "date",
    "etf_code",
    "etf_name",
    "etf_close",
    "nav",
    "etf_volume",
    "etf_trading_value",
    "aum",
    "underlying_index_name",
    "underlying_index_close",
    "underlying_index_return_pct",
    "etf_return_pct",
    "etf_open",
    "etf_high",
    "etf_low",
    "etf_change",
    "underlying_index_change",
    "etf_market_cap",
    "listed_shares",
]


NUMERIC_COLS = [
    "etf_close",
    "nav",
    "etf_volume",
    "etf_trading_value",
    "aum",
    "underlying_index_close",
    "underlying_index_return_pct",
    "etf_return_pct",
    "etf_open",
    "etf_high",
    "etf_low",
    "etf_change",
    "underlying_index_change",
    "etf_market_cap",
    "listed_shares",
]


def get_start_date() -> str:
    """
    기존 CSV가 있으면 마지막 날짜 다음 날부터 업데이트합니다.
    없으면 START_DATE부터 시작합니다.
    """
    if not OUT_PATH.exists():
        return START_DATE

    old = pd.read_csv(OUT_PATH, dtype={"date": str, "etf_code": str})

    if old.empty:
        return START_DATE

    if "date" not in old.columns:
        raise ValueError(f"기존 파일에 date 컬럼이 없습니다: {OUT_PATH} / 컬럼={list(old.columns)}")

    old["date"] = clean_date_series(old["date"])
    last_date = old["date"].max()
    next_date = pd.to_datetime(last_date) + pd.Timedelta(days=1)

    return next_date.strftime("%Y%m%d")


def clean_number_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": None, "-": None, "nan": None, "None": None}),
        errors="coerce",
    )


def clean_date_series(s: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(s, errors="coerce")
    fallback = (
        s.astype(str)
        .str.replace("-", "", regex=False)
        .str.replace("/", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.slice(0, 8)
    )
    return parsed.dt.strftime("%Y%m%d").fillna(fallback)


def normalize_etf_data(raw_data) -> pd.DataFrame:
    """
    pykrx_openapi 응답을 DataFrame으로 바꾸고 필요한 컬럼명으로 정리합니다.
    """
    if raw_data is None:
        return pd.DataFrame()

    if isinstance(raw_data, pd.DataFrame):
        df = raw_data.copy()
    elif isinstance(raw_data, dict):
        df = pd.DataFrame(raw_data.get("OutBlock_1", []))
    else:
        df = pd.DataFrame(raw_data)

    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns=RENAME_MAP)

    required_cols = {"date", "etf_code"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(
            "API 응답에 필수 컬럼이 없습니다: "
            f"{', '.join(sorted(missing_cols))}. "
            f"실제 컬럼: {', '.join(map(str, df.columns))}"
        )

    if "date" in df.columns:
        df["date"] = clean_date_series(df["date"])

    if "etf_code" in df.columns:
        df["etf_code"] = df["etf_code"].astype(str).str.zfill(6)

    # 전체 ETF가 날짜별로 내려오기 때문에 487240만 필터링
    if "etf_code" in df.columns:
        df = df[df["etf_code"] == ETF_CODE].copy()
    elif "etf_name" in df.columns:
        df = df[df["etf_name"].astype(str).str.contains(ETF_NAME_KEYWORD, na=False)].copy()

    if df.empty:
        return pd.DataFrame()

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = clean_number_series(df[col])

    # 원하는 컬럼이 없을 수도 있으니 존재하는 것만 정렬
    existing_cols = [col for col in FINAL_COLS if col in df.columns]
    remaining_cols = [col for col in df.columns if col not in existing_cols]
    df = df[existing_cols + remaining_cols]

    return df


def fetch_one_day(client: KRXOpenAPI, yyyymmdd: str) -> pd.DataFrame:
    raw = client.get_etf_daily_trade(bas_dd=yyyymmdd)
    df = normalize_etf_data(raw)

    if df.empty:
        return pd.DataFrame()

    return df


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("KRX_OPENAPI_KEY", "").strip()

    if not api_key:
        raise ValueError(
            "KRX_OPENAPI_KEY 환경변수가 비어 있습니다. "
            "터미널에서 export KRX_OPENAPI_KEY='본인_API키'를 먼저 실행하세요."
        )

    client = KRXOpenAPI(
        api_key=api_key,
        rate_limit=5,
        per_seconds=1,
        timeout=30,
        debug=False,
    )

    start_date = get_start_date()
    end_date = pd.Timestamp.today().strftime("%Y%m%d")

    print(f"업데이트 범위: {start_date} ~ {end_date}")

    dates = pd.date_range(start_date, end_date, freq="B")
    frames = []

    for d in dates:
        yyyymmdd = d.strftime("%Y%m%d")

        try:
            df = fetch_one_day(client, yyyymmdd)

            if df.empty:
                print(f"{yyyymmdd}: 데이터 없음")
            else:
                frames.append(df)
                print(f"{yyyymmdd}: {len(df)}행 수집")

            time.sleep(0.2)

        except Exception as e:
            print(f"{yyyymmdd}: 실패 - {e}")
            time.sleep(1)

    if not frames:
        print("새로 추가할 ETF 일별매매정보가 없습니다.")
        return

    new_data = pd.concat(frames, ignore_index=True)

    if OUT_PATH.exists():
        old_data = pd.read_csv(OUT_PATH, dtype={"date": str, "etf_code": str})
        combined = pd.concat([old_data, new_data], ignore_index=True)
    else:
        combined = new_data

    required_cols = {"date", "etf_code"}
    missing_cols = required_cols - set(combined.columns)
    if missing_cols:
        raise ValueError(
            "저장 직전 데이터에 필수 컬럼이 없습니다: "
            f"{', '.join(sorted(missing_cols))}. 현재 컬럼: {list(combined.columns)}"
        )

    combined["date"] = clean_date_series(combined["date"])
    combined["etf_code"] = combined["etf_code"].astype(str).str.zfill(6)

    combined = combined.drop_duplicates(
        subset=["date", "etf_code"],
        keep="last",
    )

    combined = combined.sort_values(["date", "etf_code"])

    combined.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n완료: {OUT_PATH.resolve()}")
    print(f"전체 행 수: {len(combined):,}")
    print(f"마지막 날짜: {combined['date'].max()}")

    latest = combined[combined["date"] == combined["date"].max()]
    print("\n최근 데이터:")
    print(latest.T)


if __name__ == "__main__":
    main()
