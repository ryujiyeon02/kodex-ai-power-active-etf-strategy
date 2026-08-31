import pandas as pd

ETF_OFFICIAL_COSTS = {
    # KODEX_AI전력핵심설비/2026년 03월 월간 ETF 리포트: 총 보수 연 0.39%
    # KODEX_AI전력핵심설비 간이투자설명서: 총보수 0.3900%, 총보수ㆍ비용 0.4586%
    "annual_total_fee_rate": 0.003900,
    "annual_total_fee_expense_rate": 0.004586,
    # KODEX_AI전력핵심설비 투자설명서 운용과정 거래비용: 합계 거래비용 비율 0.11%
    "reported_trading_cost_ratio": 0.001100,
    "source": "KODEX_AI전력핵심설비 2026년 03월 월간 ETF 리포트 및 투자설명서",
}


# ============================================================
# 1. 시장코드 정리
# ============================================================

def normalize_market(market):
    """
    시장코드를 표준화합니다.

    예상 입력:
    - STK, KOSPI, 유가증권, 거래소
    - KSQ, KOSDAQ, 코스닥
    - KNX, KONEX, 코넥스
    """
    if pd.isna(market):
        return "UNKNOWN"

    m = str(market).strip().upper()

    if m in ["STK", "KOSPI", "유가증권", "거래소"]:
        return "KOSPI"

    if m in ["KSQ", "KOSDAQ", "코스닥"]:
        return "KOSDAQ"

    if m in ["KNX", "KONEX", "코넥스"]:
        return "KONEX"

    return m


# ============================================================
# 2. 매도세율
# ============================================================

def sell_tax_rate(date, market):
    """
    국내 주식 매도 시 증권거래세/농특세 가정.
    단위는 소수입니다.

    예:
    0.0015 = 0.15% = 15bp
    0.0020 = 0.20% = 20bp

    백테스트 기간:
    - 2024년: 18bp
    - 2025년: 15bp
    - 2026년 이후: 20bp
    """
    year = pd.Timestamp(date).year
    market = normalize_market(market)

    if market == "KONEX":
        return 0.0010  # 10bp 가정

    if market in ["KOSPI", "KOSDAQ"]:
        if year <= 2024:
            return 0.0018  # 18bp
        elif year == 2025:
            return 0.0015  # 15bp
        else:
            return 0.0020  # 20bp

    # 시장코드가 불명확하면 보수적으로 20bp
    return 0.0020


# ============================================================
# 3. 거래비용 시나리오
# ============================================================

COST_SCENARIOS = {
    # 비용 미반영: 순수 전략 성과 확인용
    "zero": {
        "commission_rate": 0.0,
        "agency_fee_rate": 0.0,
        "slippage_rate": 0.0,
        "apply_tax": False,
    },

    # 저비용: 이벤트 수수료, 특약 계좌, 지정가 위주 체결 가정
    "low": {
        "commission_rate": 0.00015,   # 1.5bp
        "agency_fee_rate": 0.000036,  # 0.36bp
        "slippage_rate": 0.00010,     # 1bp
        "apply_tax": True,
    },

    # 기본: 온라인 일반 수수료보다 낮지만, 퀀트 백테스트에서 너무 낙관적이지 않은 수준
    "base": {
        "commission_rate": 0.00030,   # 3bp
        "agency_fee_rate": 0.000036,  # 0.36bp
        "slippage_rate": 0.00030,     # 3bp
        "apply_tax": True,
    },

    # 보수적: 중소형주 포함, 체결 불리함이 있는 경우
    "high": {
        "commission_rate": 0.00050,   # 5bp
        "agency_fee_rate": 0.000036,  # 0.36bp
        "slippage_rate": 0.00070,     # 7bp
        "apply_tax": True,
    },

    # 스트레스: 거래대금 대비 주문 규모가 크거나 체결이 나쁜 경우
    "stress": {
        "commission_rate": 0.00080,   # 8bp
        "agency_fee_rate": 0.000036,  # 0.36bp
        "slippage_rate": 0.00100,     # 10bp
        "apply_tax": True,
    },
}


# ============================================================
# 4. ADV 기반 동적 슬리피지
# ============================================================

def dynamic_slippage_rate(
    base_slippage_rate,
    trade_weight,
    adv20_krw=None,
    portfolio_aum_krw=None,
    execution_days=1,
    impact_coefficient=0.0050,
    impact_exponent=0.5,
    max_impact_rate=0.0050,
):
    """
    ADV 참여율 기반으로 슬리피지율을 보정합니다.

    고정 슬리피지는 기본 체결 불리함으로 두고, 주문금액이 해당 종목의
    20일 평균 거래대금(ADV) 대비 커질수록 추가 시장충격 비용을 붙입니다.

    participation = (AUM * |trade_weight| / execution_days) / ADV20
    dynamic_slippage = base_slippage + impact_coefficient * participation^impact_exponent

    impact_coefficient=0.0050이면:
      - 1% ADV 참여율  → 추가 충격 약  5bp
      - 10% ADV 참여율 → 추가 충격 약 16bp
      - 100% ADV 참여율 → 추가 충격 50bp (cap 도달)
    실증 연구에서 100% ADV 거래 시 시장 충격은 50~150bp 수준으로 추정되므로
    cap(max_impact_rate=0.0050)을 50bp로 설정해 하단에 맞춥니다.
    cap은 참여율 ~100% 이상에서 binding됩니다.
    """
    base = float(base_slippage_rate or 0.0)
    if (
        adv20_krw is None
        or portfolio_aum_krw is None
        or pd.isna(adv20_krw)
        or pd.isna(portfolio_aum_krw)
        or float(adv20_krw) <= 0
        or float(portfolio_aum_krw) <= 0
        or float(execution_days) <= 0
    ):
        return {
            "slippage_rate": base,
            "base_slippage_rate": base,
            "market_impact_rate": 0.0,
            "participation_rate": pd.NA,
            "adv20_krw": adv20_krw,
            "trade_notional_krw": pd.NA,
            "daily_trade_notional_krw": pd.NA,
            "used_dynamic_slippage": False,
        }

    trade_notional = abs(float(trade_weight)) * float(portfolio_aum_krw)
    daily_trade_notional = trade_notional / float(execution_days)
    participation = daily_trade_notional / float(adv20_krw)
    if not pd.notna(participation) or participation < 0:
        participation = 0.0

    impact = float(impact_coefficient) * (float(participation) ** float(impact_exponent))
    impact = min(max(impact, 0.0), float(max_impact_rate))
    return {
        "slippage_rate": base + impact,
        "base_slippage_rate": base,
        "market_impact_rate": impact,
        "participation_rate": float(participation),
        "adv20_krw": float(adv20_krw),
        "trade_notional_krw": float(trade_notional),
        "daily_trade_notional_krw": float(daily_trade_notional),
        "used_dynamic_slippage": True,
    }


# ============================================================
# 5. 거래 1건 비용 계산
# ============================================================

def calc_trade_cost(
    date,
    market,
    trade_value,
    side,
    scenario="base",
    commission_rate=None,
    agency_fee_rate=None,
    slippage_rate=None,
    apply_tax=None,
):
    """
    거래 1건의 비용을 계산합니다.

    Parameters
    ----------
    date : str or datetime
        거래일
    market : str
        시장코드. 예: STK, KSQ, KOSPI, KOSDAQ
    trade_value : float
        거래대금. 양수/음수 모두 허용하지만 내부에서는 절댓값 사용.
    side : str
        BUY 또는 SELL
    scenario : str
        zero, low, base, high, stress 중 하나.
    commission_rate, agency_fee_rate, slippage_rate, apply_tax :
        직접 지정하면 scenario 값보다 우선합니다.

    Returns
    -------
    dict
        비용 상세 내역
    """

    if scenario not in COST_SCENARIOS:
        raise ValueError(
            f"Unknown scenario: {scenario}. "
            f"Choose from {list(COST_SCENARIOS.keys())}"
        )

    config = COST_SCENARIOS[scenario].copy()

    if commission_rate is not None:
        config["commission_rate"] = commission_rate

    if agency_fee_rate is not None:
        config["agency_fee_rate"] = agency_fee_rate

    if slippage_rate is not None:
        config["slippage_rate"] = slippage_rate

    if apply_tax is not None:
        config["apply_tax"] = apply_tax

    side = str(side).upper().strip()

    if side not in ["BUY", "SELL"]:
        raise ValueError("side must be 'BUY' or 'SELL'")

    trade_value = abs(float(trade_value))
    market_std = normalize_market(market)

    commission = trade_value * config["commission_rate"]
    agency_fee = trade_value * config["agency_fee_rate"]
    slippage = trade_value * config["slippage_rate"]

    if side == "SELL" and config["apply_tax"]:
        tax_rate = sell_tax_rate(date, market_std)
    else:
        tax_rate = 0.0

    tax = trade_value * tax_rate

    total_cost = commission + agency_fee + slippage + tax

    total_cost_rate = (
        config["commission_rate"]
        + config["agency_fee_rate"]
        + config["slippage_rate"]
        + tax_rate
    )

    return {
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "market": market_std,
        "side": side,
        "scenario": scenario,
        "trade_value": trade_value,

        "commission_rate": config["commission_rate"],
        "agency_fee_rate": config["agency_fee_rate"],
        "slippage_rate": config["slippage_rate"],
        "tax_rate": tax_rate,
        "total_cost_rate": total_cost_rate,

        "commission": commission,
        "agency_fee": agency_fee,
        "slippage": slippage,
        "tax": tax,
        "total_cost": total_cost,
    }


# ============================================================
# 5. 매수/매도 금액에서 바로 비용만 뽑는 간단 함수
# ============================================================

def get_trade_cost_amount(
    date,
    market,
    trade_value,
    side,
    scenario="base",
):
    return calc_trade_cost(
        date=date,
        market=market,
        trade_value=trade_value,
        side=side,
        scenario=scenario,
    )["total_cost"]


def daily_expense_rate(annual_rate=None, periods_per_year=252):
    """
    연율 비용을 일별 비용률로 변환합니다.

    기본값은 투자설명서의 총보수ㆍ비용 0.4586%입니다. 이는 운용보수만이
    아니라 기타비용까지 포함한 값이며, 증권거래비용/금융비용은 제외된
    항목입니다.
    """
    if annual_rate is None:
        annual_rate = ETF_OFFICIAL_COSTS["annual_total_fee_expense_rate"]
    return float(annual_rate) / float(periods_per_year)


def calc_rebalance_cost_from_weight_change(
    date,
    previous_weights,
    target_weights,
    market_map=None,
    default_market="KOSPI",
    scenario="base",
    adv20_map=None,
    dynamic_slippage=False,
    portfolio_aum_krw=None,
    execution_days=1,
    impact_coefficient=0.0050,
    impact_exponent=0.5,
    max_impact_rate=0.0050,
):
    """
    비중 변화로부터 리밸런싱 매매비용을 계산합니다.

    previous_weights와 target_weights는 종목코드 index를 가진 비중 Series입니다.
    포트폴리오 총자산을 1로 두고, 비중 변화 절댓값을 거래대금으로 해석합니다.

    BUY에는 수수료/유관기관수수료/슬리피지만 적용하고, SELL에는 여기에
    증권거래세/농특세를 추가합니다.

    dynamic_slippage=True이면 고정 슬리피지율에 ADV 참여율 기반 시장충격
    비용을 추가합니다. 이때 trade_value는 포트폴리오 총자산을 1로 둔
    비중 변화이고, 실제 주문금액은 portfolio_aum_krw * trade_value로
    계산합니다.
    """
    prev = pd.to_numeric(previous_weights, errors="coerce").fillna(0.0)
    target = pd.to_numeric(target_weights, errors="coerce").fillna(0.0)
    idx = prev.index.union(target.index)
    prev = prev.reindex(idx, fill_value=0.0)
    target = target.reindex(idx, fill_value=0.0)
    delta = target - prev
    market_map = market_map or {}
    adv20_map = adv20_map or {}
    scenario_config = COST_SCENARIOS.get(scenario, COST_SCENARIOS["base"])

    rows = []
    for code, change in delta.items():
        if abs(change) <= 1e-12:
            continue
        side = "BUY" if change > 0 else "SELL"
        market = market_map.get(code, default_market)
        slippage_override = None
        slippage_diag = {
            "base_slippage_rate": scenario_config.get("slippage_rate", 0.0),
            "market_impact_rate": 0.0,
            "participation_rate": pd.NA,
            "adv20_krw": pd.NA,
            "trade_notional_krw": pd.NA,
            "daily_trade_notional_krw": pd.NA,
            "used_dynamic_slippage": False,
        }
        if dynamic_slippage:
            slippage_diag = dynamic_slippage_rate(
                base_slippage_rate=scenario_config.get("slippage_rate", 0.0),
                trade_weight=abs(change),
                adv20_krw=adv20_map.get(code),
                portfolio_aum_krw=portfolio_aum_krw,
                execution_days=execution_days,
                impact_coefficient=impact_coefficient,
                impact_exponent=impact_exponent,
                max_impact_rate=max_impact_rate,
            )
            slippage_override = slippage_diag["slippage_rate"]
        detail = calc_trade_cost(
            date=date,
            market=market,
            trade_value=abs(change),
            side=side,
            scenario=scenario,
            slippage_rate=slippage_override,
        )
        detail["stock_code"] = code
        detail["weight_change"] = float(change)
        detail.update(slippage_diag)
        rows.append(detail)

    if not rows:
        return {
            "scenario": scenario,
            "dynamic_slippage": bool(dynamic_slippage),
            "total_traded_weight": 0.0,
            "buy_weight": 0.0,
            "sell_weight": 0.0,
            "commission": 0.0,
            "agency_fee": 0.0,
            "slippage": 0.0,
            "base_slippage": 0.0,
            "market_impact_slippage": 0.0,
            "tax": 0.0,
            "total_cost": 0.0,
            "average_cost_rate_on_traded_weight": 0.0,
            "average_slippage_rate_on_traded_weight": 0.0,
            "max_slippage_rate": 0.0,
            "average_participation_rate": 0.0,
            "max_participation_rate": 0.0,
            "missing_adv_trade_weight": 0.0,
            "trade_count": 0,
        }

    df = pd.DataFrame(rows)
    total_traded = float(df["trade_value"].sum())
    base_slippage = float((df["trade_value"] * df["base_slippage_rate"]).sum())
    market_impact_slippage = float((df["trade_value"] * df["market_impact_rate"]).sum())
    participation = pd.to_numeric(df["participation_rate"], errors="coerce")
    missing_adv_trade_weight = float(df.loc[participation.isna(), "trade_value"].sum())
    return {
        "scenario": scenario,
        "dynamic_slippage": bool(dynamic_slippage),
        "total_traded_weight": total_traded,
        "buy_weight": float(df.loc[df["side"].eq("BUY"), "trade_value"].sum()),
        "sell_weight": float(df.loc[df["side"].eq("SELL"), "trade_value"].sum()),
        "commission": float(df["commission"].sum()),
        "agency_fee": float(df["agency_fee"].sum()),
        "slippage": float(df["slippage"].sum()),
        "base_slippage": base_slippage,
        "market_impact_slippage": market_impact_slippage,
        "tax": float(df["tax"].sum()),
        "total_cost": float(df["total_cost"].sum()),
        "average_cost_rate_on_traded_weight": float(df["total_cost"].sum() / total_traded) if total_traded else 0.0,
        "average_slippage_rate_on_traded_weight": float(df["slippage"].sum() / total_traded)
        if total_traded
        else 0.0,
        "max_slippage_rate": float(pd.to_numeric(df["slippage_rate"], errors="coerce").max()),
        "average_participation_rate": float(
            (participation.fillna(0.0) * df["trade_value"]).sum()
            / max(float(df.loc[participation.notna(), "trade_value"].sum()), 1e-12)
        )
        if participation.notna().any()
        else 0.0,
        "max_participation_rate": float(participation.max()) if participation.notna().any() else 0.0,
        "missing_adv_trade_weight": missing_adv_trade_weight,
        "trade_count": int(len(df)),
    }


# ============================================================
# 6. 예시
# ============================================================

if __name__ == "__main__":
    example_buy = calc_trade_cost(
        date="2025-06-16",
        market="STK",
        trade_value=10_000_000,
        side="BUY",
        scenario="base",
    )

    example_sell = calc_trade_cost(
        date="2025-06-16",
        market="STK",
        trade_value=10_000_000,
        side="SELL",
        scenario="base",
    )

    print("BUY example:")
    print(example_buy)

    print("\nSELL example:")
    print(example_sell)
