# Try Rowstead with synthetic data

The panel's **Try a sample** action loads these scenarios without downloading a file.
You can also upload one of the CSV files from this directory.

| File | Source | Expected result |
|---|---|---|
| `registry-success.csv` | Registry API | 3 successful records |
| `registry-issues.csv` | Registry API | 5 succeeded, 1 missing, 1 invalid, 1 failed |
| `browser-calculator.csv` | Browser calculator | 3 succeeded; totals 44.46, 96.00, 161.68 |

Map the `identifier` field to the `identifier` column. The calculator also maps
`quantity`, `unit_price` and `discount` to the matching columns. Discount is a number
from 0 to 100 (5 means 5%). The `notes` column does not need mapping and remains in
the exported file.

In the issues sample, `RATE-ONCE` and `ERROR-ONCE` succeed on their second attempt.
`MISSING` represents a missing record, `BAD VALUE` is an invalid identifier, and
`ALWAYS-ERROR` fails after three attempts. A repeated `BF-0001` stays a separate row.
**Completed with issues is expected for this scenario.** Retrying failed rows does
not make a permanently failing synthetic source succeed.
