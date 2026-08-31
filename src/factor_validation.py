import numpy as np
import pandas as pd

from project_paths import MODEL_PANEL_FILE, OUTPUT_DIR, ensure_output_dir
from strategy_factor_diagnostics import build_exhaustive_ic_monthly, summarize_factor_ic
from selected_factor_config import SELECTED_FACTOR_SPECS


SELECTED_FACTOR_REASON = {
    spec["factor"]: spec.get("rationale", "")
    for spec in SELECTED_FACTOR_SPECS
}
SELECTED_FACTOR_FAMILY = {
    spec["factor"]: spec.get("theme", "")
    for spec in SELECTED_FACTOR_SPECS
}


FAMILY_DESCRIPTIONS = {
    "information_liquidity_size": (
        "시가총액, 유동성, 기관 커버리지, 정보반영도가 충분한 종목을 더 신뢰하는 축"
    ),
    "forward_consensus": (
        "AI 데이터센터와 전력망 투자 수요가 매출 컨센서스 성장으로 반영되는지 보는 축"
    ),
    "quality_growth": (
        "매출 성장이 영업이익 증가로 이어지는지 확인하는 품질 성장 축"
    ),
    "forward_eps": (
        "주당이익 성장성과 가격 대비 이익 매력도 개선을 함께 보는 축"
    ),
    "valuation": (
        "PER/PBR/PSR cheapness 중심의 밸류에이션 proxy 축. DPS와 EV/EBITDA는 결산 데이터 timing을 방어하기 어려워 메인 전략에서는 제외"
    ),
}


def _add_missing_rate(monthly: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    out = monthly.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    stock_count = (
        panel.dropna(subset=["date", "stock_code"])
        .groupby("date")["stock_code"]
        .nunique()
        .rename("total_stock_count")
    )
    out = out.merge(stock_count, left_on="date", right_index=True, how="left")
    out["raw_non_missing_count"] = pd.to_numeric(
        out.get("raw_non_missing_count"), errors="coerce"
    )
    out["missing_count"] = out["total_stock_count"] - out["raw_non_missing_count"]
    out["missing_rate"] = out["missing_count"] / out["total_stock_count"].replace(0, np.nan)
    return out


def _selected_label(row: pd.Series) -> tuple[bool, str, str]:
    factor = row["factor"]
    if factor in SELECTED_FACTOR_FAMILY:
        return True, SELECTED_FACTOR_FAMILY[factor], SELECTED_FACTOR_REASON.get(factor, "")
    return False, row.get("theme", ""), ""


def _build_validation_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    summary = summarize_factor_ic(monthly)
    if summary.empty:
        return summary

    missing = (
        monthly.groupby(["factor", "theme"], dropna=False)
        .agg(
            average_missing_rate=("missing_rate", "mean"),
            median_missing_rate=("missing_rate", "median"),
            average_raw_non_missing_count=("raw_non_missing_count", "mean"),
            average_total_stock_count=("total_stock_count", "mean"),
        )
        .reset_index()
    )
    summary = summary.merge(missing, on=["factor", "theme"], how="left")
    labels = summary.apply(_selected_label, axis=1, result_type="expand")
    labels.columns = ["selected_for_main_strategy", "selected_factor_family", "selection_rationale"]
    summary = pd.concat([summary, labels], axis=1)

    ordered_cols = [
        "factor",
        "theme",
        "selected_for_main_strategy",
        "selected_factor_family",
        "observations",
        "mean_ic",
        "median_ic",
        "ic_std",
        "ic_ir",
        "hit_ratio_ic_positive",
        "mean_top_minus_bottom_return",
        "hit_ratio_top_minus_bottom_positive",
        "average_missing_rate",
        "median_missing_rate",
        "average_raw_non_missing_count",
        "average_total_stock_count",
        "selection_rationale",
    ]
    return summary[[c for c in ordered_cols if c in summary.columns]].sort_values(
        ["selected_for_main_strategy", "mean_ic"], ascending=[False, False]
    )


def _build_family_summary(summary: pd.DataFrame) -> pd.DataFrame:
    selected = summary[summary["selected_for_main_strategy"]].copy()
    if selected.empty:
        return pd.DataFrame()
    rows = []
    for family, g in selected.groupby("selected_factor_family"):
        rows.append(
            {
                "factor_family": family,
                "used_factors": ", ".join(g["factor"].tolist()),
                "factor_count": int(g["factor"].nunique()),
                "mean_ic": float(g["mean_ic"].mean()),
                "median_ic": float(g["median_ic"].median()),
                "mean_hit_ratio_ic_positive": float(g["hit_ratio_ic_positive"].mean()),
                "mean_top_minus_bottom_return": float(g["mean_top_minus_bottom_return"].mean()),
                "mean_hit_ratio_top_minus_bottom_positive": float(
                    g["hit_ratio_top_minus_bottom_positive"].mean()
                ),
                "average_missing_rate": float(g["average_missing_rate"].mean()),
                "interpretation": FAMILY_DESCRIPTIONS.get(family, ""),
                "selected": True,
            }
        )
    return pd.DataFrame(rows).sort_values("mean_ic", ascending=False)


def write_additional_data_needed() -> None:
    lines = [
        "# Additional Data Needed",
        "",
        "현재 파일로 가능한 분석은 ETF PDF 바스켓 복제, 공개 방법론 근사, FnGuide 컨센서스 기반 팩터 검증입니다. 더 정확한 복제와 전략 검증을 위해 필요한 추가 데이터는 다음과 같습니다.",
        "",
        "## 높은 우선순위",
        "",
        "- 공식 지수 구성종목 변경 이력: NH/iSelect 지수의 실제 편입/편출 결정일, 적용일, 종목별 지수 편입주식수.",
        "- 공식 유동주식비율 이력: 방법론상 NH 인덱스 개발팀이 자체 산출하므로 FnGuide 유동주식수는 대용치입니다.",
        "- 기업이벤트 상세 이력: 액면분할, 무상증자, 거래정지, 권리락, 배당, 현금대체 표시, 지수 divisor 조정.",
        "- ETF 일별 총보수/비용 회계 처리 또는 공식 비용 시계열: 현재는 공식 총보수ㆍ비용 연율을 일할 차감합니다.",
        "",
        "## 중간 우선순위",
        "",
        "- 종목별 실제 체결 가능 호가/스프레드/시장충격 데이터: slippage를 더 현실적으로 추정하기 위해 필요합니다.",
        "- ETF 설정/환매 및 CU 단위 데이터: PDF 바스켓과 실제 NAV 차이를 더 정밀하게 해석하기 위해 필요합니다.",
        "- 지수 산출기관의 total return/net return 여부와 배당 반영 방식: 종목 수익률 복제와 기초지수 비교 기준을 맞추기 위해 필요합니다.",
        "- 장기 과거 컨센서스: ETF 상장 이후 표본이 짧으므로 IC 검증의 안정성을 높이기 위해 필요합니다.",
        "",
        "## 발표에서 명확히 말해야 할 한계",
        "",
        "- 현재 cap20 복제는 공식 지수 산출 엔진이 아니라 FnGuide 유동주식수 기반 근사입니다.",
        "- PDF 복제는 관측 바스켓 기반이지만, 거래정지/기업이벤트 시 현금대체 표시를 그대로 현금으로 해석하면 추적오차가 과대 계산될 수 있습니다.",
        "- factor IC는 상장 이후 짧은 표본에서 계산된 in-sample 검증이므로 확정적 alpha가 아니라 검증 가능한 개선 가능성으로 해석해야 합니다.",
    ]
    (OUTPUT_DIR / "additional_data_needed.md").write_text("\n".join(lines), encoding="utf-8")


def _fmt_pct(x: float) -> str:
    return "" if pd.isna(x) else f"{x:.2%}"


def _fmt_num(x: float) -> str:
    return "" if pd.isna(x) else f"{x:.3f}"


def write_factor_inventory_markdown(summary: pd.DataFrame, family_summary: pd.DataFrame) -> None:
    lines = [
        "# Factor Inventory and IC Validation",
        "",
        "이 문서는 현재 보유한 FnGuide 가격/컨센서스/목표주가/투자의견/value factor 데이터로 만든 팩터 후보와 IC 검증 결과를 정리한 것입니다.",
        "",
        "## 중요한 처리 원칙",
        "",
        "- 종목 universe는 KODEX AI전력핵심설비 ETF PDF 구성종목 안으로 제한합니다.",
        "- 월말 시점의 factor score와 다음 1개월 종목 수익률을 비교해 Spearman IC를 계산합니다.",
        "- 모멘텀 팩터는 사용하지 않습니다.",
        "- EV/EBITDA와 DPS는 2026년 구간 데이터가 없고 결산 데이터 timing을 방어하기 어려워 IC 후보와 메인 전략에서 제외합니다.",
        "- PER/PBR/PSR 계열은 DataGuide 원본값과 역수형 cheapness proxy를 모두 후보로 둡니다.",
        "- 최종 메인 전략은 선택된 family 전체를 무조건 쓰는 것이 아니라, 데이터 timing과 결측률을 함께 보고 방어 가능한 팩터만 사용합니다.",
        "",
        "## Selected Factor Families",
        "",
    ]
    if family_summary.empty:
        lines.append("선택된 factor family가 없습니다.")
    else:
        lines.append("| family | used factors | mean IC | IC hit ratio | top-bottom return | missing rate | interpretation |")
        lines.append("|---|---|---:|---:|---:|---:|---|")
        for _, row in family_summary.iterrows():
            lines.append(
                "| {family} | {factors} | {mean_ic} | {hit} | {tmb} | {miss} | {interp} |".format(
                    family=row.get("factor_family", ""),
                    factors=row.get("used_factors", ""),
                    mean_ic=_fmt_num(row.get("mean_ic")),
                    hit=_fmt_pct(row.get("mean_hit_ratio_ic_positive")),
                    tmb=_fmt_pct(row.get("mean_top_minus_bottom_return")),
                    miss=_fmt_pct(row.get("average_missing_rate")),
                    interp=row.get("interpretation", ""),
                )
            )

    lines += [
        "",
        "## All IC-Tested Factors",
        "",
        "| factor | theme | selected | observations | mean IC | IC hit ratio | top-bottom return | missing rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    if not summary.empty:
        view = summary.sort_values(["selected_for_main_strategy", "theme", "mean_ic"], ascending=[False, True, False])
        for _, row in view.iterrows():
            lines.append(
                "| {factor} | {theme} | {selected} | {obs} | {mean_ic} | {hit} | {tmb} | {miss} |".format(
                    factor=row.get("factor", ""),
                    theme=row.get("theme", ""),
                    selected="Y" if bool(row.get("selected_for_main_strategy")) else "",
                    obs=int(row.get("observations", 0)) if pd.notna(row.get("observations")) else 0,
                    mean_ic=_fmt_num(row.get("mean_ic")),
                    hit=_fmt_pct(row.get("hit_ratio_ic_positive")),
                    tmb=_fmt_pct(row.get("mean_top_minus_bottom_return")),
                    miss=_fmt_pct(row.get("average_missing_rate")),
                )
            )

    lines += [
        "",
        "## Factor Groups",
        "",
        "- `information_liquidity_size`: 시가총액, 거래 유동성, 애널리스트/목표주가/투자의견 coverage. 시총은 coverage 자체가 아니라 유동성ㆍ기관 관심ㆍ정보반영도 proxy입니다.",
        "- `forward_consensus`: FY0/FY1/FY2/FY3 매출, 영업이익, 순이익, EPS 컨센서스와 성장/증가폭.",
        "- `forward_eps`: EPS 성장률, EPS yield, forward PER의 역수형 이익수익률.",
        "- `valuation`: PER/PBR/PSR 및 역수형 cheapness proxy. EV/EBITDA와 DPS는 제외.",
        "- `risk`: 변동성, drawdown, 목표주가 CV/표준편차 등 불확실성 proxy.",
        "- `liquidity_size`: 거래대금, 거래량, 유동시총, 거래대금/시총, 거래량/유동주식수.",
        "",
        "## Presentation Note",
        "",
        "이 결과는 짧은 상장 이후 표본에서 나온 IC 검증입니다. 따라서 확정적 alpha가 아니라, ETF 구성종목 안에서 검증 가능한 비중조정 가능성으로 해석해야 합니다. 최종 전략 선택은 mean IC뿐 아니라 hit ratio, top-bottom return, 결측률, 데이터 timing 방어 가능성을 함께 기준으로 삼습니다.",
    ]
    (OUTPUT_DIR / "factor_inventory_and_ic_summary.md").write_text("\n".join(lines), encoding="utf-8")


def run_factor_validation() -> dict[str, pd.DataFrame]:
    ensure_output_dir()
    panel = pd.read_csv(MODEL_PANEL_FILE, dtype={"stock_code": str}, low_memory=False)
    panel["stock_code"] = panel["stock_code"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")

    monthly = build_exhaustive_ic_monthly(panel)
    monthly = _add_missing_rate(monthly, panel)
    summary = _build_validation_summary(monthly)
    family_summary = _build_family_summary(summary)

    factor_ic = monthly[
        [
            "date",
            "factor",
            "theme",
            "ic",
            "raw_non_missing_count",
            "total_stock_count",
            "missing_count",
            "missing_rate",
        ]
    ].copy()
    factor_top_bottom = monthly[
        [
            "date",
            "factor",
            "theme",
            "top_minus_bottom_return",
            "top_group_count",
            "bottom_group_count",
            "raw_non_missing_count",
            "total_stock_count",
            "missing_rate",
        ]
    ].copy()

    summary.to_csv(OUTPUT_DIR / "factor_validation_summary.csv", index=False, encoding="utf-8-sig")
    factor_ic.to_csv(OUTPUT_DIR / "factor_ic_timeseries.csv", index=False, encoding="utf-8-sig")
    factor_top_bottom.to_csv(OUTPUT_DIR / "factor_top_bottom_timeseries.csv", index=False, encoding="utf-8-sig")
    family_summary.to_csv(
        OUTPUT_DIR / "factor_family_validation_summary.csv", index=False, encoding="utf-8-sig"
    )
    write_additional_data_needed()
    write_factor_inventory_markdown(summary, family_summary)
    return {
        "summary": summary,
        "ic_timeseries": factor_ic,
        "top_bottom_timeseries": factor_top_bottom,
        "family_summary": family_summary,
    }


if __name__ == "__main__":
    outputs = run_factor_validation()
    print(outputs["family_summary"].to_string(index=False))
