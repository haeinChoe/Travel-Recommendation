"""Build privacy-safe recommendation-fit aggregates from explicit TL/VL CSV roots.

Only aggregate rows are written. Identifiers stay inside DuckDB queries and are
never serialized, printed, or included in errors. POI_ID is treated as a
region-scoped observed-column candidate; this script does not canonicalize POIs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from profile_travel_log import detect_encoding

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw"
RESULTS_ROOT = REPO_ROOT / "results" / "eda" / "travel-log-2023"
OUT_ROOT = RESULTS_ROOT
TMP_ROOT = RESULTS_ROOT / "tmp"
K = 10
REGIONS = {"capital", "west", "east", "jeju-islands"}
SPLITS = {"TL", "VL"}
TABLES = {"TN_TRAVEL": "travel", "TN_VISIT_AREA_INFO": "visits"}
IDENTIFIER_FIELDS = {"TRAVEL_ID", "TRAVELER_ID", "VISIT_AREA_ID", "POI_ID"}
ARTIFACTS = ("recommendation_fit.csv", "run_metadata.json")
BUCKETS = ((1, 1, "1"), (2, 4, "2-4"), (5, 9, "5-9"), (10, 49, "10-49"), (50, None, "50+"))


@dataclass(frozen=True)
class Source:
    region: str
    split: str
    root: Path
    travel_view: str | None
    visits_view: str | None


def qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def ql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def has_symlink_component(path: Path) -> bool:
    if path.is_absolute():
        current = Path(path.anchor)
        parts = path.parts[1:]
    else:
        current = Path.cwd()
        parts = path.parts
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


def parse_input_spec(value: str) -> tuple[str, str, Path]:
    """Parse region:split=/path without exposing the path in errors."""
    left, sep, raw_path = value.partition("=")
    region, colon, split = left.partition(":")
    if not sep or not colon or region not in REGIONS or split not in SPLITS or not raw_path:
        raise argparse.ArgumentTypeError("입력 형식은 region:TL|VL=/approved/raw/path 입니다.")
    return region, split, Path(raw_path)


def csv_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = sorted(name for name in directories if not (base / name).is_symlink())
        for name in names:
            path = base / name
            if path.suffix.lower() == ".csv" and not path.is_symlink():
                files.append(path)
    return sorted(files)


def table_role(path: Path) -> str | None:
    stem = path.stem.upper()
    for table, role in TABLES.items():
        if stem == table or stem.startswith(table + "_"):
            return role
    return None


def resolve_column(con: duckdb.DuckDBPyConnection, view: str, name: str) -> str | None:
    try:
        columns = con.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
    except duckdb.Error:
        return None
    return next((str(row[0]) for row in columns if str(row[0]).casefold() == name.casefold()), None)


def count_bucket(value: int, k: int = K) -> str:
    if value == 0:
        return "0"
    return f"<{k}" if value < k else f"{k}+"


def rate_band(numerator: int, denominator: int, k: int = K) -> str:
    if denominator <= 0:
        return "n/a"
    if denominator < k or 0 < numerator < k:
        return f"<{k}/suppressed"
    if numerator == 0:
        return "0-<10%"
    rate = numerator / denominator
    if rate < 0.10:
        return "0-<10%"
    if rate < 0.25:
        return "10-<25%"
    if rate < 0.50:
        return "25-<50%"
    if rate < 0.75:
        return "50-<75%"
    if rate < 0.90:
        return "75-<90%"
    return "90-100%"


def add_metric(
    rows: list[dict[str, Any]],
    scope: str,
    metric: str,
    count: int,
    denominator: int | None = None,
    category: str = "total",
) -> None:
    suppressed = 0 < count < K
    denominator_suppressed = denominator is not None and denominator < K
    rows.append(
        {
            "scope": scope,
            "metric": metric,
            "category": category,
            "count": count_bucket(count),
            "rate": (
                None
                if denominator is None
                else rate_band(count, denominator)
            ),
            "status": "suppressed_k10" if suppressed or denominator_suppressed else "observed",
        }
    )


def safe_distribution(counts: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Apply k=10 and complementary suppression to a public-label distribution."""
    shown = [(label, count) for label, count in counts if count >= K]
    hidden = sum(count for _, count in counts if count < K)
    shown.sort(key=lambda item: (-item[1], item[0]))
    while 0 < hidden < K and shown:
        hidden += shown.pop()[1]
    if hidden >= K:
        shown.append(("<suppressed>", hidden))
    return shown


def add_distribution(
    rows: list[dict[str, Any]], scope: str, metric: str, counts: list[tuple[str, int]]
) -> None:
    safe = safe_distribution(counts)
    if not safe:
        add_metric(rows, scope, metric, sum(count for _, count in counts), category="<suppressed>")
        return
    for category, count in safe:
        add_metric(rows, scope, metric, count, category=category)


def degree_bucket(value: int) -> str:
    for lower, upper, label in BUCKETS:
        if value >= lower and (upper is None or value <= upper):
            return label
    raise ValueError("degree out of range")


def normalized_union_sql(
    sources: list[Source], con: duckdb.DuckDBPyConnection, table_kind: str
) -> tuple[str | None, dict[str, set[str]]]:
    branches: list[str] = []
    resolved: dict[str, set[str]] = {}
    for i, source in enumerate(sources):
        view = source.travel_view if table_kind == "travel" else source.visits_view
        source_key = f"{source.region}:{source.split}:{i}"
        resolved[source_key] = set()
        if view is None:
            continue
        names = {
            "travel": ("TRAVEL_ID", "TRAVELER_ID"),
            "visits": (
                "TRAVEL_ID",
                "VISIT_AREA_ID",
                "POI_ID",
                "DGSTFN",
                "REVISIT_INTENTION",
                "RCMDTN_INTENTION",
            ),
        }[table_kind]
        exprs = [f"{ql(source.region)} AS region_key"]
        found: set[str] = set()
        for name in names:
            col = resolve_column(con, view, name)
            if col is not None:
                cast = f"CAST({qi(col)} AS VARCHAR)"
                if name in IDENTIFIER_FIELDS:
                    expr = (
                        f"CASE WHEN {qi(col)} IS NULL OR trim({cast}) = '' "
                        f"THEN NULL ELSE {cast} END"
                    )
                else:
                    expr = f"NULLIF(trim({cast}), '')"
                exprs.append(f"{expr} AS {qi(name)}")
                found.add(name)
            else:
                exprs.append(f"NULL::VARCHAR AS {qi(name)}")
        resolved[source_key] = found
        branches.append(f"SELECT {', '.join(exprs)} FROM {view}")
    return (" UNION ALL ".join(branches) if branches else None), resolved


def complete_field_coverage(fields: dict[str, set[str]], name: str) -> bool:
    return bool(fields) and all(name in found for found in fields.values())


def add_unavailable(rows: list[dict[str, Any]], scope: str, metric: str, reason: str) -> None:
    rows.append(
        {
            "scope": scope,
            "metric": metric,
            "category": "total",
            "count": None,
            "rate": None,
            "status": f"unavailable_{reason}",
        }
    )


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    value = con.execute(sql).fetchone()[0]
    if value is None:
        raise ValueError("aggregate query returned NULL")
    return int(value)


def distribution(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[str, int]]:
    return [(str(label), int(count)) for label, count in con.execute(sql).fetchall()]


def compute_scope(
    con: duckdb.DuckDBPyConnection,
    scope: str,
    sources: list[Source],
    skip_total_identity_counts: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    travel_union, travel_fields = normalized_union_sql(sources, con, "travel")
    visits_union, visits_fields = normalized_union_sql(sources, con, "visits")
    has_trip_id = complete_field_coverage(travel_fields, "TRAVEL_ID")
    has_traveler_id = complete_field_coverage(travel_fields, "TRAVELER_ID")
    has_visit_trip_id = complete_field_coverage(visits_fields, "TRAVEL_ID")
    has_visit_area_id = complete_field_coverage(visits_fields, "VISIT_AREA_ID")
    has_poi_id = complete_field_coverage(visits_fields, "POI_ID")
    if travel_union:
        con.execute(f"CREATE OR REPLACE TEMP VIEW _fit_travel AS {travel_union}")
    if visits_union:
        con.execute(f"CREATE OR REPLACE TEMP VIEW _fit_visits AS {visits_union}")

    if skip_total_identity_counts:
        add_unavailable(rows, scope, "unique_trips", "existing_capital_observation_not_recomputed")
    elif travel_union and has_trip_id:
        trips = scalar(
            con,
            "SELECT count(*) FROM (SELECT DISTINCT region_key, TRAVEL_ID "
            "FROM _fit_travel WHERE TRAVEL_ID IS NOT NULL)",
        )
        add_metric(rows, scope, "unique_trips", trips)
    else:
        trips = 0
        add_unavailable(rows, scope, "unique_trips", "missing_or_incomplete_TRAVEL_ID")
    if skip_total_identity_counts:
        add_unavailable(
            rows, scope, "unique_travelers", "existing_capital_observation_not_recomputed"
        )
    elif travel_union and has_traveler_id:
        travelers = scalar(
            con,
            "SELECT count(*) FROM (SELECT DISTINCT region_key, TRAVELER_ID "
            "FROM _fit_travel WHERE TRAVELER_ID IS NOT NULL)",
        )
        add_metric(rows, scope, "unique_travelers", travelers)
    else:
        travelers = 0
        add_unavailable(
            rows, scope, "unique_travelers", "missing_or_incomplete_TRAVELER_ID"
        )

    if not visits_union:
        for metric in (
            "unique_visit_areas",
            "unique_pois",
            "visits",
            "poi_id_vs_visit_area_id",
            "visits_per_trip",
            "trips_per_traveler",
            "visits_per_traveler",
            "visitors_per_poi",
            "poi_visit_frequency",
            "single_visit_pois",
            "DGSTFN_distribution",
            "REVISIT_INTENTION_distribution",
            "RCMDTN_INTENTION_distribution",
        ):
            add_unavailable(rows, scope, metric, "visit_table_missing")
        return rows

    total_visits = scalar(con, "SELECT count(*) FROM _fit_visits")
    add_metric(rows, scope, "visits", total_visits)
    if has_visit_area_id and has_visit_trip_id:
        areas = scalar(
            con,
            "SELECT count(*) FROM (SELECT DISTINCT region_key, TRAVEL_ID, VISIT_AREA_ID "
            "FROM _fit_visits WHERE TRAVEL_ID IS NOT NULL AND VISIT_AREA_ID IS NOT NULL)",
        )
        add_metric(rows, scope, "unique_visit_areas", areas)
    else:
        add_unavailable(
            rows, scope, "unique_visit_areas", "missing_or_incomplete_area_trip_key"
        )
    if has_poi_id:
        poi_count = scalar(
            con,
            "SELECT count(*) FROM (SELECT DISTINCT region_key, POI_ID FROM _fit_visits "
            "WHERE POI_ID IS NOT NULL)",
        )
        add_metric(rows, scope, "unique_pois", poi_count)
        if has_visit_area_id:
            relation_counts = distribution(
                con,
                "SELECT CASE WHEN POI_ID IS NULL AND VISIT_AREA_ID IS NULL "
                "THEN 'both_missing' WHEN POI_ID IS NULL THEN 'poi_missing_area_present' "
                "WHEN VISIT_AREA_ID IS NULL THEN 'poi_present_area_missing' "
                "ELSE 'both_present' END category, count(*) FROM _fit_visits GROUP BY 1",
            )
            for category, count in safe_distribution(relation_counts):
                add_metric(
                    rows, scope, "poi_id_vs_visit_area_id", count, total_visits, category
                )
            if not safe_distribution(relation_counts):
                add_metric(
                    rows,
                    scope,
                    "poi_id_vs_visit_area_id",
                    sum(count for _, count in relation_counts),
                    category="<suppressed>",
                )
        else:
            add_unavailable(
                rows, scope, "poi_id_vs_visit_area_id", "missing_or_incomplete_VISIT_AREA_ID"
            )
    else:
        add_unavailable(rows, scope, "unique_pois", "missing_or_incomplete_POI_ID")
        add_unavailable(
            rows, scope, "poi_id_vs_visit_area_id", "missing_or_incomplete_POI_ID"
        )

    if has_visit_trip_id:
        trip_hist = distribution(
            con,
            "SELECT degree_bucket, count(*) FROM (SELECT CASE "
            "WHEN n=1 THEN '1' WHEN n BETWEEN 2 AND 4 THEN '2-4' "
            "WHEN n BETWEEN 5 AND 9 THEN '5-9' WHEN n BETWEEN 10 AND 49 THEN '10-49' "
            "ELSE '50+' END degree_bucket FROM (SELECT region_key, TRAVEL_ID, count(*) n "
            "FROM _fit_visits WHERE TRAVEL_ID IS NOT NULL GROUP BY 1,2)) GROUP BY 1",
        )
        add_distribution(rows, scope, "visits_per_trip", trip_hist)
    else:
        add_unavailable(rows, scope, "visits_per_trip", "missing_or_incomplete_TRAVEL_ID")

    # Traveler history is reported only for unambiguous observed TRAVEL_ID -> TRAVELER_ID pairs.
    if travel_union and visits_union and has_trip_id and has_traveler_id and has_visit_trip_id:
        con.execute(
            "CREATE OR REPLACE TEMP VIEW _fit_trip_owner AS "
            "SELECT region_key, TRAVEL_ID, min(TRAVELER_ID) TRAVELER_ID "
            "FROM _fit_travel WHERE TRAVEL_ID IS NOT NULL AND TRAVELER_ID IS NOT NULL "
            "GROUP BY 1,2 HAVING count(DISTINCT TRAVELER_ID)=1"
        )
        ambiguous = scalar(
            con,
            "SELECT count(*) FROM (SELECT region_key, TRAVEL_ID FROM _fit_travel "
            "WHERE TRAVEL_ID IS NOT NULL AND TRAVELER_ID IS NOT NULL GROUP BY 1,2 "
            "HAVING count(DISTINCT TRAVELER_ID)>1)",
        )
        add_metric(rows, scope, "ambiguous_trip_traveler_mappings", ambiguous)
        trip_hist = distribution(
            con,
            "SELECT degree_bucket, count(*) FROM (SELECT CASE "
            "WHEN n=1 THEN '1' WHEN n BETWEEN 2 AND 4 THEN '2-4' "
            "WHEN n BETWEEN 5 AND 9 THEN '5-9' WHEN n BETWEEN 10 AND 49 THEN '10-49' "
            "ELSE '50+' END degree_bucket FROM (SELECT region_key, TRAVELER_ID, count(*) n "
            "FROM (SELECT DISTINCT t.region_key, t.TRAVELER_ID, t.TRAVEL_ID "
            "FROM _fit_trip_owner t) GROUP BY 1,2)) GROUP BY 1",
        )
        add_distribution(rows, scope, "trips_per_traveler", trip_hist)
        visits_hist = distribution(
            con,
            "SELECT degree_bucket, count(*) FROM (SELECT CASE "
            "WHEN n=1 THEN '1' WHEN n BETWEEN 2 AND 4 THEN '2-4' "
            "WHEN n BETWEEN 5 AND 9 THEN '5-9' WHEN n BETWEEN 10 AND 49 THEN '10-49' "
            "ELSE '50+' END degree_bucket FROM (SELECT t.region_key, t.TRAVELER_ID, count(*) n "
            "FROM _fit_visits v JOIN _fit_trip_owner t USING (region_key, TRAVEL_ID) "
            "GROUP BY 1,2)) GROUP BY 1",
        )
        add_distribution(rows, scope, "visits_per_traveler", visits_hist)
        if has_poi_id:
            visitors_hist = distribution(
                con,
                "SELECT degree_bucket, count(*) FROM (SELECT CASE "
                "WHEN n=1 THEN '1' WHEN n BETWEEN 2 AND 4 THEN '2-4' "
                "WHEN n BETWEEN 5 AND 9 THEN '5-9' WHEN n BETWEEN 10 AND 49 THEN '10-49' "
                "ELSE '50+' END degree_bucket FROM (SELECT v.region_key, v.POI_ID, "
                "count(DISTINCT t.TRAVELER_ID) n FROM _fit_visits v JOIN _fit_trip_owner t "
                "USING (region_key, TRAVEL_ID) WHERE v.POI_ID IS NOT NULL GROUP BY 1,2)) "
                "GROUP BY 1",
            )
            add_distribution(rows, scope, "visitors_per_poi", visitors_hist)
        else:
            add_unavailable(rows, scope, "visitors_per_poi", "missing_or_incomplete_POI_ID")
    else:
        add_unavailable(
            rows, scope, "ambiguous_trip_traveler_mappings", "trip_traveler_link_missing"
        )
        add_unavailable(rows, scope, "trips_per_traveler", "trip_traveler_link_missing")
        add_unavailable(rows, scope, "visits_per_traveler", "trip_traveler_link_missing")
        add_unavailable(rows, scope, "visitors_per_poi", "trip_traveler_link_missing")

    if has_poi_id:
        poi_hist = distribution(
            con,
            "SELECT degree_bucket, count(*) FROM (SELECT CASE "
            "WHEN n=1 THEN '1' WHEN n BETWEEN 2 AND 4 THEN '2-4' "
            "WHEN n BETWEEN 5 AND 9 THEN '5-9' WHEN n BETWEEN 10 AND 49 THEN '10-49' "
            "ELSE '50+' END degree_bucket FROM (SELECT region_key, POI_ID, count(*) n "
            "FROM _fit_visits WHERE POI_ID IS NOT NULL GROUP BY 1,2)) GROUP BY 1",
        )
        add_distribution(rows, scope, "poi_visit_frequency", poi_hist)
        single = scalar(
            con,
            "SELECT count(*) FROM (SELECT region_key, POI_ID FROM _fit_visits "
            "WHERE POI_ID IS NOT NULL GROUP BY 1,2 HAVING count(*)=1)",
        )
        total_poi = scalar(
            con,
            "SELECT count(*) FROM (SELECT DISTINCT region_key, POI_ID FROM _fit_visits "
            "WHERE POI_ID IS NOT NULL)",
        )
        add_metric(rows, scope, "single_visit_pois", single, total_poi)
    else:
        add_unavailable(rows, scope, "poi_visit_frequency", "missing_or_incomplete_POI_ID")
        add_unavailable(rows, scope, "single_visit_pois", "missing_or_incomplete_POI_ID")

    # Feedback values are reduced to the documented 1-5 code family or a broad out-of-domain bucket.
    for field in ("DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION"):
        if not complete_field_coverage(visits_fields, field):
            add_unavailable(
                rows, scope, f"{field}_distribution", f"missing_or_incomplete_{field}"
            )
            continue
        feedback = distribution(
            con,
            f"SELECT CASE WHEN trim({qi(field)}) IN ('1','2','3','4','5') "
            f"THEN 'code_' || trim({qi(field)}) WHEN {qi(field)} IS NULL THEN '<missing>' "
            f"ELSE 'outside_1_to_5' END category, count(*) FROM _fit_visits GROUP BY 1",
        )
        add_distribution(rows, scope, f"{field}_distribution", feedback)
    return rows


def create_source_views(
    con: duckdb.DuckDBPyConnection, specs: list[tuple[str, str, Path]], raw_root: Path
) -> list[Source]:
    validated_roots: list[Path] = []
    for _, _, requested in specs:
        if has_symlink_component(requested):
            raise ValueError("입력 경로에 심볼릭 링크가 있어 안전하게 읽을 수 없습니다.")
        root = Path(os.path.abspath(requested))
        resolved_root = root.resolve()
        if not root.is_dir() or not within(resolved_root, raw_root.resolve()):
            raise ValueError("TL/VL 입력은 지정한 --raw-root 아래의 기존 폴더여야 합니다.")
        validated_roots.append(resolved_root)
    if len(set(validated_roots)) != len(validated_roots):
        raise ValueError("서로 다른 권역·분할에 같은 입력 폴더를 지정할 수 없습니다.")

    sources: list[Source] = []
    for index, ((region, split, _requested), root) in enumerate(
        zip(specs, validated_roots, strict=True)
    ):
        found: dict[str, list[Path]] = {role: [] for role in TABLES.values()}
        for path in csv_files(root):
            role = table_role(path)
            if role:
                found[role].append(path)
        views: dict[str, str | None] = {role: None for role in TABLES.values()}
        for role, paths in found.items():
            if not paths:
                continue
            encodings = {detect_encoding(path) for path in paths}
            if "non-utf8" in encodings or len(encodings) != 1:
                raise ValueError("UTF-8/UTF-16 이외 또는 혼합 인코딩 CSV는 변환하지 않습니다.")
            encoding = next(iter(encodings))
            view = f"_fit_input_{index}_{role}"
            files = ", ".join(ql(str(path)) for path in paths)
            con.execute(
                f"CREATE TEMP VIEW {view} AS SELECT * FROM read_csv([{files}], "
                f"header=true, all_varchar=true, union_by_name=true, strict_mode=false, "
                f"encoding={ql(encoding)})"
            )
            views[role] = view
        sources.append(Source(region, split, root, views["travel"], views["visits"]))
    return sources


def overlap_rows(
    con: duckdb.DuckDBPyConnection, label: str, tl: list[Source], vl: list[Source]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tl_sql, tl_fields = normalized_union_sql(tl, con, "visits")
    vl_sql, vl_fields = normalized_union_sql(vl, con, "visits")
    unavailable_metrics = (
        "tl_unique_pois",
        "vl_unique_pois",
        "tl_vl_poi_overlap",
        "vl_cold_start_pois",
        "vl_cold_start_poi_share",
    )
    if not tl_sql or not vl_sql:
        for metric in unavailable_metrics:
            add_unavailable(rows, label, metric, "visit_table_missing")
        return rows
    if not complete_field_coverage(tl_fields, "POI_ID") or not complete_field_coverage(
        vl_fields, "POI_ID"
    ):
        for metric in unavailable_metrics:
            add_unavailable(rows, label, metric, "missing_or_incomplete_POI_ID")
        return rows
    con.execute(f"CREATE OR REPLACE TEMP VIEW _fit_tl_poi AS {tl_sql}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW _fit_vl_poi AS {vl_sql}")
    overlap_sql = (
        "WITH tl AS (SELECT DISTINCT region_key, POI_ID FROM _fit_tl_poi "
        "WHERE POI_ID IS NOT NULL), "
        "vl AS (SELECT DISTINCT region_key, POI_ID FROM _fit_vl_poi "
        "WHERE POI_ID IS NOT NULL) "
        "SELECT (SELECT count(*) FROM tl), (SELECT count(*) FROM vl), "
        "(SELECT count(*) FROM vl WHERE EXISTS (SELECT 1 FROM tl "
        "WHERE tl.region_key=vl.region_key AND tl.POI_ID=vl.POI_ID)), "
        "(SELECT count(*) FROM vl WHERE NOT EXISTS (SELECT 1 FROM tl "
        "WHERE tl.region_key=vl.region_key AND tl.POI_ID=vl.POI_ID))"
    )
    tl_count, vl_count, shared, cold = con.execute(overlap_sql).fetchone()
    add_metric(rows, label, "tl_unique_pois", int(tl_count))
    add_metric(rows, label, "vl_unique_pois", int(vl_count))
    add_metric(rows, label, "tl_vl_poi_overlap", int(shared), int(vl_count))
    add_metric(rows, label, "vl_cold_start_pois", int(cold), int(vl_count))
    add_metric(rows, label, "vl_cold_start_poi_share", int(cold), int(vl_count))
    return rows


def write_rows(
    out: Path, rows: list[dict[str, Any]], metadata: dict[str, Any], overwrite: bool
) -> None:
    resolved_out = out.resolve()
    if (
        out.is_symlink()
        or not within(resolved_out, OUT_ROOT.resolve())
        or resolved_out == OUT_ROOT.resolve()
        or within(resolved_out, TMP_ROOT.resolve())
    ):
        raise ValueError(
            "출력 폴더는 results/eda/travel-log-2023 아래, tmp 바깥이어야 합니다."
        )
    if has_symlink_component(out.absolute()):
        raise ValueError("출력 경로에 심볼릭 링크가 있습니다.")
    out.mkdir(parents=True, exist_ok=True)
    targets = [out / name for name in ARTIFACTS]
    if any(path.is_symlink() for path in targets) or (
        not overwrite and any(path.exists() for path in targets)
    ):
        raise ValueError("기존 결과 또는 심볼릭 링크가 있습니다. --overwrite 여부를 확인하세요.")
    for path in targets:
        if path.exists() and not path.is_file():
            raise ValueError("결과 위치가 일반 파일이 아닙니다.")
    with tempfile.TemporaryDirectory(prefix=".recommendation-fit-stage-", dir=out) as stage:
        staged_csv = Path(stage) / ARTIFACTS[0]
        staged_metadata = Path(stage) / ARTIFACTS[1]
        with staged_csv.open("w", newline="", encoding="utf-8") as stream:
            fields = ("scope", "metric", "category", "count", "rate", "status")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        staged_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Stage both complete files before per-file atomic replacement. The pair
        # cannot be made crash-atomic portably while preserving extra output files.
        for staged, target in zip((staged_csv, staged_metadata), targets, strict=True):
            os.replace(staged, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TL/VL travel-log 추천 적합성 집계를 k=10으로 생성합니다.",
        epilog="입력은 --raw-root 아래의 명시적 TL/VL 폴더, 출력은 ignored results/ 아래입니다.",
    )
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument(
        "--input", action="append", required=True, type=parse_input_spec,
        metavar="REGION:SPLIT=PATH",
        help="반복 지정: capital|west|east|jeju-islands:TL|VL=/raw/...",
    )
    parser.add_argument("--output", type=Path, default=OUT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument(
        "--confirm-poi-candidate",
        action="store_true",
        help=(
            "로컬 방문 테이블의 관측 POI_ID 컬럼을 미확정 후보로 분석하는 데 동의; "
            "검토한 HWP는 table-specific 의미나 PK/FK를 확정하지 않음"
        ),
    )
    return parser


def pooled_scope_prefix(selected_regions: list[str]) -> str:
    if set(selected_regions) == REGIONS:
        return "integrated"
    return f"selected[{'+'.join(sorted(selected_regions))}]"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_approved or not args.confirm_terms or not args.confirm_poi_candidate:
        print("[중단] 승인, 이용 조건, POI_ID 후보 분석 확인 옵션이 필요합니다.", file=sys.stderr)
        return 2
    if has_symlink_component(args.raw_root) or has_symlink_component(args.output.absolute()):
        print("[중단] raw/output 경로에 심볼릭 링크가 있습니다.", file=sys.stderr)
        return 2
    raw_root = Path(os.path.abspath(args.raw_root)).resolve()
    specs = args.input
    if len({(region, split) for region, split, _ in specs}) != len(specs):
        print("[중단] 동일 권역·분할 입력이 중복됐습니다.", file=sys.stderr)
        return 2
    selected_regions = sorted({region for region, _, _ in specs})
    expected_pairs = {(region, split) for region in selected_regions for split in SPLITS}
    supplied_pairs = {(region, split) for region, split, _ in specs}
    if supplied_pairs != expected_pairs:
        print("[중단] 선택한 각 권역의 TL과 VL 입력이 모두 필요합니다.", file=sys.stderr)
        return 2
    try:
        if TMP_ROOT.is_symlink() or not within(TMP_ROOT.resolve(), RESULTS_ROOT.resolve()):
            raise ValueError("DuckDB 임시 경로가 허용된 results/tmp 경로를 벗어납니다.")
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        started = datetime.now(UTC)
        with tempfile.TemporaryDirectory(prefix="recommendation-fit-", dir=TMP_ROOT) as temp_dir:
            con = duckdb.connect(
                ":memory:",
                config={"memory_limit": "1GiB", "threads": 2, "temp_directory": temp_dir},
            )
            try:
                sources = create_source_views(con, specs, raw_root)
                by_region_split = {(source.region, source.split): source for source in sources}
                result_rows: list[dict[str, Any]] = []
                for region in selected_regions:
                    tl = [by_region_split[(region, "TL")]]
                    vl = [by_region_split[(region, "VL")]]
                    skip_capital_combined_totals = region == "capital"
                    result_rows.extend(
                        compute_scope(con, f"{region}:TL", tl)
                    )
                    result_rows.extend(
                        compute_scope(con, f"{region}:VL", vl)
                    )
                    result_rows.extend(
                        compute_scope(
                            con,
                            f"{region}:combined",
                            tl + vl,
                            skip_capital_combined_totals,
                        )
                    )
                    result_rows.extend(overlap_rows(con, region, tl, vl))
                if len(selected_regions) > 1:
                    pooled_prefix = pooled_scope_prefix(selected_regions)
                    result_rows.extend(
                        overlap_rows(
                            con,
                            pooled_prefix,
                            [by_region_split[(region, "TL")] for region in selected_regions],
                            [by_region_split[(region, "VL")] for region in selected_regions],
                        )
                    )
                    for split in sorted(SPLITS):
                        group = [by_region_split[(region, split)] for region in selected_regions]
                        result_rows.extend(
                            compute_scope(con, f"{pooled_prefix}:{split}", group)
                        )
                    result_rows.extend(
                        compute_scope(con, f"{pooled_prefix}:combined", sources)
                    )
                metadata = {
                    "started_utc": started.isoformat(timespec="seconds"),
                    "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "code_commit": _git_commit(),
                    "code_worktree_dirty": _git_dirty(),
                    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "regions": selected_regions,
                    "splits": sorted(SPLITS),
                    "sampling": "full scan of matched tables; no random sampling",
                    "seed": None,
                    "source_paths_written": False,
                    "k": K,
                    "public_count_policy": "0, <10, 10+",
                    "public_rate_policy": "coarse categorical bands; small numerators suppressed",
                    "poi_identity_basis": (
                        "region-scoped observed POI_ID column candidate; no canonicalization"
                    ),
                    "poi_link_semantics": "candidate relation only; not a declared PK/FK",
                    "capital_total_identity_counts": (
                        "existing observation retained; totals not recomputed"
                        if "capital" in selected_regions
                        else "not applicable"
                    ),
                    "unique_visit_area_basis": "distinct (region, TRAVEL_ID, VISIT_AREA_ID)",
                    "traveler_link_basis": (
                        "unambiguous observed TRAVEL_ID to TRAVELER_ID pairs only"
                    ),
                    "matrix_sparsity": "not computed (canonical item policy not defined)",
                    "duckdb": duckdb.__version__,
                    "memory_limit": "1GiB",
                    "temp_directory": "results/eda/travel-log-2023/tmp (cleaned after run)",
                    "threads": 2,
                }
                write_rows(args.output, result_rows, metadata, args.overwrite)
            finally:
                con.close()
    except (OSError, ValueError, duckdb.Error) as exc:
        print(f"[중단] recommendation-fit 분석 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"완료: {args.output.resolve().relative_to(REPO_ROOT)}")
    return 0


def _git_commit() -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _git_dirty() -> bool | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


if __name__ == "__main__":
    raise SystemExit(main())
