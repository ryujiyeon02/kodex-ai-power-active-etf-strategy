## Appendix. 최종 전략 Metrics 산출

아래 지표는 최종 전략 `consensus_active_mvo_te20_ra1_min1` 기준입니다. 수익률은 비용 반영 후 일별 수익률을 사용했고, benchmark는 KRX PDF 비중 복제 포트폴리오입니다.

| 지표 | 최종값 | 의미 | 실무적 해석 |
|---|---:|---|---|
| Average Holding Periods | 21.2거래일 / 약 30.7일 | 연환산 one-way turnover의 역수로 본 평균 보유기간입니다. | 주간 리밸런싱이지만 모든 비중을 매주 갈아엎는 구조는 아니며, 평균적으로 약 21.2거래일마다 보유비중이 한 바퀴 도는 수준입니다. |
| Maximum Strategy Capacity | 3일 분할 x 10% ADV x 시계열 하위 10% 99.09억 원 | 리밸런싱 주문이 직전 20거래일 평균 거래대금의 일정 비율을 넘지 않는 운용규모 한도입니다. | 발표 기준 capacity는 3일 분할 체결, 하루 10% ADV 참여율, 시계열 하위 10% 기준 99.09억 원입니다. 1일 체결ㆍ5% ADVㆍ시계열 하위 5% 기준 12.33억 원과 3일 분할ㆍ5% ADVㆍ시계열 하위 5% 기준 36.98억 원은 더 보수적인 참고값입니다. 3일 분할ㆍ10% ADVㆍ시계열 하위 5% 기준은 73.97억 원입니다. |
| Turnover and Costs | 리밸런싱 평균 one-way 21.71%, 매매비용 -6.14%p, 총보수ㆍ비용 -0.80%p | Turnover는 리밸런싱 때 목표비중으로 이동하기 위해 사고파는 비중 변화입니다. 비용은 매매비용과 펀드 총보수ㆍ비용을 분리해 반영했습니다. | 평균 리밸런싱 one-way turnover는 21.71%이고, 최대값은 약 30%로 turnover limit 근처입니다. 비용 반영 누적수익률은 비용 미반영 대비 -54.97%p 낮아집니다. |
| Sharpe Ratio | 3.937 | 성과표의 Sharpe는 CAGR을 연환산 변동성으로 나눈 값입니다. | 최종 전략은 누적수익률 664.06%, 연환산 변동성 55.78% 기준 Sharpe 3.94입니다. 단, 표본이 짧으므로 PSR/DSR과 함께 봅니다. |
| Probabilistic Sharpe Ratio | PSR(SR*>0) 99.92%, PSR(SR*>1) 96.55%, PSR(SR*>2) 68.62% | 관측된 표본 Sharpe가 특정 기준 Sharpe를 초과할 확률을 왜도ㆍ첨도를 반영해 계산한 값입니다. | 표본 연율 Sharpe 2.36 기준, 장기 Sharpe가 1을 넘을 가능성은 96.55%로 추정됩니다. PSR은 미래 보장이 아니라 짧은 표본의 Sharpe 신뢰도 점검입니다. |
| Deflated Sharpe Ratio | 91.65% (trial count 15) | 여러 전략 후보를 테스트했을 때 우연히 높아진 Sharpe를 할인한 확률입니다. | 현재 발표에 남긴 후보/민감도 조합 15개를 고려해 기대 최대 Sharpe 기준을 1.33로 높이면 DSR은 91.65%입니다. 여러 후보 중 고른 효과를 반영해도 Sharpe가 완전히 우연이라고 보기는 어렵지만, trial count 정의에 따라 값이 달라지므로 scenario table과 함께 해석합니다. |
| Drawdown | -32.92% (2024-09-06) | 누적 wealth가 이전 고점 대비 얼마나 하락했는지의 최대값입니다. | 최대낙폭은 -32.92%로, 수익률은 높지만 테마 ETF 특유의 하락위험은 큽니다. 따라서 이 전략은 저위험 전략이 아니라 active overlay 전략으로 해석해야 합니다. |
| Tracking Error | 17.90% | 전략 일별 수익률에서 PDF 벤치마크 일별 수익률을 뺀 active return의 표준편차를 연율화한 값입니다. | 실현 TE는 17.90%, IR은 0.843, PDF 상관계수는 0.947입니다. TE는 패시브 복제 오차가 아니라 초과성과를 얻기 위해 사용한 active risk 예산입니다. |
| Herfindahl-Hirschman Index | latest HHI 0.261, effective holdings 3.84 | 종목별 비중 제곱합입니다. 1/HHI는 실질적으로 몇 종목에 분산된 것처럼 보이는지 보여줍니다. | 최신 전략 HHI는 0.261, PDF HHI는 0.147입니다. 전략의 최신 effective holdings는 3.84개로 PDF 6.82개보다 낮아, 초과성과와 함께 집중위험이 커졌습니다. |

### 지표별 핵심 해석

- **Average Holding Periods**: turnover가 높을수록 평균 보유기간은 짧아집니다. 최종 전략은 주간 리밸런싱이므로 월간 전략보다 빠르게 컨센서스 변화를 반영하지만, 비용과 capacity를 반드시 같이 봐야 합니다.
- **Maximum Strategy Capacity**: 성과가 좋아도 거래대금이 작은 종목을 크게 사고팔아야 하면 실제 운용규모는 제한됩니다. 본문 기준은 3일 분할 체결, 하루 10% ADV 참여율, 시계열 하위 10% capacity이고, 1일 체결 또는 5% ADV 기준은 더 보수적인 참고 시나리오입니다.
- **Turnover and Costs**: turnover는 신호를 얼마나 자주 비중으로 옮기는지 보여주고, 비용은 그 대가입니다. 최종 성과는 매매비용과 펀드 총보수ㆍ비용을 반영한 값으로 설명해야 합니다.
- **Sharpe / PSR / DSR**: Sharpe는 위험 대비 성과, PSR은 Sharpe의 표본 신뢰도, DSR은 여러 후보를 테스트한 효과를 감안한 보수적 Sharpe 검증입니다.
- **Drawdown**: 최종 전략은 초과성과가 있지만 MDD가 작지 않습니다. 저위험 절대수익 전략이 아니라 테마 ETF 위에서 active risk를 쓰는 전략입니다.
- **Tracking Error**: 여기서 TE는 공식 ETF 추적오차가 아니라 PDF benchmark 대비 active return의 변동성입니다. active 전략에서는 TE 자체보다 IR과 함께 해석합니다.
- **HHI**: HHI가 높아질수록 특정 종목에 집중된 포트폴리오입니다. 최종 전략은 PDF보다 effective holdings가 낮아졌으므로 초과성과와 함께 집중위험도 커졌습니다.

### Deflated Sharpe Ratio의 조합 수 기준

DSR에서 가장 중요한 선택은 `trial count`, 즉 몇 개의 전략 후보를 비교했다고 볼 것인지입니다. 이 숫자는 정답이 하나로 정해져 있다기보다, 연구자가 실제로 어떤 후보군 안에서 최종 전략을 골랐는지 투명하게 정해야 합니다.

이번 프로젝트에서는 다음 원칙을 사용했습니다.

```text
1. Resampling / Monte Carlo 경로는 trial로 세지 않는다.
   이미 선택된 전략의 경로 안정성 검증이지, 새로운 전략 후보가 아니기 때문입니다.

2. 개별 종목이나 개별 날짜의 IC 관측치도 trial로 세지 않는다.
   이들은 전략 후보가 아니라 신호 검증 단위입니다.

3. 실제로 최종 전략 선택에 영향을 줄 수 있었던 비중화 방식과 운용 파라미터 조합을 trial로 본다.
   예: 단순 점수 틸트, 공격형 점수 틸트, MVO, TE budget, max weight, 비용, 리밸런싱, factor weight 설정.
```

본문 기준 DSR은 **reported_spec_rows_conservative**를 사용했습니다. 이는 MVO 적용 전 2개 후보와 현재 발표/README에 남긴 robustness 설정 13개를 모두 포함한 **15개 조합**입니다. 같은 최종 경로가 여러 sensitivity 항목에 중복 등장하더라도 모두 세기 때문에 다소 보수적인 기준입니다.

여기서 중요한 구분은, resampling이나 Monte Carlo에서 만든 2,000개 가상 경로는 DSR의 trial count에 넣지 않는다는 점입니다. 그 경로들은 이미 선택한 최종 전략의 수익률을 흔들어 보는 안정성 검증이지, 새로 비교한 전략 후보가 아니기 때문입니다. DSR의 trial은 '최종 전략을 고르기 전에 실제로 비교할 수 있었던 전략 설계 조합'입니다.

| scenario | trial count | DSR | 표본 Sharpe | 기대 최대 Sharpe | 기준 설명 |
|---|---:|---:|---:|---:|---|
| core_candidate_set | 3 | 98.93% | 2.36 | 0.64 | MVO 적용 전 단순 점수 틸트, MVO 적용 전 공격형 점수 틸트, 최종 Consensus Active MVO의 3개 핵심 후보만 trial로 간주 |
| unique_return_paths_current | 10 | 94.27% | 2.36 | 1.18 | MVO 적용 전 2개 후보와, 최종 robustness 표에서 성과 경로가 실제로 다른 8개 MVO 경로를 합산 |
| reported_spec_rows_conservative | 15 | 91.65% | 2.36 | 1.33 | MVO 적용 전 2개 후보와, 발표/README에 남긴 robustness 설정 13개 행을 모두 trial로 간주. 동일 경로 중복도 포함하므로 보수적 |
| broad_stress_legacy | 26 | 87.27% | 2.36 | 1.51 | 이전 실험 과정에서 검토했던 더 넓은 후보 수를 stress trial count로 사용. 현재 본문 전략 선택 기준은 아니며 민감도 점검용 |

해석은 다음과 같습니다.

- trial count를 3개 핵심 후보만으로 보면 DSR은 더 높게 나옵니다.
- 중복 경로를 제거한 현재 후보군 기준은 10개입니다.
- 본문에서는 더 보수적으로 15개를 사용했습니다.
- 26개 stress count를 적용해도 DSR은 80%대 후반으로 유지됩니다.

따라서 DSR은 'Sharpe가 여러 조합을 돌리다 우연히 높아진 것일 수 있다'는 비판을 완전히 없애는 도구는 아니지만, 현재 공개한 후보군 기준에서는 최종 Sharpe가 단순 우연이라고 보기 어렵다는 보조 근거로 사용할 수 있습니다.

### 추가 산출 파일

| 파일 | 내용 |
|---|---|
| `output/final_metrics_summary.csv` | 지표별 원자료 요약 |
| `output/final_metrics_summary_pretty.csv` | 발표용 지표 설명 표 |
| `output/final_metrics_detail.csv` | turnover, DSR, HHI 세부 수치 |
| `output/deflated_sharpe_ratio_scenarios.csv` | DSR trial count 시나리오별 원자료 |
| `output/deflated_sharpe_ratio_scenarios_pretty.csv` | DSR trial count 시나리오별 발표용 표 |
| `output/chart_deflated_sharpe_ratio_scenarios.png` | trial count 기준별 DSR 민감도 그래프 |
| `output/final_hhi_timeseries.csv` | 날짜별 전략/PDF HHI 및 effective holdings |
| `output/chart_final_hhi_timeseries.png` | 전략/PDF HHI 변화 |
| `output/chart_final_effective_holdings.png` | 전략/PDF effective holdings 변화 |

### DSR 그래프 해석

DSR 그래프는 `trial count`, 즉 몇 개의 전략 후보를 비교했다고 볼 것인지에 따라 Deflated Sharpe Ratio가 어떻게 달라지는지 보여줍니다. x축은 trial count 기준별 시나리오이고, y축은 DSR입니다. 와인색 막대는 본문에서 사용한 기준입니다.

읽는 방법은 다음과 같습니다.

- trial count가 커질수록 DSR은 낮아집니다. 여러 조합을 많이 시도할수록 우연히 높은 Sharpe가 나올 가능성이 커지기 때문입니다.
- 핵심 후보 3개만 보면 DSR은 98.93%로 매우 높습니다.
- 본문 기준인 15개 조합에서는 91.65%입니다.
- 더 보수적인 26개 stress 기준에서도 87.27%입니다.
- 50% 기준선보다 충분히 높기 때문에, 현재 공개한 후보군 안에서는 최종 Sharpe가 단순한 후보 선택 운으로만 나온 것이라고 보기는 어렵습니다.

다만 이 그래프도 미래 성과를 보장하는 증거는 아닙니다. 정확한 발표 표현은 **'과최적화 가능성을 낮춰 보는 보조 진단'**입니다.

![DSR trial count 민감도](output/chart_deflated_sharpe_ratio_scenarios.png)

### HHI 그래프 해석

HHI는 종목별 비중의 제곱합입니다.

```text
HHI = sum_i weight_i^2
Effective holdings = 1 / HHI
```

즉 HHI가 높을수록 특정 종목에 비중이 몰려 있고, `1 / HHI`로 계산한 effective holdings는 실질적으로 몇 종목에 분산된 것처럼 보이는지를 나타냅니다.

첫 번째 HHI 그래프에서는 최종 전략의 HHI가 PDF보다 대체로 높습니다. 이는 전략이 PDF를 그대로 복제한 것이 아니라, consensus score가 좋은 종목에 더 집중해서 초과성과를 만들었다는 뜻입니다.

최신 시점 기준으로 전략 HHI는 0.261, PDF HHI는 0.147입니다. 이를 effective holdings로 바꾸면 전략은 약 3.84개, PDF는 약 6.82개입니다.

따라서 해석은 양면적입니다.

- 긍정적 해석: 점수가 높은 종목에 집중했기 때문에 PDF 대비 초과성과가 커졌습니다.
- 리스크 해석: 실질 분산 종목 수가 줄어들었기 때문에 특정 종목의 급락이나 신호 오류에 더 민감해졌습니다.

발표에서는 **'초과성과는 공짜가 아니라, 더 높은 active concentration을 감수한 결과'**라고 설명하는 것이 안전합니다.

![최종 전략 HHI](output/chart_final_hhi_timeseries.png)

두 번째 effective holdings 그래프는 같은 내용을 더 직관적으로 보여줍니다. 선이 낮아질수록 포트폴리오가 소수 종목에 집중된다는 의미입니다. 최종 전략의 effective holdings가 PDF보다 낮게 유지되는 구간은, MVO가 컨센서스 점수가 높은 종목으로 비중을 몰아준 구간으로 해석하면 됩니다.

![최종 전략 effective holdings](output/chart_final_effective_holdings.png)
