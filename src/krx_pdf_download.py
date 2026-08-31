import os
import time
import requests
import pandas as pd
from pathlib import Path
from urllib.parse import urlencode

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUT_PATH = INPUT_DIR / "kodex_ai_power_pdf_history.csv"

URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

# 추천: 쿠키를 코드에 직접 쓰지 말고 환경변수로 넣기
# 터미널에서 먼저:
# export KRX_COOKIE='lang=ko_KR; JSESSIONID=...; mdc.client_session=true'
COOKIE_STRING = os.getenv("KRX_COOKIE", "").strip()

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://data.krx.co.kr",
    "referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201030108",
    "user-agent": "Mozilla/5.0",
    "x-requested-with": "XMLHttpRequest",
    "cookie": COOKIE_STRING,
}

BASE_PAYLOAD = {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT05001",
    "locale": "ko_KR",
    "tboxisuCd_finder_secuprodisu1_0": "487240/KODEX AI전력핵심설비",
    "isuCd": "KR7487240004",
    "isuCd2": "KR7152100004",
    "codeNmisuCd_finder_secuprodisu1_0": "KODEX AI전력핵심설비",
    "param1isuCd_finder_secuprodisu1_0": "",
    "share": "1",
    "money": "1",
    "csvxls_isNo": "false",
}

RENAME_MAP = {
    "COMPST_ISU_CD": "stock_code",
    "COMPST_ISU_CD2": "stock_isin",
    "MKT_ID": "market_id",
    "SECUGRP_ID": "security_group",
    "COMPST_ISU_NM": "stock_name",
    "COMPST_ISU_CU1_SHRS": "cu1_shares",
    "VALU_AMT": "valuation_amount",
    "COMPST_AMT": "composition_amount",
    "COMPST_RTO": "weight_pct",
}

NUMERIC_COLS = [
    "cu1_shares",
    "valuation_amount",
    "composition_amount",
    "weight_pct",
]

def is_valid_pdf_day(df):
    """
    KRX가 휴장일에 반환하는 원화현금 100%, 주식비중 0%짜리 데이터를 걸러냅니다.
    """
    if df.empty:
        return False

    tmp = df.rename(columns=RENAME_MAP).copy()

    if "stock_name" not in tmp.columns or "weight_pct" not in tmp.columns:
        return False

    tmp["weight_pct"] = (
        tmp["weight_pct"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    tmp["weight_pct"] = pd.to_numeric(tmp["weight_pct"], errors="coerce").fillna(0)

    stock_name = tmp["stock_name"].astype(str)

    is_cash = stock_name.str.contains("원화현금", na=False)

    stock_weight_sum = tmp.loc[~is_cash, "weight_pct"].sum()
    cash_weight_sum = tmp.loc[is_cash, "weight_pct"].sum()

    # 휴장일/비정상 데이터: 주식 비중이 0에 가깝고 현금만 100인 경우
    if stock_weight_sum < 50:
        return False

    if cash_weight_sum >= 50:
        return False

    return True

def fetch_one_day(session, yyyymmdd):
    payload = BASE_PAYLOAD.copy()
    payload["trdDd"] = yyyymmdd

    body = urlencode(payload, encoding="utf-8")

    r = session.post(
        URL,
        headers=HEADERS,
        data=body.encode("utf-8"),
        timeout=20,
    )
    r.raise_for_status()

    data = r.json()
    rows = data.get("output", [])

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "date", yyyymmdd)
    df.insert(1, "etf_code", "487240")
    df.insert(2, "etf_name", "KODEX AI전력핵심설비")

    # 휴장일/비정상 PDF 데이터 제거
    if not is_valid_pdf_day(df):
        print(f"{yyyymmdd}: 휴장일 또는 비정상 PDF 데이터로 판단되어 제외")
        return pd.DataFrame()

    return df


def clean_result(result):
    result = result.rename(columns=RENAME_MAP)

    for col in NUMERIC_COLS:
        if col in result.columns:
            result[col] = (
                result[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.strip()
                .replace({"": None, "-": None, "nan": None, "None": None})
            )
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "date" not in result.columns:
        raise ValueError(f"PDF 응답 정리 후 date 컬럼이 없습니다. 현재 컬럼: {list(result.columns)}")

    result["date"] = result["date"].astype(str)
    if "stock_code" in result.columns:
        stock_code = result["stock_code"].astype(str).str.strip()
        is_cash = stock_code.str.startswith("KRD", na=False)
        result["stock_code"] = stock_code.where(is_cash, stock_code.str.zfill(6))

    return result


def get_start_date():
    if not OUT_PATH.exists():
        # 파일이 없으면 처음 시작일
        return "20240709"

    old = pd.read_csv(OUT_PATH, dtype={"date": str, "stock_code": str})

    if old.empty:
        return "20240709"

    if "date" not in old.columns:
        raise ValueError(f"기존 파일에 date 컬럼이 없습니다: {OUT_PATH} / 컬럼={list(old.columns)}")

    last_date = old["date"].max()
    next_date = pd.to_datetime(last_date) + pd.Timedelta(days=1)

    return next_date.strftime("%Y%m%d")


def main():
    if not COOKIE_STRING:
        raise ValueError("KRX_COOKIE 환경변수가 비어 있습니다. 로그인 쿠키를 먼저 설정하세요.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    start_date = get_start_date()
    end_date = pd.Timestamp.today().strftime("%Y%m%d")

    print(f"업데이트 범위: {start_date} ~ {end_date}")

    dates = pd.date_range(start_date, end_date, freq="B")
    frames = []

    with requests.Session() as session:
        for d in dates:
            yyyymmdd = d.strftime("%Y%m%d")

            try:
                df = fetch_one_day(session, yyyymmdd)

                if df.empty:
                    print(f"{yyyymmdd}: 데이터 없음")
                else:
                    frames.append(df)
                    print(f"{yyyymmdd}: {len(df)}행 수집")

                time.sleep(0.5)

            except Exception as e:
                print(f"{yyyymmdd}: 실패 - {e}")
                time.sleep(3)

    if not frames:
        print("새로 추가할 데이터가 없습니다.")
        return

    new_data = pd.concat(frames, ignore_index=True)
    new_data = clean_result(new_data)

    if OUT_PATH.exists():
        old_data = pd.read_csv(
            OUT_PATH,
            dtype={
                "date": str,
                "stock_code": str,
            },
        )
        combined = pd.concat([old_data, new_data], ignore_index=True)
    else:
        combined = new_data

    # 같은 날짜, 같은 종목이 중복 저장되지 않도록 제거
    if "stock_code" in combined.columns:
        combined = combined.drop_duplicates(
            subset=["date", "stock_code"],
            keep="last",
        )
    else:
        combined = combined.drop_duplicates(keep="last")

    sort_cols = ["date"] + (["stock_code"] if "stock_code" in combined.columns else [])
    combined = combined.sort_values(sort_cols)

    combined.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"완료: {OUT_PATH.resolve()}")
    print(f"전체 행 수: {len(combined):,}")
    print(f"마지막 날짜: {combined['date'].max()}")

    # history CSV에 새 데이터가 추가된 경우에만 pivot 파일도 업데이트
    try:
        from update_weights_pivot import update_weights_pivot

        print("\n비중 pivot 파일 업데이트를 시작합니다.")
        update_weights_pivot()

    except Exception as e:
        print(f"비중 pivot 파일 업데이트 실패: {e}")


if __name__ == "__main__":
    main()
