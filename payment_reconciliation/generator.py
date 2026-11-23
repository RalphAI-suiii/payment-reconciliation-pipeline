import csv
from datetime import date, timedelta
from pathlib import Path


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate_inputs(raw_dir: Path, batch_date: date) -> None:
    """Write deterministic source rows, including common reconciliation problems."""
    payment_columns = ["payment_id", "event_date", "amount_minor", "currency"]
    ledger_columns = ["ledger_entry_id", "payment_id", "posting_date", "amount_minor", "currency"]
    settlement_columns = [
        "settlement_id",
        "payment_id",
        "settlement_date",
        "gross_minor",
        "fee_minor",
        "net_minor",
        "currency",
    ]

    payments: list[dict[str, str]] = []
    ledger: list[dict[str, str]] = []
    settlements: list[dict[str, str]] = []

    for number in range(1, 13):
        payment_id = f"PAY-{batch_date:%Y%m%d}-{number:04d}"
        amount_minor = 1_000 + number * 137
        currency = "EUR" if number >= 9 else "USD"
        payments.append(
            {
                "payment_id": payment_id,
                "event_date": batch_date.isoformat(),
                "amount_minor": str(amount_minor),
                "currency": currency,
            }
        )

        if number != 2:
            ledger.append(
                {
                    "ledger_entry_id": f"LED-{number:04d}",
                    "payment_id": payment_id,
                    "posting_date": batch_date.isoformat(),
                    "amount_minor": str(amount_minor),
                    "currency": currency,
                }
            )

        if number != 3:
            gross_minor = amount_minor + (25 if number == 4 else 0)
            fee_minor = number * 5
            net_minor = gross_minor - fee_minor + (1 if number == 6 else 0)
            settlement_currency = currency
            settlement_date = batch_date
            if number == 5:
                settlement_currency = "EUR" if currency == "USD" else "USD"
            if number == 7:
                settlement_date = batch_date + timedelta(days=1)
            settlements.append(
                {
                    "settlement_id": f"SET-{number:04d}",
                    "payment_id": payment_id,
                    "settlement_date": settlement_date.isoformat(),
                    "gross_minor": str(gross_minor),
                    "fee_minor": str(fee_minor),
                    "net_minor": str(net_minor),
                    "currency": settlement_currency,
                }
            )

    # One exact redelivery and one malformed source row exercise dedupe and quarantine.
    payments.append(payments[0].copy())
    payments.append(
        {
            "payment_id": "PAY-BAD-ROW",
            "event_date": batch_date.isoformat(),
            "amount_minor": "not-an-integer",
            "currency": "USD",
        }
    )

    _write_csv(raw_dir / "payments.csv", payment_columns, payments)
    _write_csv(raw_dir / "ledger.csv", ledger_columns, ledger)
    _write_csv(raw_dir / "settlements.csv", settlement_columns, settlements)

