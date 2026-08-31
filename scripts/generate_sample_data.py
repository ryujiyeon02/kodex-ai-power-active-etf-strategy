"""Generate synthetic examples for the private input schemas.

The values are artificial and are not used in the published backtest results.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "sample_data"
STOCKS = [("000001", "SAMPLE_A"), ("000002", "SAMPLE_B"), ("000003", "SAMPLE_C")]


def write_csv(name: str, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / name).open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    dates = [date(2025, 1, 2) + timedelta(days=i) for i in range(5)]
    pdf_rows: list[dict[str, object]] = []
    price_adv_rows: list[dict[str, object]] = []
    consensus_rows: list[dict[str, object]] = []
    etf_rows: list[dict[str, object]] = []

    for i, current in enumerate(dates):
        for j, (code, name) in enumerate(STOCKS):
            pdf_rows.append(
                {
                    "date": current.isoformat(),
                    "etf_code": "SAMPLE_ETF",
                    "etf_name": "SAMPLE ETF",
                    "stock_code": code,
                    "stock_isin": f"SAMPLE_ISIN_{j + 1}",
                    "market_id": "STK",
                    "security_group": "STOCK",
                    "stock_name": name,
                    "cu1_shares": 1000 + j * 100,
                    "valuation_amount": 100_000_000 + j * 10_000_000,
                    "weight": round([0.4, 0.35, 0.25][j], 4),
                    "source": "synthetic",
                }
            )
            price_adv_rows.append(
                {
                    "date": current.isoformat(),
                    "stock_code": code,
                    "stock_name": name,
                    "close": 100 + j * 10 + i,
                    "trading_value": 1_000_000_000 + j * 100_000_000,
                }
            )
            consensus_rows.append(
                {
                    "date": current.isoformat(),
                    "stock_code": code,
                    "stock_name": name,
                    "eps_forward": 5_000 + j * 250 + i * 10,
                    "target_price": 130 + j * 10,
                    "rating_point": 4.0 - j * 0.2,
                }
            )
        etf_rows.append(
            {
                "date": current.isoformat(),
                "etf_code": "SAMPLE_ETF",
                "etf_name": "SAMPLE ETF",
                "etf_close": 10_000 + i * 20,
                "nav": 10_005 + i * 20,
                "etf_volume": 100_000 + i * 1_000,
                "etf_trading_value": 1_000_000_000 + i * 10_000_000,
                "aum": 50_000_000_000,
                "underlying_index_name": "SAMPLE INDEX",
                "underlying_index_close": 1_000 + i * 2,
            }
        )

    write_csv(
        "pdf_history_sample.csv",
        [
            "date", "etf_code", "etf_name", "stock_code", "stock_isin", "market_id",
            "security_group", "stock_name", "cu1_shares", "valuation_amount", "weight", "source",
        ],
        pdf_rows,
    )
    write_csv(
        "price_adv_sample.csv",
        ["date", "stock_code", "stock_name", "close", "trading_value"],
        price_adv_rows,
    )
    write_csv(
        "consensus_sample.csv",
        ["date", "stock_code", "stock_name", "eps_forward", "target_price", "rating_point"],
        consensus_rows,
    )
    write_csv(
        "etf_daily_sample.csv",
        [
            "date", "etf_code", "etf_name", "etf_close", "nav", "etf_volume",
            "etf_trading_value", "aum", "underlying_index_name", "underlying_index_close",
        ],
        etf_rows,
    )


if __name__ == "__main__":
    main()
