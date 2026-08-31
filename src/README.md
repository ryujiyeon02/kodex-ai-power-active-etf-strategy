# src

ETF 복제, 데이터 패널 생성, 팩터 검증, active MVO, 비용/슬리피지, capacity, factsheet 산출 코드를 모은 폴더입니다.

핵심 실행 흐름은 다음입니다.

```text
build_model_panel_v2.py
-> benchmark_replication.py
-> active_experiment_runner.py
-> factsheet_diagnostics.py
-> final_metrics_diagnostics.py
-> resampling_monte_carlo_diagnostics.py
```

최종 전략은 `active_experiment_runner.py`의 `consensus_active_mvo_te20_ra1_min1`입니다.

