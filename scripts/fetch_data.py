import csv
import io
import json
import math
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = (
    "https://reports-public.ieso.ca/public/Demand/PUB_Demand.csv"
)

MAX_BYTES = 5_000_000
OUTPUT = Path("public/data/ontario.json")


def download():
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "OntarioDemandDashboard/1.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )

    with urlopen(request, timeout=45) as response:
        raw = response.read(MAX_BYTES + 1)

    if len(raw) > MAX_BYTES:
        raise ValueError("IESO report exceeded the download limit.")

    return raw.decode("utf-8-sig")


def parse_report(text):
    lines = text.splitlines()
    header_index = None
    report_created = None

    for index, line in enumerate(lines):
        columns = [
            value.strip().lstrip("\ufeff")
            for value in next(csv.reader([line]), [])
        ]

        if (
            "Date" in columns
            and "Hour" in columns
            and "Ontario Demand" in columns
        ):
            header_index = index
            break

        if "Created at" in line:
            report_created = (
                line.split("Created at", 1)[1]
                .split(",", 1)[0]
                .strip()
            )

    if header_index is None:
        raise ValueError("Expected IESO CSV columns were not found.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[header_index:]))
    )

    records = {}

    for raw in reader:
        row = {
            str(key).strip().lstrip("\ufeff"):
                value.strip() if isinstance(value, str) else value
            for key, value in raw.items()
            if key is not None
        }

        try:
            date_text = row["Date"]
            datetime.strptime(date_text, "%Y-%m-%d")

            hour = int(row["Hour"])
            demand_mw = float(row["Ontario Demand"])

            if not 1 <= hour <= 24:
                continue

            if not math.isfinite(demand_mw) or demand_mw < 0:
                continue

        except (KeyError, ValueError, TypeError):
            continue

        records[(date_text, hour)] = {
            "date": date_text,
            "hour": hour,
            "ontarioDemandMW": demand_mw,
        }

    rows = sorted(
        records.values(),
        key=lambda row: (row["date"], row["hour"]),
    )

    if not rows:
        raise ValueError("No valid Ontario demand records were found.")

    return {
        "region": "ON",
        "metric": "Ontario demand",
        "unit": "MW",
        "sourceName": "IESO Hourly Demand Report",
        "sourceUrl": SOURCE_URL,
        "reportCreated": report_created,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "latest": rows[-1],
        "history": rows[-48:],
    }


def main():
    payload = None

    for attempt in range(3):
        try:
            payload = parse_report(download())
            break

        except Exception as error:
            if attempt == 2:
                raise

            print(f"Fetch attempt {attempt + 1} failed: {error}")
            time.sleep(5 * (attempt + 1))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT.write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    latest = payload["latest"]

    print(
        f"Saved {OUTPUT}: "
        f"{latest['date']} hour {latest['hour']}, "
        f"{latest['ontarioDemandMW']} MW"
    )


if __name__ == "__main__":
    main()