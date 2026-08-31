from pathlib import Path
import re
import numpy as np
import pandas as pd

# =========================
# 0. 파일 경로 설정
# =========================
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / 'input'
OUTPUT_DIR = BASE_DIR / 'output'

PRICE_FILE = INPUT_DIR / '2022_2026_price_data.xlsx'
WEIGHTS_FILE = INPUT_DIR / 'kodex_ai_power_weights_pivot.csv'

BACKTEST_START = '2024-07-09'

OUT_PRICE_LONG = OUTPUT_DIR / 'price_long.csv'
OUT_CONSENSUS_LONG = OUTPUT_DIR / 'consensus_long.csv'
OUT_CONSENSUS_FY_PANEL = OUTPUT_DIR / 'consensus_fy_panel.csv'
OUT_TARGET_RATING_LONG = OUTPUT_DIR / 'target_rating_long.csv'
OUT_VALUE_FACTOR_LONG = OUTPUT_DIR / 'value_factor_long.csv'
OUT_MODEL_PANEL = OUTPUT_DIR / 'model_panel.csv'
OUT_PANEL_MONTHLY = OUTPUT_DIR / 'model_panel_monthly.csv'


def find_file_by_patterns(patterns):
    """파일명 한글 정규화 이슈까지 고려해서 파일을 찾습니다."""
    import unicodedata

    def valid_input_file(path: Path) -> bool:
        return path.is_file() and not path.name.startswith('~$')

    # 1차: 일반 glob
    for pattern in patterns:
        matches = sorted(f for f in INPUT_DIR.glob(pattern) if valid_input_file(f))
        if matches:
            return matches[0]

    # 2차: 한글 NFC 정규화 후 부분 문자열 매칭
    files = [f for f in INPUT_DIR.glob('*.xlsx') if valid_input_file(f)]
    for pattern in patterns:
        key = pattern.replace('*', '').replace('.xlsx', '')
        if not key:
            continue
        key_n = unicodedata.normalize('NFC', key).lower()
        for f in files:
            name_n = unicodedata.normalize('NFC', f.name).lower()
            if key_n in name_n:
                return f

    # 3차: 목표/투자 파일 특수 처리
    for f in files:
        name_n = unicodedata.normalize('NFC', f.name)
        if ('목표' in name_n) and ('투자' in name_n):
            return f

    return None

CONSENSUS_FILES = {
    2024: find_file_by_patterns(['*24E.xlsx', '*2024E.xlsx']),
    2025: find_file_by_patterns(['*25E.xlsx', '*2025E.xlsx']),
    2026: find_file_by_patterns(['*26E.xlsx', '*2026E.xlsx']),
    2027: find_file_by_patterns(['*27E.xlsx', '*2027E.xlsx']),
    2028: find_file_by_patterns(['*28E.xlsx', '*2028E.xlsx']),
}

TARGET_RATING_FILE = find_file_by_patterns([
    '*목표*투자*.xlsx',
    '*투자*목표*.xlsx',
    '*target*rating*.xlsx',
])

def find_value_factor_file() -> Path | None:
    """목표주가 파일 fallback 없이 진짜 value factor 파일만 찾습니다."""
    import unicodedata

    files = [f for f in INPUT_DIR.glob('*.xlsx') if f.is_file() and not f.name.startswith('~$')]
    for f in files:
        name = unicodedata.normalize('NFC', f.name).lower()
        if ('value' in name and 'factor' in name) or ('밸류' in name and '팩터' in name):
            return f
    return None


VALUE_FACTOR_FILE = find_value_factor_file()

# =========================
# 1. 공통 유틸
# =========================

def excel_serial_to_date(s: pd.Series) -> pd.Series:
    """FnGuide Excel 날짜 변환. 이미 datetime이면 그대로, serial이면 변환."""
    dt = pd.to_datetime(s, errors='coerce')
    # 숫자 serial만 들어온 경우 pd.to_datetime이 1970년대 나노초로 해석할 수 있어 보정
    if dt.notna().sum() == 0 or (dt.dropna().dt.year.lt(1990).all() if dt.notna().any() else False):
        num = pd.to_numeric(s, errors='coerce')
        dt = pd.to_datetime(num, unit='D', origin='1899-12-30', errors='coerce')
    return dt


def clean_code(x) -> str:
    """A010120, 10120, 010120 등을 6자리 종목코드로 정리."""
    if pd.isna(x):
        return None
    x = str(x).strip()
    x = re.sub(r'^A', '', x)
    x = re.sub(r'\.0$', '', x)
    x = re.sub(r'[^0-9]', '', x)
    if not x:
        return None
    return x.zfill(6)


def to_numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str)
         .str.replace(',', '', regex=False)
         .str.strip()
         .replace({'': np.nan, '-': np.nan, 'nan': np.nan, 'None': np.nan}),
        errors='coerce'
    )


def adjust_weight_pivot_cash_substitution(
    weights_wide: pd.DataFrame,
    cash_col: str = '원화현금',
    cash_spike_threshold_pct: float = 5.0,
    normal_cash_threshold_pct: float = 2.0,
    lookahead_rows: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    KRX PDF 피벗에서 기업이벤트/거래정지 종목이 일시적으로 원화현금으로
    대체 표시된 구간을 보정합니다. 비정상 현금 중 정상 현금 수준을 초과한
    부분만 직전/직후에 존재하는 임시 0% 종목으로 되돌립니다.
    """
    if weights_wide.empty or cash_col not in weights_wide.columns:
        return weights_wide.copy(), pd.DataFrame()

    w = weights_wide.copy()
    value_cols = [c for c in w.columns if c != 'date']
    for col in value_cols:
        w[col] = to_numeric_series(w[col])
    w = w.sort_values('date').reset_index(drop=True)

    cash = w[cash_col].fillna(0.0)
    normal_cash = cash[cash <= normal_cash_threshold_pct].median()
    if not np.isfinite(normal_cash):
        normal_cash = 0.0

    stock_cols = [c for c in value_cols if c != cash_col]
    audit_rows = []
    for pos, row in w.iterrows():
        original_cash = float(row.get(cash_col, 0.0) or 0.0)
        excess_cash = original_cash - float(normal_cash)
        if excess_cash <= cash_spike_threshold_pct:
            continue

        if pos == 0:
            continue
        future = w.loc[pos + 1 : pos + lookahead_rows, stock_cols]
        if future.empty:
            continue

        prev = w.loc[pos - 1, stock_cols].fillna(0.0)
        current = w.loc[pos, stock_cols].fillna(0.0)
        future_max = future.max(axis=0).fillna(0.0)
        candidate_mask = (
            (prev > normal_cash_threshold_pct)
            & (current <= 1e-10)
            & (future_max > normal_cash_threshold_pct)
        )
        candidates = candidate_mask[candidate_mask].index.tolist()
        if not candidates:
            continue

        prev_weights = prev[candidates].astype(float)
        denom = float(prev_weights.sum())
        if denom <= 0:
            continue

        adjusted_cash = max(0.0, float(normal_cash))
        w.at[pos, cash_col] = adjusted_cash
        for stock_name, prev_weight in prev_weights.items():
            original_stock = float(current.get(stock_name, 0.0))
            transferred = excess_cash * float(prev_weight) / denom
            w.at[pos, stock_name] = original_stock + transferred
            audit_rows.append({
                'date': row['date'],
                'stock_name': stock_name,
                'original_cash_weight_pct': original_cash,
                'adjusted_cash_weight_pct': adjusted_cash,
                'original_stock_weight_pct': original_stock,
                'adjusted_stock_weight_pct': float(w.at[pos, stock_name]),
                'transferred_weight_pct': transferred,
                'reason': 'cash_substitution_for_temporary_zero_weight',
            })

    return w, pd.DataFrame(audit_rows)


def standardize_item_name(item: str) -> str:
    """FnGuide 항목명을 영문 컬럼명으로 매핑."""
    item = str(item).strip()
    mapping = {
        # 가격/거래/유동시총
        '종가(원)': 'close',
        '수정주가(원)': 'adj_close',
        '거래량(주)': 'volume',
        '거래대금(원)': 'trading_value',
        '시가총액(백만원)': 'market_cap_mn',
        '유동주식수(주)': 'float_shares',
        '유동주식비율(%)': 'float_ratio_pct',

        # 실적 컨센서스
        '매출액(억원)': 'sales_e',
        '영업이익(억원)': 'op_e',
        '당기순이익(억원)': 'ni_e',
        '순이익(억원)': 'ni_e',
        'EPS(지배)(원)': 'eps_e',
        'EPS(원)': 'eps_e',
        '추정기관수': 'analyst_count',
        '최근기업리포트발간일': 'latest_report_date',

        # 목표주가/투자의견 컨센서스
        '투자의견(포인트)': 'rating_point',
        '투자의견상향수': 'rating_up_count',
        '투자의견하향수': 'rating_down_count',
        '투자의견유지수': 'rating_maintain_count',
        '투자의견신규수': 'rating_new_count',
        '투자의견전체수': 'rating_total_count',
        '목표주가(원)': 'target_price',
        '목표주가(최고)(원)': 'target_price_high',
        '목표주가(최저)(원)': 'target_price_low',
        '목표주가(중앙값)(원)': 'target_price_median',
        '목표주가괴리율(%)': 'target_gap_pct',
        '목표주가표준편차': 'target_price_std',
        '목표주가CV': 'target_price_cv',
        '목표주가상향수': 'target_up_count',
        '목표주가하향수': 'target_down_count',
        '목표주가전체수': 'target_total_count',

        # 밸류에이션/배당 팩터
        '현금배당액(전체)(천원)': 'cash_dividend_total_thousand_krw',
        'DPS(보통주, 현금)(원)': 'dps_common_cash_krw',
        'PER(IFRS-연결)': 'per_ifrs_consolidated',
        'PBR(IFRS-연결)': 'pbr_ifrs_consolidated',
        'PSR(IFRS-연결)': 'psr_ifrs_consolidated',
        '배당수익률(IFRS-연결)': 'dividend_yield_pct',
        'EV/EBITDA(배)': 'ev_ebitda',
    }
    return mapping.get(item, item)

# =========================
# 2. FnGuide wide 포맷 파서
# =========================

def parse_fnguide_wide_xlsx(path: Path, fiscal_year: int | None = None) -> pd.DataFrame:
    """
    FnGuide Excel Builder 형태 파일을 long/panel 형태로 변환.
    구조 가정:
    - 9행: 코드
    - 10행: 코드명
    - 13행: 아이템명
    - 15행부터 날짜별 데이터
    """
    if path is None or not path.exists():
        raise FileNotFoundError(f'파일을 찾을 수 없습니다: {path}')

    raw = pd.read_excel(path, sheet_name=0, header=None, engine='openpyxl')

    code_row = raw.iloc[8, 1:]
    name_row = raw.iloc[9, 1:]
    item_row = raw.iloc[12, 1:]
    data = raw.iloc[14:, :].copy()
    data = data.dropna(how='all')

    dates = excel_serial_to_date(data.iloc[:, 0])
    values = data.iloc[:, 1:].copy()

    meta = pd.DataFrame({
        'stock_code': [clean_code(x) for x in code_row],
        'stock_name': list(name_row),
        'item_raw': list(item_row),
        'item': [standardize_item_name(x) for x in item_row],
    })

    # 빈 열 제거
    valid_cols = meta['stock_code'].notna() & meta['item'].notna()
    meta = meta.loc[valid_cols].reset_index(drop=True)
    values = values.loc[:, valid_cols.values]

    pieces = []
    for j, m in meta.iterrows():
        tmp = pd.DataFrame({
            'date': dates.values,
            'stock_code': m['stock_code'],
            'stock_name': m['stock_name'],
            'item': m['item'],
            'value': values.iloc[:, j].values,
        })
        pieces.append(tmp)
    long = pd.concat(pieces, ignore_index=True)
    long = long.dropna(subset=['date'])

    panel = long.pivot_table(
        index=['date', 'stock_code', 'stock_name'],
        columns='item',
        values='value',
        aggfunc='first'
    ).reset_index()
    panel.columns.name = None

    if fiscal_year is not None:
        panel['fiscal_year'] = fiscal_year

    # 날짜/문자열 컬럼 외 숫자 정리
    non_numeric_cols = {'date', 'stock_code', 'stock_name', 'fiscal_year', 'latest_report_date'}
    for col in panel.columns:
        if col not in non_numeric_cols:
            panel[col] = to_numeric_series(panel[col])

    # 리포트 발간일이 Excel serial인 경우 변환
    if 'latest_report_date' in panel.columns:
        report_raw = panel['latest_report_date']
        report_str = report_raw.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        yyyymmdd = pd.to_datetime(report_str, format='%Y%m%d', errors='coerce')
        report_num = pd.to_numeric(report_raw, errors='coerce')
        serial_mask = report_num.between(20000, 60000)
        serial = pd.Series(pd.NaT, index=panel.index, dtype='datetime64[ns]')
        serial.loc[serial_mask] = pd.to_datetime(
            report_num.loc[serial_mask],
            unit='D',
            origin='1899-12-30',
            errors='coerce',
        )
        panel['latest_report_date'] = yyyymmdd.fillna(serial)

    return panel


def build_consensus_fy_panel(consensus: pd.DataFrame, max_offset: int = 3) -> pd.DataFrame:
    """
    fiscal_year별 long 컨센서스를 날짜 기준 FY0/FY1/FY2 형태로 펼칩니다.

    FY0 = 해당 날짜가 속한 calendar year의 결산연도 예상치
    FY1 = 다음 결산연도 예상치
    FY2 = 2년 뒤 결산연도 예상치

    발표/리포트에서는 FY0/FY1/FY2보다 명확한 alias도 함께 제공합니다.
    current_year = FY0, next_year = FY1, year_after_next = FY2 입니다.
    """
    if consensus.empty:
        return pd.DataFrame()

    con = consensus.copy()
    con['date'] = pd.to_datetime(con['date'], errors='coerce')
    con['fiscal_year'] = pd.to_numeric(con['fiscal_year'], errors='coerce')
    con = con.dropna(subset=['date', 'stock_code', 'fiscal_year'])
    con['fiscal_year'] = con['fiscal_year'].astype(int)
    con['stock_code'] = con['stock_code'].astype(str).str.zfill(6)
    con['fy_offset'] = con['fiscal_year'] - con['date'].dt.year
    con = con[(con['fy_offset'] >= 0) & (con['fy_offset'] <= max_offset)].copy()
    if con.empty:
        return pd.DataFrame()

    value_cols = [
        col for col in ['sales_e', 'op_e', 'ni_e', 'eps_e', 'analyst_count', 'latest_report_date']
        if col in con.columns
    ]
    base = con[['date', 'stock_code']].drop_duplicates().sort_values(['date', 'stock_code'])
    out = base.copy()
    for offset in sorted(con['fy_offset'].dropna().unique()):
        offset = int(offset)
        tmp_cols = ['date', 'stock_code', 'fiscal_year'] + value_cols
        tmp = con.loc[con['fy_offset'] == offset, tmp_cols].copy()
        rename = {'fiscal_year': f'fiscal_year_fy{offset}'}
        rename.update({col: f"{col.replace('_e', '')}_fy{offset}" for col in value_cols})
        tmp = tmp.rename(columns=rename)
        out = out.merge(tmp, on=['date', 'stock_code'], how='left')

    for metric in ['sales', 'op', 'ni', 'eps']:
        for left, right in [(0, 1), (1, 2), (0, 2)]:
            near_col = f'{metric}_fy{left}'
            next_col = f'{metric}_fy{right}'
            if {near_col, next_col}.issubset(out.columns):
                out[f'{metric}_growth_fy{right}_vs_fy{left}'] = (
                    out[next_col] - out[near_col]
                ) / out[near_col].abs().replace(0, np.nan)
                out[f'{metric}_spread_fy{right}_minus_fy{left}'] = out[next_col] - out[near_col]

    out['fy0'] = out['date'].dt.year
    out['fy1'] = out['fy0'] + 1
    out['fy2'] = out['fy0'] + 2

    out['current_year'] = out['fy0'].astype(str) + 'E'
    out['next_year'] = out['fy1'].astype(str) + 'E'
    out['year_after_next'] = out['fy2'].astype(str) + 'E'

    alias_map = {
        'sales_current_year_e': 'sales_fy0',
        'op_current_year_e': 'op_fy0',
        'ni_current_year_e': 'ni_fy0',
        'eps_current_year_e': 'eps_fy0',
        'sales_next_year_e': 'sales_fy1',
        'op_next_year_e': 'op_fy1',
        'ni_next_year_e': 'ni_fy1',
        'eps_next_year_e': 'eps_fy1',
        'sales_year_after_next_e': 'sales_fy2',
        'op_year_after_next_e': 'op_fy2',
        'ni_year_after_next_e': 'ni_fy2',
        'eps_year_after_next_e': 'eps_fy2',
        'sales_next_year_growth': 'sales_growth_fy1_vs_fy0',
        'op_next_year_growth': 'op_growth_fy1_vs_fy0',
        'ni_next_year_growth': 'ni_growth_fy1_vs_fy0',
        'eps_next_year_growth': 'eps_growth_fy1_vs_fy0',
        'sales_year_after_next_growth': 'sales_growth_fy2_vs_fy1',
        'op_year_after_next_growth': 'op_growth_fy2_vs_fy1',
        'ni_year_after_next_growth': 'ni_growth_fy2_vs_fy1',
        'eps_year_after_next_growth': 'eps_growth_fy2_vs_fy1',
        'eps_two_year_growth': 'eps_growth_fy2_vs_fy0',
        'op_two_year_growth': 'op_growth_fy2_vs_fy0',
    }
    for alias, source_col in alias_map.items():
        if source_col in out.columns:
            out[alias] = out[source_col]
    return out.sort_values(['stock_code', 'date'])

# =========================
# 3. ETF 비중 파일 파서
# =========================

def load_weights_pivot(path: Path) -> pd.DataFrame:
    """kodex_ai_power_weights_pivot.csv를 long 형태로 변환."""
    if not path.exists():
        print(f'[경고] ETF 비중 파일이 없습니다: {path}')
        return pd.DataFrame(columns=['date', 'stock_name', 'etf_weight_pct'])

    w = pd.read_csv(path)
    first_col = w.columns[0]
    w = w.rename(columns={first_col: 'date'})
    w['date'] = pd.to_datetime(w['date'].astype(str), errors='coerce')
    w, adjustment_audit = adjust_weight_pivot_cash_substitution(w)
    if not adjustment_audit.empty:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        adjustment_audit.to_csv(
            OUTPUT_DIR / 'model_panel_pdf_weight_event_adjustment_audit.csv',
            index=False,
            encoding='utf-8-sig',
        )

    long = w.melt(id_vars='date', var_name='stock_name', value_name='etf_weight_pct')
    long['etf_weight_pct'] = to_numeric_series(long['etf_weight_pct'])
    long = long.dropna(subset=['date'])
    return long

# =========================
# 4. 20% cap 함수
# =========================

def apply_cap(weights: pd.Series, cap: float = 0.20, tol: float = 1e-12) -> pd.Series:
    """
    raw weight에 cap을 반복 적용.
    입력과 출력은 decimal weight. 예: 0.2 = 20%.
    """
    w = weights.astype(float).copy().fillna(0.0)
    total = w.sum()
    if total <= 0:
        return w * np.nan
    w = w / total

    capped = pd.Series(False, index=w.index)
    result = w.copy()

    for _ in range(100):
        over = (result > cap + tol) & (~capped)
        if not over.any():
            break
        capped = capped | over
        result.loc[capped] = cap
        remaining = 1.0 - result.loc[capped].sum()
        uncapped = ~capped
        if remaining <= 0 or result.loc[uncapped].sum() <= 0:
            result.loc[uncapped] = 0.0
            break
        result.loc[uncapped] = result.loc[uncapped] / result.loc[uncapped].sum() * remaining

    s = result.sum()
    if s > 0:
        result = result / s
    return result

# =========================
# 5. 패널 생성
# =========================

def build_panel():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print('1) 가격/유동시총 데이터 파싱 중...')
    price = parse_fnguide_wide_xlsx(PRICE_FILE)
    price = price.sort_values(['stock_code', 'date'])

    required_price_cols = ['close', 'adj_close', 'trading_value', 'market_cap_mn', 'float_shares']
    missing = [c for c in required_price_cols if c not in price.columns]
    if missing:
        print('[주의] 가격 파일에 없는 주요 컬럼:', missing)

    price['return'] = price.groupby('stock_code')['adj_close'].pct_change()
    price['float_mktcap'] = price['close'] * price['float_shares']
    if 'market_cap_mn' in price.columns:
        price['market_cap'] = price['market_cap_mn'] * 1_000_000
        price['float_mktcap_check_ratio'] = price['float_mktcap'] / price['market_cap']

    price['momentum_20d'] = price.groupby('stock_code')['adj_close'].pct_change(20)
    price['momentum_60d'] = price.groupby('stock_code')['adj_close'].pct_change(60)
    price['vol_20d_ann'] = (
        price.groupby('stock_code')['return']
             .rolling(20)
             .std()
             .reset_index(level=0, drop=True)
        * np.sqrt(252)
    )

    price['raw_float_weight'] = price.groupby('date')['float_mktcap'].transform(lambda x: x / x.sum())
    price['cap20_weight'] = price.groupby('date', group_keys=False)['raw_float_weight'].apply(apply_cap)
    price['raw_float_weight_pct'] = price['raw_float_weight'] * 100
    price['cap20_weight_pct'] = price['cap20_weight'] * 100

    price.to_csv(OUT_PRICE_LONG, index=False, encoding='utf-8-sig')
    print(f'   저장: {OUT_PRICE_LONG}')

    print('2) 실적 컨센서스 데이터 파싱 중...')
    consensus_frames = []
    for fy, path in CONSENSUS_FILES.items():
        if path is not None and path.exists():
            c = parse_fnguide_wide_xlsx(path, fiscal_year=fy)
            consensus_frames.append(c)
            print(f'   {fy}E: {len(c):,}행')
        else:
            print(f'   [경고] {fy}E 파일 없음')

    if consensus_frames:
        consensus = pd.concat(consensus_frames, ignore_index=True)
        consensus = consensus.sort_values(['stock_code', 'fiscal_year', 'date'])
        consensus.to_csv(OUT_CONSENSUS_LONG, index=False, encoding='utf-8-sig')
        print(f'   저장: {OUT_CONSENSUS_LONG}')
        consensus_fy_panel = build_consensus_fy_panel(consensus)
        consensus_fy_panel.to_csv(OUT_CONSENSUS_FY_PANEL, index=False, encoding='utf-8-sig')
        print(f'   FY0/FY1 정리본 저장: {OUT_CONSENSUS_FY_PANEL}')
    else:
        consensus = pd.DataFrame()
        consensus_fy_panel = pd.DataFrame()
        print('   실적 컨센서스 파일이 없어 병합은 생략합니다.')

    print('3) 목표주가/투자의견 컨센서스 데이터 파싱 중...')
    if TARGET_RATING_FILE is not None and TARGET_RATING_FILE.exists():
        target_rating = parse_fnguide_wide_xlsx(TARGET_RATING_FILE)
        target_rating = target_rating.sort_values(['stock_code', 'date'])
        # 파생 변수
        if 'target_gap_pct' in target_rating.columns:
            target_rating['target_upside'] = target_rating['target_gap_pct'] / 100.0
        if {'target_up_count', 'target_down_count', 'target_total_count'}.issubset(target_rating.columns):
            denom = target_rating['target_total_count'].replace(0, np.nan)
            target_rating['target_revision_balance'] = (
                target_rating['target_up_count'] - target_rating['target_down_count']
            ) / denom
        if {'rating_up_count', 'rating_down_count', 'rating_total_count'}.issubset(target_rating.columns):
            denom = target_rating['rating_total_count'].replace(0, np.nan)
            target_rating['rating_revision_balance'] = (
                target_rating['rating_up_count'] - target_rating['rating_down_count']
            ) / denom
        if {'target_total_count', 'target_price_cv'}.issubset(target_rating.columns):
            target_rating['target_confidence'] = target_rating['target_total_count'] / (1.0 + target_rating['target_price_cv'].fillna(0))

        target_rating.to_csv(OUT_TARGET_RATING_LONG, index=False, encoding='utf-8-sig')
        print(f'   저장: {OUT_TARGET_RATING_LONG}')
        print(f'   목표주가/투자의견 행 수: {len(target_rating):,}')
    else:
        target_rating = pd.DataFrame()
        print('   목표주가/투자의견 파일이 없어 병합은 생략합니다.')

    print('3-1) 밸류에이션 팩터 데이터 파싱 중...')
    if VALUE_FACTOR_FILE is not None and VALUE_FACTOR_FILE.exists():
        value_factor = parse_fnguide_wide_xlsx(VALUE_FACTOR_FILE)
        value_factor = value_factor.sort_values(['stock_code', 'date'])
        value_factor.to_csv(OUT_VALUE_FACTOR_LONG, index=False, encoding='utf-8-sig')
        print(f'   저장: {OUT_VALUE_FACTOR_LONG}')
        print(f'   밸류에이션 팩터 행 수: {len(value_factor):,}')
    else:
        value_factor = pd.DataFrame()
        print('   밸류에이션 팩터 파일이 없어 병합은 생략합니다.')

    print('4) ETF PDF 비중 병합 중...')
    weights = load_weights_pivot(WEIGHTS_FILE)

    panel = price[price['date'] >= pd.to_datetime(BACKTEST_START)].copy()

    if not weights.empty:
        panel = panel.merge(weights, on=['date', 'stock_name'], how='left')
    else:
        panel['etf_weight_pct'] = np.nan

    panel = panel.sort_values(['stock_code', 'date'])
    panel['etf_weight_lag1_pct'] = panel.groupby('stock_code')['etf_weight_pct'].shift(1)

    print('5) FY0/FY1 실적 컨센서스 병합 중...')
    if not consensus_fy_panel.empty:
        merge_cols = [c for c in consensus_fy_panel.columns if c != 'stock_name']
        panel = panel.merge(consensus_fy_panel[merge_cols], on=['date', 'stock_code'], how='left')

        panel = panel.sort_values(['stock_code', 'date'])
        panel['op_fy0_3m_ago'] = panel.groupby('stock_code')['op_fy0'].shift(63)
        panel['eps_fy0_3m_ago'] = panel.groupby('stock_code')['eps_fy0'].shift(63)
        panel['op_revision_3m'] = (panel['op_fy0'] - panel['op_fy0_3m_ago']) / panel['op_fy0_3m_ago'].abs()
        panel['eps_revision_3m'] = (panel['eps_fy0'] - panel['eps_fy0_3m_ago']) / panel['eps_fy0_3m_ago'].abs()

        # FY0/FY1/FY2는 각각 현재년도/다음년도/다다음년도 예상치입니다.
        # 기존 분석 파일과 호환되도록 FY 이름도 유지하되, 발표용 alias는
        # build_consensus_fy_panel()에서 함께 생성합니다.
        for metric in ['op', 'eps']:
            left_col = f'{metric}_fy1'
            right_col = f'{metric}_fy2'
            if {left_col, right_col}.issubset(panel.columns):
                panel[f'{metric}_growth_fy2_vs_fy1'] = (
                    panel[right_col] - panel[left_col]
                ) / panel[left_col].abs().replace(0, np.nan)

    print('6) 목표주가/투자의견 컨센서스 병합 중...')
    if not target_rating.empty:
        tr_cols = [
            'date', 'stock_code',
            'rating_point', 'rating_up_count', 'rating_down_count', 'rating_maintain_count',
            'rating_new_count', 'rating_total_count',
            'target_price', 'target_price_high', 'target_price_low', 'target_price_median',
            'target_gap_pct', 'target_price_std', 'target_price_cv',
            'target_up_count', 'target_down_count', 'target_total_count',
            'target_upside', 'target_revision_balance', 'rating_revision_balance', 'target_confidence'
        ]
        tr_cols = [c for c in tr_cols if c in target_rating.columns]
        panel = panel.merge(target_rating[tr_cols], on=['date', 'stock_code'], how='left')

    print('6-1) 밸류에이션 팩터 병합 중...')
    if not value_factor.empty:
        vf_cols = [
            'date', 'stock_code',
            'cash_dividend_total_thousand_krw',
            'dps_common_cash_krw',
            'per_ifrs_consolidated',
            'pbr_ifrs_consolidated',
            'psr_ifrs_consolidated',
            'dividend_yield_pct',
            'ev_ebitda',
        ]
        vf_cols = [c for c in vf_cols if c in value_factor.columns]
        panel = panel.merge(value_factor[vf_cols], on=['date', 'stock_code'], how='left')

    if 'close' in panel.columns:
        close = pd.to_numeric(panel['close'], errors='coerce').replace(0, np.nan)
        for offset, label in [(0, 'current_year'), (1, 'next_year'), (2, 'year_after_next'), (3, 'three_year_forward')]:
            eps_col = f'eps_fy{offset}'
            if eps_col in panel.columns:
                eps = pd.to_numeric(panel[eps_col], errors='coerce')
                # Forward PER는 EPS가 0 이하일 때 해석이 불안정하므로 NaN으로 둡니다.
                panel[f'forward_per_fy{offset}'] = close / eps.where(eps > 0)
                panel[f'forward_per_{label}'] = panel[f'forward_per_fy{offset}']

    # 밸류에이션/가격 기반 factor의 엄격한 검증이 필요할 때 사용할 수 있는
    # lag1 버전도 함께 제공합니다. 단, FnGuide PER/배당수익률처럼 전일자
    # 수정주가를 명시적으로 쓰는 항목은 기본 분석에서 추가 lag가 중복될 수 있습니다.
    panel = panel.sort_values(['stock_code', 'date'])
    valuation_lag_cols = [
        'cash_dividend_total_thousand_krw',
        'dps_common_cash_krw',
        'per_ifrs_consolidated',
        'pbr_ifrs_consolidated',
        'psr_ifrs_consolidated',
        'dividend_yield_pct',
        'ev_ebitda',
        'forward_per_fy0',
        'forward_per_fy1',
        'forward_per_fy2',
        'forward_per_fy3',
        'forward_per_current_year',
        'forward_per_next_year',
        'forward_per_year_after_next',
        'forward_per_three_year_forward',
    ]
    for col in valuation_lag_cols:
        if col in panel.columns:
            panel[f'{col}_lag1'] = panel.groupby('stock_code')[col].shift(1)
    for col in [
        'per_ifrs_consolidated',
        'pbr_ifrs_consolidated',
        'psr_ifrs_consolidated',
        'ev_ebitda',
        'forward_per_fy0',
        'forward_per_fy1',
        'forward_per_fy2',
        'forward_per_fy3',
        'forward_per_current_year',
        'forward_per_next_year',
        'forward_per_year_after_next',
        'forward_per_three_year_forward',
    ]:
        lag_col = f'{col}_lag1'
        if lag_col in panel.columns:
            panel[f'neg_{lag_col}'] = -pd.to_numeric(panel[lag_col], errors='coerce')

    panel['month'] = panel['date'].dt.to_period('M')
    monthly = (
        panel.sort_values(['stock_code', 'date'])
             .groupby(['stock_code', 'month'], as_index=False)
             .tail(1)
             .drop(columns=['month'])
    )

    panel.to_csv(OUT_MODEL_PANEL, index=False, encoding='utf-8-sig')
    monthly.to_csv(OUT_PANEL_MONTHLY, index=False, encoding='utf-8-sig')

    print(f'7) 저장 완료: {OUT_MODEL_PANEL}')
    print(f'   일별 패널 행 수: {len(panel):,}')
    print(f'   월말 패널 저장: {OUT_PANEL_MONTHLY}')
    print(f'   월말 패널 행 수: {len(monthly):,}')

    print('\n[검증] 가격 데이터 기간:', price['date'].min().date(), '~', price['date'].max().date())
    print('[검증] 가격 종목 수:', price['stock_code'].nunique())
    print('[검증] 패널 기간:', panel['date'].min().date(), '~', panel['date'].max().date())
    print('[검증] ETF 비중 매칭률:', panel['etf_weight_pct'].notna().mean())
    if not consensus.empty:
        print('[검증] 실적 컨센서스 기간:', consensus['date'].min().date(), '~', consensus['date'].max().date())
        print('[검증] 실적 컨센서스 fiscal years:', sorted(consensus['fiscal_year'].dropna().unique()))
        print('[검증] FY0 op 매칭률:', panel.get('op_fy0', pd.Series(dtype=float)).notna().mean())
        print('[검증] FY1 op 매칭률:', panel.get('op_fy1', pd.Series(dtype=float)).notna().mean())
    if not target_rating.empty:
        print('[검증] 목표주가/투자의견 기간:', target_rating['date'].min().date(), '~', target_rating['date'].max().date())
        print('[검증] 목표주가 매칭률:', panel.get('target_price', pd.Series(dtype=float)).notna().mean())
        print('[검증] 투자의견 매칭률:', panel.get('rating_point', pd.Series(dtype=float)).notna().mean())
        print('[검증] 목표주가CV 매칭률:', panel.get('target_price_cv', pd.Series(dtype=float)).notna().mean())
    if not value_factor.empty:
        print('[검증] 밸류에이션 팩터 기간:', value_factor['date'].min().date(), '~', value_factor['date'].max().date())
        print('[검증] PER 매칭률:', panel.get('per_ifrs_consolidated', pd.Series(dtype=float)).notna().mean())
        print('[검증] Forward PER FY1 매칭률:', panel.get('forward_per_fy1', pd.Series(dtype=float)).notna().mean())


if __name__ == '__main__':
    build_panel()
