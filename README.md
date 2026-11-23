# Payment Reconciliation Pipeline

A small nightly batch pipeline that reconciles synthetic payment processor records, internal ledger entries, and settlement records. It is designed to show the core data engineering work clearly: contracts, validation, deduplication, deterministic matching, exceptions, repeatable runs, and a daily report.

**All records are synthetic.** This project does not connect to a fintech company, process real payments, or use AI.

## Architecture

```mermaid
flowchart TD
    A["Nightly batch starts"] --> B["Generate synthetic input files"]
    B --> C["Processor payment CSV"]
    B --> D["Internal ledger CSV"]
    B --> E["Settlement CSV"]

    C --> F["Keep raw batch inputs"]
    D --> F
    E --> F

    F --> G{"Headers and row values valid?"}
    G -- "Invalid row" --> Q["Quarantine row with reason"]
    G -- "Valid" --> H["Normalize fields and remove duplicate rows"]
    H --> I["Match deterministically by payment_id"]
    I --> J{"Amounts, currencies, dates, and fee math agree?"}
    J -- "Yes" --> K["Write matched.csv"]
    J -- "No" --> X["Write exceptions.csv"]

    K --> R["Write daily report.json"]
    X --> R
    Q --> R
    R --> S["GitHub Actions saves an output artifact"]
```

## What the batch does

1. Creates three repeatable CSV inputs for a batch date.
2. Checks required headers and validates required values, dates, currencies, and integer amounts. A missing required header fails the batch; invalid individual rows are written to quarantine.
3. Trims whitespace, uppercases currency codes, and removes identical normalized rows within each source.
4. Matches records by `payment_id` and checks payment and ledger amounts, currency agreement, settlement date, and `gross_minor - fee_minor = net_minor`.
5. Writes matched records, exceptions, quarantined rows, and a JSON quality report.

Matching is deterministic. Missing, ambiguous, late-dated, and mismatched records receive named exception reasons for review. The pipeline does not guess a match.

## Data contracts

| Input | Record grain | Required fields |
| --- | --- | --- |
| `payments.csv` | One processor payment | `payment_id`, `event_date`, `amount_minor`, `currency` |
| `ledger.csv` | One ledger entry | `ledger_entry_id`, `payment_id`, `posting_date`, `amount_minor`, `currency` |
| `settlements.csv` | One settlement record | `settlement_id`, `payment_id`, `settlement_date`, `gross_minor`, `fee_minor`, `net_minor`, `currency` |

`payment_id` is the shared matching key. Amounts are integer minor units; the generator uses USD and EUR, which both have two decimal places. Dates use ISO `YYYY-MM-DD` format. Extra named columns are ignored; missing required columns stop the batch.

## Outputs

Each run writes under `data/output/<batch-date>/`:

- `matched.csv` — payments that passed every matching rule.
- `exceptions.csv` — payments with one or more reconciliation reasons.
- `quarantine.csv` — invalid source rows and their validation reasons.
- `report.json` — source counts, duplicates removed, quarantine count, match and exception counts, and matched or unmatched totals by currency.

Generated inputs are kept under `data/raw/<batch-date>/`. Both data directories are ignored by Git. Running the same batch date regenerates the same synthetic rows and replaces that date's local files; it does not append duplicate output.

## Run locally

Requires Python 3.12 or newer. The pipeline uses only the Python standard library; no package installation is needed.

```bash
python -m payment_reconciliation --batch-date 2026-11-23
```

Omit `--batch-date` to use the computer's local date:

```bash
python -m payment_reconciliation
```

The command prints a short summary. Open the CSV files and `report.json` in the matching `data/output/<batch-date>/` folder to inspect the results.

## Nightly automation

`.github/workflows/nightly-reconciliation.yml` runs the synthetic batch daily at midnight in the Philippines (16:00 UTC) and can also be started manually from the Actions tab. GitHub scheduled runs use UTC and may be delayed during busy periods, so this is a portfolio demonstration rather than a guaranteed production schedule. The workflow uploads the report files as an artifact for seven days; it does not commit generated data to the repository.

## Repository structure

```text
.
├── .github/
│   └── workflows/
│       └── nightly-reconciliation.yml
├── payment_reconciliation/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── generator.py
│   └── pipeline.py
├── .gitignore
└── README.md
```

## Scope and limitations

- Every row is synthetic; generated exception rates do not describe real fintech operations.
- The demo models successful payment captures only and matches on an exact shared `payment_id`.
- No FX conversion, provider API, warehouse, dashboard, or cross-day lookback for late arrivals is implemented. A settlement dated after the current batch date is flagged for review.
- Fee validation checks the arithmetic relationship between gross, fee, and net. There is no provider-specific fee schedule to compare against.
- The exception CSV is a review queue, not a user interface or an automated approval process.
- The scheduled workflow has no alerting or production SLA. Automated tests are a later milestone; the first version demonstrates the runnable data flow and row-level checks.

AI is intentionally out of scope. The matching rules are visible and explainable, which is the right baseline before considering any model-assisted exception triage.

## README references

These public data engineering project READMEs informed the organization of this document. Their wording and implementation were not copied:

- [AWS Ecommerce Data Platform](https://github.com/5H13LD2/aws-rds-pipeline)
- [Financial transaction data pipeline](https://github.com/Adetlo/txn-data-pipeline)
- [Data quality reconciliation framework](https://github.com/KiranReddy-data/data-quality-reconciliation-framework)

