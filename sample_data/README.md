# 합성 샘플 데이터

공개 저장소에는 원본 가격·PDF·컨센서스·지수 데이터가 포함되지 않습니다. 이 폴더는 정규화 이후의 논리 스키마를 설명하기 위한 합성 예시입니다.

```bash
python scripts/generate_sample_data.py
```

| 샘플 | 설명 |
| --- | --- |
| `pdf_history_sample.csv` | 날짜별 ETF PDF 구성종목과 비중 |
| `price_adv_sample.csv` | 종목별 가격과 거래대금 |
| `consensus_sample.csv` | EPS 전망, 목표주가, 투자의견 |
| `etf_daily_sample.csv` | ETF 종가, NAV, 거래량, AUM, 기초지수 |

샘플 값은 인위적으로 생성했으며 공개된 성과표와 차트에는 사용하지 않았습니다. 실제 재실행에는 이용 권한을 확보한 원본을 `input/`에 준비해야 합니다.
