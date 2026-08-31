# Investment Proposal

## Strategy Name

**KODEX AI전력핵심설비 ETF Consensus Active MVO Overlay**

## Executive Summary

본 전략은 KODEX AI전력핵심설비 ETF의 실제 KRX PDF 바스켓을 benchmark로 두고, 동일 구성종목 안에서 컨센서스 기반 점수와 benchmark-relative MVO를 이용해 비중만 조정하는 active overlay 전략입니다.

전략의 목적은 ETF 구성종목을 새로 고르는 것이 아니라, 이미 ETF가 편입한 전력설비 종목들 안에서 **EPS revision, 목표주가 괴리율, 투자의견 점수**가 더 우호적인 종목을 PDF보다 더 담고, 신호가 약한 종목은 덜 담는 것입니다.

최종 백테스트 기준 성과는 다음과 같습니다.

| 항목 | 값 |
|---|---:|
| 평가기간 | 2024-07-10 ~ 2026-05-06 |
| 최종 전략 누적수익률, 비용 반영 | 664.06% |
| PDF benchmark 누적수익률 | 495.88% |
| PDF 대비 초과 누적수익률 | +168.18%p |
| 연환산 변동성 | 55.78% |
| Sharpe Ratio | 3.94 |
| PDF 대비 Tracking Error | 17.90% |
| Information Ratio | 0.843 |
| PDF 일별 수익률 상관계수 | 0.947 |
| 최대낙폭 | -32.92% |

## Why Adopt This Strategy

### 1. ETF 내부 비중조정 전략이라 benchmark 정의가 명확합니다

일반적인 stock picking 전략과 달리, 이 전략은 한국 주식 전체에서 종목을 새로 찾지 않습니다. KODEX AI전력핵심설비 ETF가 실제로 보유한 KRX PDF 구성종목 안에서만 비중을 조정합니다.

따라서 성과 평가는 다음 질문에 집중됩니다.

```text
같은 ETF 구성종목 안에서
PDF 비중과 다르게 배분하면
PDF benchmark보다 더 나은 위험조정성과를 낼 수 있는가?
```

이 구조는 투자자에게 설명하기 쉽고, 전략의 active risk를 PDF benchmark 기준으로 직접 관리할 수 있다는 장점이 있습니다.

### 2. 기대수익의 논리가 ETF 테마와 직접 연결됩니다

AI전력핵심설비 ETF는 단순 AI 소프트웨어 테마가 아니라, 데이터센터 전력수요, 전력망 투자, 변압기, 전선, 전력기기 수요로 이어지는 실물 인프라 테마입니다.

이 테마에서는 수주, 매출, 영업이익, EPS 전망 변화가 애널리스트 컨센서스에 비교적 직접적으로 반영될 가능성이 있습니다. 따라서 컨센서스 변화와 목표주가, 투자의견을 이용한 횡단면 비교가 자연스럽습니다.

### 3. 단순 점수 틸트보다 MVO 적용 후 성과가 개선되었습니다

단순 점수 틸트는 점수가 높은 종목을 기계적으로 overweight하는 방식입니다. 최종 전략은 여기에 공분산, tracking error budget, turnover penalty를 반영해 benchmark-relative MVO로 비중을 산출합니다.

| 구분 | 누적수익률 | PDF 대비 초과 | Sharpe | TE | IR | PDF 상관 |
|---|---:|---:|---:|---:|---:|---:|
| 단순 점수 tilt | 562.51% | +66.63%p | 3.55 | 8.44% | 0.766 | 0.988 |
| 최종 MVO 전략 | 664.06% | +168.18%p | 3.94 | 17.90% | 0.843 | 0.947 |

MVO 적용 후 TE는 증가했지만, 같은 active risk를 사용해 얻은 초과성과를 나타내는 IR도 개선되었습니다. 즉 단순히 더 위험하게 만든 것이 아니라, active risk를 더 효율적으로 사용한 결과로 해석할 수 있습니다.

## Source of Expected Return

전략의 기대수익 원천은 다음 세 가지 컨센서스 신호의 결합입니다.

| 신호 | 정의 | 기대수익 논리 |
|---|---|---|
| EPS revision 1M | 다음 연도 EPS 컨센서스의 21거래일 변화율 | 최근 이익 전망이 상향되는 종목 선호 |
| Target upside | `(목표주가 - 현재가) / 현재가` | 애널리스트가 보는 상승여력과 가격 센티먼트 반영 |
| Rating point | 투자의견 점수, 5 = Strong Buy | 컨센서스 방향 확인용 보조 신호 |

최종 점수는 세 신호를 동일가중으로 표준화해 계산합니다.

```text
ConsensusScore
= 1/3 * z(EPS revision 1M)
+ 1/3 * z(Target upside)
+ 1/3 * z(Rating point)
```

동일가중을 사용한 이유는 표본이 짧고 종목 수가 적은 상황에서 특정 가중치 하나에 과도하게 의존했다는 인상을 줄이기 위해서입니다.

## Portfolio Construction

| 항목 | 설정 |
|---|---|
| Universe | KODEX AI전력핵심설비 ETF KRX PDF 편입종목 |
| Benchmark | KRX PDF 복제 포트폴리오 |
| Rebalancing | 주간 |
| Score | EPS revision 1M, target upside, rating point 동일가중 |
| Allocation | Benchmark-relative MVO |
| Ex-ante TE budget | 20% |
| 개별 최대비중 | 50% |
| PDF 편입종목 최소비중 | 1% |
| One-way turnover limit | 30% |
| 비용 | 매매수수료, 유관기관수수료, 슬리피지, 매도세, 펀드 총보수ㆍ비용 반영 |

## Key Risks

| 리스크 | 설명 | 관리 방법 |
|---|---|---|
| 테마 리스크 | 전력설비 테마 전체가 하락하면 PDF와 전략이 함께 하락 | 절대 drawdown과 PDF 대비 active return을 분리 관리 |
| 종목 집중 리스크 | 최종 전략은 PDF보다 특정 종목에 더 집중 | HHI, effective holdings, max weight 모니터링 |
| 거래비용ㆍ슬리피지 리스크 | 주간 리밸런싱과 평균 one-way turnover 21.71% | turnover limit, stress cost, ADV 제약 |
| Capacity 리스크 | 기준 capacity 3일 분할ㆍ10% ADVㆍ하위 10% 99.09억 원 | 1일 체결ㆍ5% ADVㆍ하위 5% 12.33억 원을 stress 기준으로 함께 관리 |
| 표본ㆍ과적합 리스크 | ETF 상장 이후 표본이 짧고 종목 수가 적음 | resampling, Monte Carlo, 향후 실시간 검증 |

## ETF AUM vs Strategy Capacity

KODEX AI전력핵심설비 ETF의 순자산총액이 **35,789.33억 원**이라고 해서, 본 active overlay 전략도 같은 규모로 바로 운용할 수 있다는 의미는 아닙니다. ETF 순자산총액은 이미 보유 중인 종목들의 평가금액과 설정ㆍ환매를 통해 형성된 펀드 규모이고, capacity는 리밸런싱 때 실제로 시장에서 사고팔아야 하는 주문금액이 유동성 안에 들어오는지를 보는 지표입니다.

최종 전략의 평균 리밸런싱 one-way turnover **21.71%**를 35,789.33억 원에 적용하면, 한 번의 리밸런싱에서 one-way 기준 약 **7,768억 원**, 매수+매도 합산 기준 약 **1조 5,536억 원**의 거래가 필요합니다. 이는 본 전략의 기준 capacity인 **3일 분할ㆍ10% ADVㆍ시계열 하위 10% 99.09억 원**과 비교해도 매우 큰 규모입니다. 더 보수적인 1일 체결ㆍ5% ADVㆍ시계열 하위 5% 기준은 **12.33억 원**입니다.

따라서 ETF 자체가 약 3.6조 원 규모로 존재하는 것은 가능하지만, 이 active overlay를 같은 규모로 매주 리밸런싱하는 것은 현재 유동성 가정에서는 가능하다고 보기 어렵습니다. 본 전략은 대형 ETF 자체를 대체하는 전략이 아니라, 소규모 active overlay 또는 랩/SMA 후보로 보는 것이 적절합니다.

## Practical Recommendation

본 전략은 대형 공모펀드처럼 큰 자금을 즉시 운용하기보다는, **소규모 active overlay 또는 내부 모델 포트폴리오**로 먼저 운용ㆍ검증하는 것이 적절합니다.

권장 운용 방향은 다음과 같습니다.

1. 기준 capacity는 약 99억 원이지만, 초기 운용규모는 보수 stress capacity를 고려해 약 10억~20억 원 내외에서 시작합니다.
2. 실제 체결 슬리피지와 turnover를 모니터링합니다.
3. 운용규모가 커질 경우 종목별 ADV 참여율 제약을 MVO에 직접 추가합니다.
4. 최소 6~12개월의 실시간 out-of-sample 성과를 축적한 뒤 확장 여부를 판단합니다.

## Investment View

이 전략은 확정적 alpha proof가 아니라, KODEX AI전력핵심설비 ETF의 관측 가능한 PDF 바스켓 안에서 컨센서스 신호를 이용한 **검증 기반 active overlay 후보**입니다. 백테스트와 resampling/Monte Carlo 결과는 유망하지만, 높은 성과와 함께 turnover, capacity, 종목 집중도라는 실무 제약이 존재합니다.

