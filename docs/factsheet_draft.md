# Factsheet Draft

## Consensus Active MVO Overlay

**As of 2026-05-06**

## Strategy Overview

| 항목 | 내용 |
|---|---|
| 전략명 | Consensus Active MVO Overlay |
| 투자대상 | KODEX AI전력핵심설비 ETF KRX PDF 구성종목 |
| Benchmark | KRX PDF 복제 포트폴리오 |
| Reference Index | iSelect AI전력핵심설비 지수 |
| 리밸런싱 | 주간 |
| 핵심 신호 | EPS revision 1M, target upside, rating point |
| 신호 가중치 | 동일가중, 1/3 each |
| 비중 산출 | Benchmark-relative MVO |
| TE budget | 20% ex-ante annualized |
| 개별 최대비중 | 50% |
| 편입종목 최소비중 | 1% |
| One-way turnover limit | 30% |

## Investment Objective

KODEX AI전력핵심설비 ETF의 실제 PDF 바스켓을 benchmark로 삼고, 동일 구성종목 안에서 컨센서스 신호가 우호적인 종목을 더 담아 PDF 대비 초과성과를 추구합니다.

## Performance Summary

| 지표 | 최종 전략 | PDF Benchmark |
|---|---:|---:|
| 누적수익률 | 664.06% | 495.88% |
| PDF 대비 초과 누적수익률 | +168.18%p | - |
| 연환산 변동성 | 55.78% | 54.10% |
| Sharpe Ratio | 3.94 | - |
| 최대낙폭 | -32.92% | - |
| PDF 대비 Tracking Error | 17.90% | - |
| Information Ratio | 0.843 | - |
| PDF 상관계수 | 0.947 | 1.000 |

## Period Returns

기초지수 대비 참고 성과입니다.

| 기간 | 최종 전략 | 기초지수 | 초과수익 |
|---|---:|---:|---:|
| MTD | 19.25% | 17.75% | +1.51%p |
| YTD | 197.89% | 170.43% | +27.47%p |
| 1M | 101.21% | 100.65% | +0.56%p |
| 3M | 120.51% | 118.47% | +2.04%p |
| 6M | 147.47% | 142.10% | +5.38%p |
| 1Y | 533.22% | 511.48% | +21.74%p |
| Since inception | 656.17% | 498.60% | +157.56%p |

## Top Holdings

| 종목 | 전략 비중 | PDF 비중 | Active weight |
|---|---:|---:|---:|
| 효성중공업 | 45.12% | 18.00% | +27.12%p |
| HD현대일렉트릭 | 14.20% | 12.74% | +1.46%p |
| LS ELECTRIC | 13.06% | 24.61% | -11.55%p |
| 대한전선 | 12.08% | 10.88% | +1.20%p |
| LS마린솔루션 | 5.02% | 1.14% | +3.88%p |
| LS에코에너지 | 4.52% | 1.23% | +3.29%p |
| LS | 1.00% | 12.97% | -11.97%p |
| 일진전기 | 1.00% | 4.63% | -3.63%p |
| 대원전선 | 1.00% | 1.43% | -0.43%p |
| 가온전선 | 1.00% | 5.38% | -4.38%p |

## Risk Indicators

| 지표 | 값 | 해석 |
|---|---:|---|
| Tracking Error vs PDF | 17.90% | PDF 대비 active risk 사용 수준 |
| Information Ratio | 0.843 | active risk 1단위당 초과성과 |
| Correlation vs PDF | 0.947 | 같은 테마 흐름은 유지 |
| Max Drawdown | -32.92% | 테마 ETF 특유의 큰 하락위험 존재 |
| Latest HHI | 0.261 | PDF보다 집중도 높음 |
| Effective holdings | 3.84개 | 실질 분산도 낮음 |
| Average rebalance one-way turnover | 21.71% | 주간 리밸런싱 비용 관리 필요 |
| 기준 capacity | 99.09억 원 | 3일 분할ㆍ10% ADVㆍ시계열 하위 10% 기준 |

## Cumulative Performance Charts

Factsheet에 사용할 차트 파일은 다음과 같습니다.

| 파일 | 설명 |
|---|---|
| `output/chart_factsheet_cumulative_vs_index.png` | 최종 전략 vs 기초지수 누적성과 |
| `output/chart_factsheet_drawdown_vs_index.png` | 최종 전략 vs 기초지수 drawdown |
| `output/chart_factsheet_rolling_te_vs_index.png` | rolling tracking error |
| `output/chart_final_cumulative_return.png` | 최종 전략 vs PDF benchmark 누적성과 |
| `output/chart_final_cumulative_active_return.png` | PDF 대비 누적 active return |

## Portfolio Comment

전략은 최근 효성중공업을 크게 overweight하고 LS, LS ELECTRIC을 PDF 대비 underweight하고 있습니다. 이는 최신 EPS revision, target upside, rating point를 동일가중으로 반영한 consensus score와 benchmark-relative MVO 결과입니다.

성과는 PDF benchmark 대비 우수했으나, 포트폴리오 집중도가 높아졌고 주간 리밸런싱에 따른 turnover와 거래비용 관리가 중요합니다. 따라서 본 전략은 대규모 패시브 복제 전략이 아니라, 제한된 capacity 안에서 운용하는 active overlay 전략으로 보는 것이 적절합니다.

## Short Comment for Client Use

KODEX AI전력핵심설비 ETF의 실제 PDF 바스켓 안에서 컨센서스 신호를 활용해 비중을 조정한 결과, 비용 반영 후에도 benchmark 대비 초과성과가 확인되었습니다. 다만 종목 집중도와 turnover가 높아, 운용규모와 체결비용을 함께 관리해야 하는 전략입니다.

