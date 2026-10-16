"""Small synthetic fixtures for a successful first run and deliberate error review."""

import csv
import io


def sample_csv(adapter: str, scenario: str = "legacy") -> str:
    if adapter == "registry_demo":
        header = ["identifier", "notes"]
        rows = {
            "legacy": [
                ["BF-0001", "First company"],
                ["BF-0002", "Second company"],
                ["MISSING", "Missing record"],
                ["RATE-ONCE", "Recovers after retry"],
            ],
            "success": [
                ["BF-0001", "First company"],
                ["BF-0002", "Second company"],
                ["BF-0003", "Third company"],
            ],
            "issues": [
                ["BF-0001", "Standard record"],
                ["BF-0002", "Another record"],
                ["BF-0001", "Duplicate identifier stays a separate row"],
                ["RATE-ONCE", "429 first, then succeeds"],
                ["ERROR-ONCE", "500 first, then succeeds"],
                ["MISSING", "Expected missing record"],
                ["BAD VALUE", "Expected invalid identifier"],
                ["ALWAYS-ERROR", "Expected failure after three attempts"],
            ],
        }[scenario]
    elif adapter == "browser_demo" and scenario in {"legacy", "success"}:
        header = ["identifier", "quantity", "unit_price", "discount"]
        rows = [["BF-0001", 2, 19.5, 5], ["BF-0002", 10, 8, 0], ["BF-0003", 3, 49.9, 10]]
    else:
        raise ValueError("This sample is not available")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()
