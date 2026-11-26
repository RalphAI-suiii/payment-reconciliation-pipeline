import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


CONTRACTS = {
    "payments": {
        "file": "payments.csv",
        "columns": ["payment_id", "event_date", "amount_minor", "currency"],
        "integer_fields": ["amount_minor"],
        "date_fields": ["event_date"],
    },
    "ledger": {
        "file": "ledger.csv",
        "columns": ["ledger_entry_id", "payment_id", "posting_date", "amount_minor", "currency"],
        "integer_fields": ["amount_minor"],
        "date_fields": ["posting_date"],
    },
    "settlements": {
        "file": "settlements.csv",
        "columns": [
            "settlement_id",
            "payment_id",
            "settlement_date",
            "gross_minor",
            "fee_minor",
            "net_minor",
            "currency",
        ],
        "integer_fields": ["gross_minor", "fee_minor", "net_minor"],
        "date_fields": ["settlement_date"],
    },
}

MATCHED_COLUMNS = [
    "payment_id",
    "event_date",
    "payment_amount_minor",
    "currency",
    "ledger_entry_id",
    "posting_date",
    "settlement_id",
    "settlement_date",
    "gross_minor",
    "fee_minor",
    "net_minor",
]
EXCEPTION_COLUMNS = [
    "payment_id",
    "exception_grain",
    "exception_reasons",
    "payment_amount_minor",
    "payment_currency",
    "ledger_entry_id",
    "settlement_id",
    "source",
    "source_record_id",
    "source_row",
    "source_currency",
    "source_amount_minor",
    "source_gross_minor",
    "source_fee_minor",
    "source_net_minor",
]
QUARANTINE_COLUMNS = ["source", "source_row", "payment_id", "reason"]


def _read_rows(path: Path, required_columns: list[str]) -> list[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input file is missing: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        duplicates = sorted(name for name, count in Counter(headers).items() if count > 1)
        if duplicates:
            names = ", ".join(repr(name) for name in duplicates)
            raise ValueError(f"{path.name} has duplicate column names: {names}")
        missing = sorted(set(required_columns) - set(headers))
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {', '.join(missing)}")
        return [(reader.line_num, row) for row in reader]


def _normalize_and_validate(
    source: str,
    rows: list[tuple[int, dict[str, Any]]],
    columns: list[str],
    integer_fields: list[str],
    date_fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    valid: list[dict[str, Any]] = []
    quarantined: list[dict[str, str]] = []

    for line_number, raw_row in rows:
        row = {key: (value.strip() if value is not None else "") for key, value in raw_row.items() if key}
        reasons: list[str] = []
        if raw_row.get(None):
            reasons.append("extra_values_without_headers")

        for column in columns:
            if not row.get(column, ""):
                reasons.append(f"missing_{column}")

        for column in integer_fields:
            if row.get(column):
                try:
                    amount = int(row[column])
                    if amount < 0:
                        raise ValueError
                    row[column] = amount
                except ValueError:
                    reasons.append(f"invalid_{column}")

        for column in date_fields:
            if row.get(column):
                try:
                    if date.fromisoformat(row[column]).isoformat() != row[column]:
                        raise ValueError
                except ValueError:
                    reasons.append(f"invalid_{column}")

        if row.get("currency"):
            if not re.fullmatch(r"[A-Za-z]{3}", row["currency"]):
                reasons.append("invalid_currency")
            else:
                row["currency"] = row["currency"].upper()

        if reasons:
            quarantined.append(
                {
                    "source": source,
                    "source_row": str(line_number),
                    "payment_id": row.get("payment_id", ""),
                    "reason": ";".join(sorted(set(reasons))),
                }
            )
        else:
            row["_source_row"] = str(line_number)
            valid.append(row)

    return valid, quarantined


def _remove_exact_duplicates(
    rows: list[dict[str, Any]], columns: list[str]
) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for row in rows:
        key = tuple(row[column] for column in columns)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
            unique.append(row)
    return unique, duplicates


def _load_source(raw_dir: Path, source: str) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, int]]:
    contract = CONTRACTS[source]
    raw_rows = _read_rows(raw_dir / contract["file"], contract["columns"])
    valid, quarantined = _normalize_and_validate(
        source,
        raw_rows,
        contract["columns"],
        contract["integer_fields"],
        contract["date_fields"],
    )
    unique, duplicates = _remove_exact_duplicates(valid, contract["columns"])
    metrics = {
        "raw_rows": len(raw_rows),
        "accepted_rows": len(unique),
        "duplicates_removed": duplicates,
        "quarantined_rows": len(quarantined),
    }
    return unique, quarantined, metrics


def _index_by_payment_id(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        indexed[row["payment_id"]].append(row)
    return indexed


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def reconcile_batch(raw_dir: Path, output_dir: Path, batch_date: date) -> dict[str, Any]:
    """Validate source files, reconcile payment IDs, and replace one batch's outputs."""
    loaded: dict[str, list[dict[str, Any]]] = {}
    quarantined: list[dict[str, str]] = []
    source_metrics: dict[str, dict[str, int]] = {}
    for source in CONTRACTS:
        loaded[source], rejected, source_metrics[source] = _load_source(raw_dir, source)
        quarantined.extend(rejected)

    ledgers = _index_by_payment_id(loaded["ledger"])
    settlements = _index_by_payment_id(loaded["settlements"])
    payments = _index_by_payment_id(loaded["payments"])
    matched: list[dict[str, Any]] = []
    payment_exceptions: list[dict[str, Any]] = []

    for payment_id in sorted(payments):
        payment_rows = payments[payment_id]
        payment = payment_rows[0]
        reasons: list[str] = []
        ledger_rows = ledgers.get(payment_id, [])
        settlement_rows = settlements.get(payment_id, [])

        if len(payment_rows) > 1:
            reasons.append("multiple_payment_records")
        if not ledger_rows:
            reasons.append("missing_ledger_entry")
        elif len(ledger_rows) > 1:
            reasons.append("multiple_ledger_entries")
        else:
            ledger = ledger_rows[0]
            if ledger["currency"] != payment["currency"]:
                reasons.append("ledger_currency_mismatch")
            elif ledger["amount_minor"] != payment["amount_minor"]:
                reasons.append("ledger_amount_mismatch")

        if not settlement_rows:
            reasons.append("missing_settlement")
        elif len(settlement_rows) > 1:
            reasons.append("multiple_settlements")
        else:
            settlement = settlement_rows[0]
            if settlement["currency"] != payment["currency"]:
                reasons.append("settlement_currency_mismatch")
            elif settlement["gross_minor"] != payment["amount_minor"]:
                reasons.append("settlement_gross_mismatch")
            if date.fromisoformat(settlement["settlement_date"]) > batch_date:
                reasons.append("settlement_after_batch_date")
            if settlement["gross_minor"] - settlement["fee_minor"] != settlement["net_minor"]:
                reasons.append("fee_arithmetic_mismatch")

        if reasons:
            ledger = ledger_rows[0] if len(ledger_rows) == 1 else {}
            settlement = settlement_rows[0] if len(settlement_rows) == 1 else {}
            payment_exceptions.append(
                {
                    "payment_id": payment_id,
                    "exception_grain": "payment",
                    "exception_reasons": ";".join(reasons),
                    "payment_amount_minor": payment["amount_minor"],
                    "payment_currency": payment["currency"],
                    "ledger_entry_id": ledger.get("ledger_entry_id", ""),
                    "settlement_id": settlement.get("settlement_id", ""),
                }
            )
        else:
            ledger = ledger_rows[0]
            settlement = settlement_rows[0]
            matched.append(
                {
                    "payment_id": payment_id,
                    "event_date": payment["event_date"],
                    "payment_amount_minor": payment["amount_minor"],
                    "currency": payment["currency"],
                    "ledger_entry_id": ledger["ledger_entry_id"],
                    "posting_date": ledger["posting_date"],
                    "settlement_id": settlement["settlement_id"],
                    "settlement_date": settlement["settlement_date"],
                    "gross_minor": settlement["gross_minor"],
                    "fee_minor": settlement["fee_minor"],
                    "net_minor": settlement["net_minor"],
                }
            )

    orphan_exceptions: list[dict[str, Any]] = []
    orphan_totals: dict[str, dict[str, Counter]] = {
        "ledger": defaultdict(Counter),
        "settlements": defaultdict(Counter),
    }
    for source, record_id_field in (("ledger", "ledger_entry_id"), ("settlements", "settlement_id")):
        for row in loaded[source]:
            if row["payment_id"] in payments:
                continue
            currency = row["currency"]
            exception = {
                "payment_id": row["payment_id"],
                "exception_grain": "source_record",
                "exception_reasons": "orphan_source_record",
                "source": source,
                "source_record_id": row[record_id_field],
                "source_row": row["_source_row"],
                "source_currency": currency,
            }
            for field in CONTRACTS[source]["integer_fields"]:
                exception[f"source_{field}"] = row[field]
                orphan_totals[source][currency][field] += row[field]
            orphan_exceptions.append(exception)

    exceptions = payment_exceptions + orphan_exceptions
    matched_totals = Counter()
    unmatched_totals = Counter()
    exception_reason_counts = Counter()
    quarantine_reason_counts = {source: Counter() for source in CONTRACTS}
    for row in matched:
        matched_totals[row["currency"]] += row["payment_amount_minor"]
    for row in payment_exceptions:
        unmatched_totals[row["payment_currency"]] += row["payment_amount_minor"]
    for row in exceptions:
        exception_reason_counts.update(row["exception_reasons"].split(";"))
    for row in quarantined:
        quarantine_reason_counts[row["source"]].update(row["reason"].split(";"))

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "matched.csv", MATCHED_COLUMNS, matched)
    _write_csv(output_dir / "exceptions.csv", EXCEPTION_COLUMNS, exceptions)
    _write_csv(output_dir / "quarantine.csv", QUARANTINE_COLUMNS, quarantined)

    report = {
        "batch_date": batch_date.isoformat(),
        "batch_id": f"synthetic-{batch_date.isoformat()}",
        "status": "completed_with_exceptions" if exceptions or quarantined else "completed",
        "source_metrics": source_metrics,
        "matched_count": len(matched),
        "exception_count": len(exceptions),
        "payment_exception_count": len(payment_exceptions),
        "orphan_source_exception_count": len(orphan_exceptions),
        "orphan_source_totals_by_source_and_currency": orphan_totals,
        "quarantined_count": len(quarantined),
        "exception_reason_counts": dict(sorted(exception_reason_counts.items())),
        "quarantine_reason_counts": {
            source: dict(sorted(counts.items()))
            for source, counts in sorted(quarantine_reason_counts.items())
        },
        "matched_amount_minor_by_currency": dict(sorted(matched_totals.items())),
        "unmatched_amount_minor_by_currency": dict(sorted(unmatched_totals.items())),
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report

