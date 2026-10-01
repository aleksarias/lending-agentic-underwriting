"""Copy the tables the console may read from Databricks into a local DuckDB lake (a fixture for offline UI work).

Only objects the read-only "ui" role can see are copied: every table in ops, experiments, feature_registry and
production, plus curated.data_catalog, curated.field_lineage and labels.split_meta. Never raw data, holdout,
all-version labels or applicant-level curated tables.

Usage (reads Databricks as the harness identity from .env):
    uv run python scripts/export_console_fixture.py --out .local_lake/console_fixture
Then run the console on the fixture:
    LAU_BACKEND=local LAU_LOCAL_LAKE=.local_lake/console_fixture uv run lau console
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UI_SCHEMAS = ["ops", "experiments", "feature_registry", "production"]
UI_OBJECTS = [("curated", "data_catalog"), ("curated", "field_lineage"), ("labels", "split_meta")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".local_lake" / "console_fixture"))
    ap.add_argument("--max-rows", type=int, default=200_000, help="cap per table (large tables are truncated)")
    args = ap.parse_args()

    from lau.settings import Settings
    from lau.store import DatabricksStore, LocalStore

    src_settings = Settings()
    src_settings.project.backend = "databricks"
    src = DatabricksStore("harness", src_settings)

    os.environ["LAU_LOCAL_LAKE"] = str(Path(args.out).resolve())
    dst_settings = Settings()
    dst_settings.project.backend = "local"
    dst = LocalStore("admin", dst_settings)
    dst.ensure_schemas()

    objects = list(UI_OBJECTS)
    for key in UI_SCHEMAS:
        schema = src_settings.schema(key)
        for t in src.w.tables.list(catalog_name=src_settings.catalog, schema_name=schema):
            if t.table_type and "VIEW" in str(t.table_type):
                continue
            objects.append((key, t.name))

    total = 0
    for key, table in objects:
        t0 = time.time()
        try:
            df = src.query(f"SELECT * FROM {src.fq(key, table)} LIMIT {int(args.max_rows)}")
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"skip {key}.{table}: {str(e)[:120]}")
            continue
        dst.write_df(key, table, df, mode="overwrite")
        total += len(df)
        print(f"{key}.{table}: {len(df):,} rows ({time.time() - t0:.1f}s)")
    src.close()
    print(f"done: {len(objects)} objects, {total:,} rows -> {dst_settings.local_lake}")


if __name__ == "__main__":
    main()
