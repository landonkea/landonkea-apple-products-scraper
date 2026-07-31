# ───────────────────────────────────────────────────────────────────
# GitHub Pages data generator
# ───────────────────────────────────────────────────────────────────
# Reads the daily_price_stats table and writes docs/data/daily_stats.json
# — the data file the GitHub Pages site (docs/index.html) fetches to
# draw the price trend charts. Runs once per scrape, after all
# searches finish.
# ───────────────────────────────────────────────────────────────────

import json
import os

from database import DailyPriceStat


def generate_pages_data(db, output_path: str = "docs/data/daily_stats.json") -> int:
    """
    Export all daily price stats to a JSON file for the GitHub Pages site.

    Output shape:
        {
          "MacBook Pro": {
            "M5 Max": [{"date": "2026-07-31", "min": 3008, "avg": 4656, "max": 7139, "count": 29}, ...],
            "M4 Max": [...],
            "M3 Max": [...]
          },
          "iPhone Pro Max": {
            "iPhone 17 Pro Max": [...],
            ...
          }
        }

    Args:
        db: Database session.
        output_path: Where to write the JSON file (created if missing).

    Returns:
        Total number of stat rows exported.
    """
    rows = db.query(DailyPriceStat).order_by(DailyPriceStat.date.asc()).all()

    data: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        product_group = data.setdefault(row.product_name, {})
        series = product_group.setdefault(row.group_key, [])
        series.append({
            "date": row.date,
            "min": row.min_price,
            "avg": row.avg_price,
            "max": row.max_price,
            "count": row.listing_count,
        })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return len(rows)
