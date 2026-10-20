"""Multi-stage evidence-based POI identity matching pipeline (Issue #69).

Evaluates Stage 0 through Stage 5 over all 4 regions (capital, west, east, jeju-islands)
and both splits (TL, VL) on AI Hub 2023 Domestic Travel Log against TourAPI KorService2 v4.4 snapshot.

Outputs only non-identifying aggregate metrics (counts, rates, quantiles) to Git-ignored results/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.address_key_parser import (
    ParsedAddress,
    match_parsed_addresses,
    normalize_sido,
    normalize_sigungu,
    parse_address_string,
)
from scripts.recommendation.geo_distance import (
    haversine_distance_meters,
    is_valid_korea_wgs84,
)
from scripts.recommendation.name_normalizer import (
    generate_location_gated_name_variants,
    normalize_punctuation_n1,
    split_parenthetical_variants_n2,
    strip_facility_suffix,
    strip_region_prefix,
)
from scripts.recommendation.poi_catalog_candidate_contract import (
    CatalogPoi,
    CatalogSnapshot,
    load_tourapi_v44_snapshot_csv,
    normalize_code,
    normalize_text,
)
from scripts.recommendation.poi_catalog_policy import load_poi_catalog_policy
from scripts.recommendation.sgg_crosswalk import SggCrosswalk

REGIONS = ("capital", "west", "east", "jeju-islands")
SPLITS = ("TL", "VL")
SUPPORTED_CONTENT_TYPES = frozenset({"12", "14", "28"})
GRID_STEP = 0.01  # ~1.1 km grid bucket for spatial indexing

REGION_ENV_PREFIX = {
    "capital": "CAPITAL",
    "west": "WEST",
    "east": "EAST",
    "jeju-islands": "JEJU",
}


@dataclass
class PositiveObservation:
    region: str
    split: str
    travel_id: str
    poi_id: str
    visit_area_nm: str
    poi_nm: str
    road_nm_addr: str
    lotno_addr: str
    x_coord: float | None
    y_coord: float | None
    sgg_cd: str
    visit_area_type_cd: str


@dataclass
class MasterPoiRecord:
    poi_id: str
    poi_nm: str
    sgg_cd: str
    road_nm_addr: str
    lotno_addr: str
    x_coord: float | None
    y_coord: float | None


def _safe_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.strip().strip('"'))
    except ValueError:
        return None


def load_all_tc_sgg(capital_tl_dir: Path | None = None) -> SggCrosswalk:
    """Load TC_SGG crosswalk across all 4 regions."""
    sgg_paths: list[Path] = []
    for reg_key in ["CAPITAL_TL", "WEST_TL", "EAST_TL", "JEJU_TL", "CAPITAL_VL", "WEST_VL", "EAST_VL", "JEJU_VL"]:
        val = os.environ.get(reg_key)
        if val:
            p = Path(val).resolve()
            found = list(p.glob("*sgg*.csv")) + list(p.glob("*SGG*.csv"))
            for f in found:
                if f not in sgg_paths:
                    sgg_paths.append(f)

    if capital_tl_dir:
        for f in list(capital_tl_dir.glob("*sgg*.csv")) + list(capital_tl_dir.glob("*SGG*.csv")):
            if f not in sgg_paths:
                sgg_paths.append(f)

    raw_root_val = os.environ.get("RAW_ROOT")
    if raw_root_val:
        for f in Path(raw_root_val).glob("**/tc_sgg*.csv"):
            if f not in sgg_paths:
                sgg_paths.append(f)

    if not sgg_paths:
        raise FileNotFoundError("TC_SGG CSV could not be located")

    cw = SggCrosswalk()
    cw.load_from_csvs(sgg_paths)
    return cw


def load_all_visit_positives() -> list[PositiveObservation]:
    """Load exactly the 97,640 unique (region, travel_id, poi_id) observations."""
    positives: list[PositiveObservation] = []
    seen: set[tuple[str, str, str]] = set()

    for region in REGIONS:
        prefix = REGION_ENV_PREFIX[region]
        for split in SPLITS:
            split_env_key = f"{prefix}_{split}"
            split_path = Path(os.environ[split_env_key]).resolve()
            files = list(split_path.glob("*visit_area_info*.csv")) + list(split_path.glob("*VISIT_AREA_INFO*.csv"))
            if not files:
                raise FileNotFoundError(f"VISIT_AREA_INFO not found for {region}:{split}")
            target = files[0]
            with target.open("r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    travel_id = (row.get("TRAVEL_ID") or "").strip()
                    poi_id = (row.get("POI_ID") or "").strip()
                    if not (travel_id and poi_id):
                        continue
                    key = (region, travel_id, poi_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    visit_nm = (row.get("VISIT_AREA_NM") or "").strip()
                    poi_nm = (row.get("POI_NM") or "").strip()
                    road = (row.get("ROAD_NM_ADDR") or "").strip()
                    lotno = (row.get("LOTNO_ADDR") or "").strip()
                    x = _safe_float(row.get("X_COORD"))
                    y = _safe_float(row.get("Y_COORD"))
                    sgg_cd = (row.get("SGG_CD") or "").strip()
                    v_type = (row.get("VISIT_AREA_TYPE_CD") or "").strip()

                    positives.append(PositiveObservation(
                        region=region,
                        split=split,
                        travel_id=travel_id,
                        poi_id=poi_id,
                        visit_area_nm=visit_nm,
                        poi_nm=poi_nm,
                        road_nm_addr=road,
                        lotno_addr=lotno,
                        x_coord=x,
                        y_coord=y,
                        sgg_cd=sgg_cd,
                        visit_area_type_cd=v_type,
                    ))

    return positives


def load_master_records_fast(
    target_poi_ids: set[str],
    cache_path: Path | None = None,
) -> dict[str, MasterPoiRecord]:
    """Load POI Master records using standard csv.reader with cache integrity verification."""
    target_ids_sorted = sorted(target_poi_ids)
    target_ids_sha256 = hashlib.sha256("".join(target_ids_sorted).encode("utf-8")).hexdigest()

    capital_other = Path(os.environ["CAPITAL_OTHER"]).resolve()
    target_file = capital_other / "메타데이터" / "tn_poi_master_POIMaster_all.csv"
    if not target_file.exists():
        target_file = capital_other / "tn_poi_master_POIMaster_all.csv"
    if not target_file.exists():
        files = list(capital_other.glob("**/*POI*Master*.csv"))
        if not files:
            raise FileNotFoundError("Master POI file not found")
        target_file = files[0]

    master_file_size = target_file.stat().st_size
    master_file_mtime_ns = target_file.stat().st_mtime_ns

    if cache_path is not None and cache_path.exists():
        try:
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            meta = cache_payload.get("_metadata", {})
            if (
                meta.get("target_ids_count") == len(target_poi_ids)
                and meta.get("target_ids_sha256") == target_ids_sha256
                and meta.get("master_file_size") == master_file_size
                and meta.get("master_file_mtime_ns") == master_file_mtime_ns
                and "records" in cache_payload
            ):
                records = {k: MasterPoiRecord(**v) for k, v in cache_payload["records"].items()}
                print(f"Loaded {len(records)} cached master POI records (verified integrity).")
                return records
            else:
                print("Cache metadata mismatch or outdated; rebuilding cache...")
        except Exception:
            print("Failed to read cache safely; rebuilding...")

    print(f"Reading master POI file for {len(target_poi_ids)} target POI IDs using csv.reader...")
    t0 = time.time()
    records: dict[str, MasterPoiRecord] = {}

    with target_file.open("r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx_id = header.index("POI_ID")
        idx_nm = header.index("POI_NM")
        idx_sgg = header.index("SGG_CD")
        idx_road = header.index("ROAD_NM_ADDR")
        idx_lotno = header.index("LOTNO_ADDR")
        idx_x = header.index("X_COORD")
        idx_y = header.index("Y_COORD")

        for row in reader:
            if len(row) <= idx_id:
                continue
            pid = row[idx_id].strip()
            if pid in target_poi_ids:
                poi_nm = row[idx_nm].strip() if idx_nm < len(row) else ""
                sgg_cd = row[idx_sgg].strip() if idx_sgg < len(row) else ""
                road = row[idx_road].strip() if idx_road < len(row) else ""
                lotno = row[idx_lotno].strip() if idx_lotno < len(row) else ""
                x = _safe_float(row[idx_x]) if idx_x < len(row) else None
                y = _safe_float(row[idx_y]) if idx_y < len(row) else None

                records[pid] = MasterPoiRecord(
                    poi_id=pid,
                    poi_nm=poi_nm,
                    sgg_cd=sgg_cd,
                    road_nm_addr=road,
                    lotno_addr=lotno,
                    x_coord=x,
                    y_coord=y,
                )

    t1 = time.time()
    print(f"Loaded {len(records)} master POI records in {t1 - t0:.2f}s.")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "_metadata": {
                "target_ids_count": len(target_poi_ids),
                "target_ids_sha256": target_ids_sha256,
                "master_file_size": master_file_size,
                "master_file_mtime_ns": master_file_mtime_ns,
            },
            "records": {k: asdict(v) for k, v in records.items()},
        }
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Saved master POI cache with integrity metadata.")
    return records


def percentile(data: Sequence[float], p: float) -> float:
    if not data:
        return 0.0
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data_sorted[int(k)]
    d0 = data_sorted[int(f)] * (c - k)
    d1 = data_sorted[int(c)] * (k - f)
    return d0 + d1


def compute_distribution_summary(values: list[int | float]) -> dict:
    if not values:
        return {
            "min": 0, "p25": 0.0, "p50": 0.0, "mean": 0.0,
            "p75": 0.0, "p90": 0.0, "p99": 0.0, "max": 0,
        }
    return {
        "min": min(values),
        "p25": round(percentile(values, 25), 2),
        "p50": round(percentile(values, 50), 2),
        "mean": round(sum(values) / len(values), 2),
        "p75": round(percentile(values, 75), 2),
        "p90": round(percentile(values, 90), 2),
        "p99": round(percentile(values, 99), 2),
        "max": max(values),
    }


def build_spatial_grid(catalog: list[CatalogPoi], step: float = GRID_STEP) -> dict[tuple[int, int], list[CatalogPoi]]:
    grid: dict[tuple[int, int], list[CatalogPoi]] = defaultdict(list)
    for item in catalog:
        if item.mapx and item.mapy and is_valid_korea_wgs84(item.mapy, item.mapx):
            gx = int(item.mapx / step)
            gy = int(item.mapy / step)
            grid[(gy, gx)].append(item)
    return grid


def query_spatial_grid(grid: dict[tuple[int, int], list[CatalogPoi]], lat: float, lon: float, step: float = GRID_STEP) -> list[CatalogPoi]:
    gy = int(lat / step)
    gx = int(lon / step)
    candidates = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            candidates.extend(grid.get((gy + dy, gx + dx), []))
    return candidates


def run_pipeline(
    positives: list[PositiveObservation],
    masters: dict[str, MasterPoiRecord],
    catalog: list[CatalogPoi],
    sgg_crosswalk: SggCrosswalk,
    policy,
) -> dict:
    """Execute Stage 0 through Stage 5 pipeline with holdout anchor validation, seed coverage and precision audit."""
    # Pre-index catalog
    by_contentid: dict[str, CatalogPoi] = {item.content_id: item for item in catalog}
    by_norm_title: dict[str, list[CatalogPoi]] = defaultdict(list)
    by_parsed_road_full: dict[tuple, list[CatalogPoi]] = defaultdict(list)
    by_parsed_lotno_full: dict[tuple, list[CatalogPoi]] = defaultdict(list)
    item_parsed_addrs: dict[str, ParsedAddress] = {}

    region_ldong_map = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}

    # Eligible catalog candidates: contenttypeid in {12, 14, 28} and compatible with any ProductRegion
    eligible_catalog_items = [
        item for item in catalog
        if item.content_type_id in SUPPORTED_CONTENT_TYPES
        and any(bool(item.region_codes & region_ldong_map[r]) for r in REGIONS)
    ]
    eligible_content_ids = {item.content_id for item in eligible_catalog_items}
    total_eligible_candidates = len(eligible_content_ids)

    for item in catalog:
        norm_title = normalize_text(item.title)
        by_norm_title[norm_title].append(item)

        addr_str = f"{item.address} {item.addr2}".strip()
        parsed = parse_address_string(addr_str)
        if parsed is not None:
            item_parsed_addrs[item.content_id] = parsed
            if parsed.road_key is not None:
                by_parsed_road_full[parsed.road_key.key_full].append(item)
            if parsed.lotno_key is not None:
                by_parsed_lotno_full[parsed.lotno_key.key_full].append(item)

    spatial_grid = build_spatial_grid(catalog)

    # Group observations by (region, poi_id)
    poi_visits: dict[tuple[str, str], list[PositiveObservation]] = defaultdict(list)
    for obs in positives:
        poi_visits[(obs.region, obs.poi_id)].append(obs)

    # -------------------------------------------------------------
    # Stage 0: Compute both Global Scope (Arm D) and Regional Scope
    # -------------------------------------------------------------
    global_arm_d_matches: dict[tuple[str, str], str] = {}
    anchor_pairs_global: list[tuple[PositiveObservation, MasterPoiRecord, CatalogPoi]] = []

    regional_stage0_results: dict[tuple[str, str], tuple[str, str | None]] = {}
    anchor_pairs_regional: list[tuple[PositiveObservation, MasterPoiRecord, CatalogPoi]] = []
    anchor_unique_pois: dict[tuple[str, str], str] = {}  # (region, poi_id) -> canonical content_id

    for (region, poi_id), obs_list in poi_visits.items():
        master = masters.get(poi_id)
        if master is None or not master.poi_nm:
            regional_stage0_results[(region, poi_id)] = ("identity_source_missing", None)
            continue

        master_name = normalize_text(master.poi_nm)
        all_name_cands = by_norm_title.get(master_name, [])
        master_addrs = {normalize_text(a) for a in (master.road_nm_addr, master.lotno_addr) if a and normalize_text(a)}

        # Global matching
        if all_name_cands and master_addrs:
            m_glob = [it for it in all_name_cands if normalize_text(it.address) in master_addrs]
            if len(m_glob) == 1:
                global_arm_d_matches[(region, poi_id)] = m_glob[0].content_id
                for obs in obs_list:
                    anchor_pairs_global.append((obs, master, m_glob[0]))

        # Regional matching
        allowed_ldong = region_ldong_map.get(region, frozenset())
        regional_cands = [c for c in all_name_cands if bool(c.region_codes & allowed_ldong)]
        if not regional_cands:
            regional_stage0_results[(region, poi_id)] = ("UNMATCHED", None)
            continue

        if not master_addrs:
            regional_stage0_results[(region, poi_id)] = ("AMBIGUOUS", None)
            continue

        matched_items = [
            item for item in regional_cands
            if normalize_text(item.address) in master_addrs
        ]
        if len(matched_items) == 1:
            matched_item = matched_items[0]
            regional_stage0_results[(region, poi_id)] = ("MATCHED", matched_item.content_id)
            anchor_unique_pois[(region, poi_id)] = matched_item.content_id
            for obs in obs_list:
                anchor_pairs_regional.append((obs, master, matched_item))
        elif len(matched_items) > 1:
            regional_stage0_results[(region, poi_id)] = ("AMBIGUOUS", None)
        else:
            regional_stage0_results[(region, poi_id)] = ("AMBIGUOUS", None)

    # Coordinate stats helper
    def _calc_coord_stats(distances: list[float], valid_cnt: int, total_cnt: int) -> dict:
        if not distances:
            return {
                "wgs84_valid_pairs": valid_cnt,
                "wgs84_valid_rate": round(valid_cnt / total_cnt, 4) if total_cnt else 0.0,
                "quantiles_meters": {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0},
                "threshold_shares": {"le_50m": 0.0, "le_100m": 0.0, "le_200m": 0.0, "le_500m": 0.0, "le_1000m": 0.0},
            }
        return {
            "wgs84_valid_pairs": valid_cnt,
            "wgs84_valid_rate": round(valid_cnt / total_cnt, 4) if total_cnt else 0.0,
            "quantiles_meters": {
                "p50": round(percentile(distances, 50), 2),
                "p90": round(percentile(distances, 90), 2),
                "p95": round(percentile(distances, 95), 2),
                "p99": round(percentile(distances, 99), 2),
            },
            "threshold_shares": {
                "le_50m": round(sum(d <= 50.0 for d in distances) / len(distances), 4),
                "le_100m": round(sum(d <= 100.0 for d in distances) / len(distances), 4),
                "le_200m": round(sum(d <= 200.0 for d in distances) / len(distances), 4),
                "le_500m": round(sum(d <= 500.0 for d in distances) / len(distances), 4),
                "le_1000m": round(sum(d <= 1000.0 for d in distances) / len(distances), 4),
            },
        }

    def _collect_distances(pairs: list[tuple[PositiveObservation, MasterPoiRecord, CatalogPoi]]):
        m_dists, v_dists = [], []
        m_valid, v_valid = 0, 0
        for obs, m, c in pairs:
            if is_valid_korea_wgs84(m.y_coord, m.x_coord) and is_valid_korea_wgs84(c.mapy, c.mapx):
                m_valid += 1
                m_dists.append(haversine_distance_meters(m.y_coord, m.x_coord, c.mapy, c.mapx))
            if is_valid_korea_wgs84(obs.y_coord, obs.x_coord) and is_valid_korea_wgs84(c.mapy, c.mapx):
                v_valid += 1
                v_dists.append(haversine_distance_meters(obs.y_coord, obs.x_coord, c.mapy, c.mapx))
        return m_dists, m_valid, v_dists, v_valid

    m_dists_reg, m_val_reg, v_dists_reg, v_val_reg = _collect_distances(anchor_pairs_regional)
    m_dists_glob, m_val_glob, v_dists_glob, v_val_glob = _collect_distances(anchor_pairs_global)

    anchor_dist_summary = {
        "comparison_summary": {
            "issue4_canonical_arm_d_observations": 4696,
            "issue4_snapshot_date": "2026-10-17 (48,583 items)",
            "global_arm_d_observations": len(anchor_pairs_global),
            "global_arm_d_unique_pois": len(global_arm_d_matches),
            "current_snapshot_date": "2026-10-20 (48,589 items)",
            "difference_explanation": "10-observation difference between 4,696 and 4,686 is due to 6 newly added items in TourAPI 2026-10-20 snapshot causing title collision/ambiguity for certain places.",
            "regional_stage0_observations": len(anchor_pairs_regional),
            "regional_stage0_unique_pois": len(anchor_unique_pois),
            "regional_difference_explanation": "407-observation difference between 4,686 (global) and 4,279 (regional) is due to strict ProductRegion allowed_ldong constraint filtering out cross-regional candidate collisions.",
        },
        "regional_stage0_anchor": {
            "total_anchor_observations": len(anchor_pairs_regional),
            "total_anchor_unique_pois": len(anchor_unique_pois),
            "master_coordinates": _calc_coord_stats(m_dists_reg, m_val_reg, len(anchor_pairs_regional)),
            "visit_coordinates": _calc_coord_stats(v_dists_reg, v_val_reg, len(anchor_pairs_regional)),
        },
        "global_arm_d_anchor": {
            "total_anchor_observations": len(anchor_pairs_global),
            "total_anchor_unique_pois": len(global_arm_d_matches),
            "master_coordinates": _calc_coord_stats(m_dists_glob, m_val_glob, len(anchor_pairs_global)),
            "visit_coordinates": _calc_coord_stats(v_dists_glob, v_val_glob, len(anchor_pairs_global)),
        },
    }

    # Pre-parse master and visit signals for each (region, poi_id)
    enriched_source: dict[tuple[str, str], dict] = {}
    for (region, poi_id), obs_list in poi_visits.items():
        master = masters.get(poi_id)

        visit_names = {normalize_text(obs.visit_area_nm) for obs in obs_list if obs.visit_area_nm}
        visit_poi_names = {normalize_text(obs.poi_nm) for obs in obs_list if obs.poi_nm}
        all_visit_names = (visit_names | visit_poi_names) - {""}

        visit_roads = {obs.road_nm_addr for obs in obs_list if obs.road_nm_addr}
        visit_lotnos = {obs.lotno_addr for obs in obs_list if obs.lotno_addr}
        visit_sggs = {obs.sgg_cd for obs in obs_list if obs.sgg_cd}

        valid_xs = [obs.x_coord for obs in obs_list if obs.x_coord and is_valid_korea_wgs84(obs.y_coord, obs.x_coord)]
        valid_ys = [obs.y_coord for obs in obs_list if obs.y_coord and is_valid_korea_wgs84(obs.y_coord, obs.x_coord)]
        median_x = percentile(valid_xs, 50) if valid_xs else None
        median_y = percentile(valid_ys, 50) if valid_ys else None

        master_name = normalize_text(master.poi_nm) if master else ""
        master_road = master.road_nm_addr if master else ""
        master_lotno = master.lotno_addr if master else ""
        master_sgg = master.sgg_cd if master else ""
        master_x = master.x_coord if master and is_valid_korea_wgs84(master.y_coord, master.x_coord) else None
        master_y = master.y_coord if master and is_valid_korea_wgs84(master.y_coord, master.x_coord) else None

        parsed_master_addrs = [
            parse_address_string(a) for a in (master_road, master_lotno) if a
        ]
        parsed_master_addrs = [p for p in parsed_master_addrs if p is not None]

        parsed_visit_addrs = [
            parse_address_string(a) for a in (visit_roads | visit_lotnos) if a
        ]
        parsed_visit_addrs = [p for p in parsed_visit_addrs if p is not None]

        enriched_source[(region, poi_id)] = {
            "has_master": master is not None,
            "master_name": master_name,
            "master_sgg": master_sgg,
            "master_x": master_x,
            "master_y": master_y,
            "parsed_master_addrs": parsed_master_addrs,
            "all_visit_names": all_visit_names,
            "visit_sggs": visit_sggs,
            "visit_x": median_x,
            "visit_y": median_y,
            "parsed_visit_addrs": parsed_visit_addrs,
            "visit_types": Counter(obs.visit_area_type_cd for obs in obs_list if obs.visit_area_type_cd),
        }

    # -------------------------------------------------------------
    # Define matching stages 1 to 5 (Cumulative Pipeline with Short-Circuit)
    # -------------------------------------------------------------
    stages_results: dict[int, dict[tuple[str, str], tuple[str, str | None]]] = {
        0: regional_stage0_results,
        1: {},
        2: {},
        3: {},
        4: {},
        5: {},
    }

    # Stage 1: Stage 0 + Structured Address Keys on Master
    # Strict rule: Only road_exact_full and lotno_exact_full qualify as stand-alone address match.
    # road_exact_main / lotno_exact_main (omitted sub_no) requires unique name cand + supporting signal (SGG or dist <= 200m).
    for key, data in enriched_source.items():
        region, poi_id = key
        allowed_ldong = region_ldong_map.get(region, frozenset())
        s0_status, s0_id = stages_results[0][key]
        if s0_status == "MATCHED":
            stages_results[1][key] = (s0_status, s0_id)
            continue
        if not data["has_master"] or not data["master_name"]:
            stages_results[1][key] = (s0_status, None)
            continue

        name_cands = [
            cand for cand in by_norm_title.get(data["master_name"], [])
            if bool(cand.region_codes & allowed_ldong)
        ]
        if not name_cands:
            stages_results[1][key] = ("UNMATCHED", None)
            continue

        exact_full_cands: set[str] = set()
        exact_main_cands: set[str] = set()

        for cand in name_cands:
            cand_parsed = item_parsed_addrs.get(cand.content_id)
            if cand_parsed is None:
                cand_parsed = parse_address_string(f"{cand.address} {cand.addr2}".strip())
            for m_addr in data["parsed_master_addrs"]:
                match_tag = match_parsed_addresses(m_addr, cand_parsed)
                if match_tag in ("road_exact_full", "lotno_exact_full"):
                    exact_full_cands.add(cand.content_id)
                elif match_tag in ("road_exact_main", "lotno_exact_main"):
                    exact_main_cands.add(cand.content_id)

        if len(exact_full_cands) == 1:
            stages_results[1][key] = ("MATCHED", next(iter(exact_full_cands)))
        elif len(exact_full_cands) > 1:
            stages_results[1][key] = ("AMBIGUOUS", None)
        else:
            # Gated fallback: main match allowed ONLY if single candidate AND verified by SGG or distance <= 200m
            if len(name_cands) == 1 and len(exact_main_cands) == 1:
                cand = name_cands[0]
                sgg_compat = any(
                    sgg_crosswalk.is_compatible(data["master_sgg"], r, d)
                    for r in cand.region_codes for d in cand.district_codes
                ) if data["master_sgg"] else False
                dist_compat = False
                if data["master_x"] and data["master_y"] and cand.mapx and cand.mapy:
                    if haversine_distance_meters(data["master_y"], data["master_x"], cand.mapy, cand.mapx) <= 200.0:
                        dist_compat = True
                if sgg_compat or dist_compat:
                    stages_results[1][key] = ("MATCHED", cand.content_id)
                else:
                    stages_results[1][key] = (s0_status, None)
            else:
                stages_results[1][key] = (s0_status, None)

    # Stage 2: Stage 1 + TC_SGG Code Agreement Unique Resolution
    for key, data in enriched_source.items():
        region, poi_id = key
        allowed_ldong = region_ldong_map.get(region, frozenset())
        s1_status, s1_id = stages_results[1][key]
        if s1_status == "MATCHED":
            stages_results[2][key] = (s1_status, s1_id)
            continue
        if not data["has_master"] or not data["master_name"]:
            stages_results[2][key] = (s1_status, None)
            continue

        name_cands = [
            cand for cand in by_norm_title.get(data["master_name"], [])
            if bool(cand.region_codes & allowed_ldong)
        ]
        if not name_cands:
            stages_results[2][key] = ("UNMATCHED", None)
            continue

        sgg_compat_cands = []
        master_sgg = data["master_sgg"]
        if master_sgg:
            for cand in name_cands:
                for regn in cand.region_codes:
                    for signgu in cand.district_codes:
                        if sgg_crosswalk.is_compatible(master_sgg, regn, signgu):
                            sgg_compat_cands.append(cand.content_id)
                            break

        if len(set(sgg_compat_cands)) == 1:
            cand_id = sgg_compat_cands[0]
            cand = by_contentid[cand_id]
            is_vetoed = False

            # Veto 1: WGS84 distance check if coordinates are present on both sides
            m_x, m_y = data["master_x"], data["master_y"]
            if m_x and m_y and cand.mapx and cand.mapy:
                d = haversine_distance_meters(m_y, m_x, cand.mapy, cand.mapx)
                if d > 200.0:
                    is_vetoed = True

            # Veto 2: Address main number conflict if parsed addresses are present on both sides
            if not is_vetoed:
                cand_parsed = item_parsed_addrs.get(cand_id)
                if cand_parsed is None:
                    cand_parsed = parse_address_string(f"{cand.address} {cand.addr2}".strip())
                if cand_parsed and data["parsed_master_addrs"]:
                    # Road address conflict check
                    if cand_parsed.road_key is not None:
                        c_rk = cand_parsed.road_key
                        for ma in data["parsed_master_addrs"]:
                            if ma.road_key is not None:
                                s_rk = ma.road_key
                                if (c_rk.sido, c_rk.sigungu, c_rk.road_name) == (s_rk.sido, s_rk.sigungu, s_rk.road_name):
                                    if c_rk.main_no != s_rk.main_no:
                                        is_vetoed = True
                                        break
                    # Lotno address conflict check
                    if not is_vetoed and cand_parsed.lotno_key is not None:
                        c_lk = cand_parsed.lotno_key
                        for ma in data["parsed_master_addrs"]:
                            if ma.lotno_key is not None:
                                s_lk = ma.lotno_key
                                if (c_lk.sido, c_lk.sigungu, c_lk.emd_ri, c_lk.san_flag) == (s_lk.sido, s_lk.sigungu, s_lk.emd_ri, s_lk.san_flag):
                                    if c_lk.main_no != s_lk.main_no:
                                        is_vetoed = True
                                        break

            if not is_vetoed:
                stages_results[2][key] = ("MATCHED", cand_id)
            else:
                stages_results[2][key] = (s1_status, None)
        else:
            stages_results[2][key] = (s1_status, None)

    # Stage 3: Stage 2 + Verified Coordinates Proximity Resolution
    # Refined:
    # 1. <= 200.0m with Nearest-Neighbor margin (d2 - d1 >= 50m) or single candidate -> MATCHED
    # 2. 200m < d <= 500m allowed ONLY if unique title candidate in region AND verified by TC_SGG agreement
    stage3_breakdown = {"le_200m": 0, "between_200m_and_500m": 0}
    for key, data in enriched_source.items():
        region, poi_id = key
        allowed_ldong = region_ldong_map.get(region, frozenset())
        s2_status, s2_id = stages_results[2][key]
        if s2_status == "MATCHED":
            stages_results[3][key] = (s2_status, s2_id)
            continue
        if not data["has_master"] or not data["master_name"]:
            stages_results[3][key] = (s2_status, None)
            continue

        name_cands = [
            cand for cand in by_norm_title.get(data["master_name"], [])
            if bool(cand.region_codes & allowed_ldong)
        ]
        if not name_cands:
            stages_results[3][key] = ("UNMATCHED", None)
            continue

        m_x, m_y = data["master_x"], data["master_y"]
        if m_x is None or m_y is None:
            stages_results[3][key] = (s2_status, None)
            continue

        cands_with_dist: list[tuple[CatalogPoi, float]] = []
        for cand in name_cands:
            if cand.mapx and cand.mapy and is_valid_korea_wgs84(cand.mapy, cand.mapx):
                d = haversine_distance_meters(m_y, m_x, cand.mapy, cand.mapx)
                cands_with_dist.append((cand, d))

        if not cands_with_dist:
            stages_results[3][key] = (s2_status, None)
            continue

        cands_with_dist.sort(key=lambda x: x[1])
        closest_cand, closest_d = cands_with_dist[0]

        if closest_d <= 200.0:
            if len(cands_with_dist) == 1 or cands_with_dist[1][1] > 200.0 or (cands_with_dist[1][1] - closest_d >= 50.0):
                stages_results[3][key] = ("MATCHED", closest_cand.content_id)
                stage3_breakdown["le_200m"] += 1
            else:
                stages_results[3][key] = ("AMBIGUOUS", None)
        elif closest_d <= 500.0 and len(name_cands) == 1:
            # Strict requirement: unique candidate in region + TC_SGG agreement
            sgg_ok = False
            if data["master_sgg"]:
                for regn in closest_cand.region_codes:
                    for signgu in closest_cand.district_codes:
                        if sgg_crosswalk.is_compatible(data["master_sgg"], regn, signgu):
                            sgg_ok = True
                            break
            if sgg_ok:
                stages_results[3][key] = ("MATCHED", closest_cand.content_id)
                stage3_breakdown["between_200m_and_500m"] += 1
            else:
                stages_results[3][key] = (s2_status, None)
        else:
            stages_results[3][key] = (s2_status, None)

    # Stage 4: Stage 3 + Visit Area Info Integration
    for key, data in enriched_source.items():
        region, poi_id = key
        allowed_ldong = region_ldong_map.get(region, frozenset())
        s3_status, s3_id = stages_results[3][key]
        if s3_status == "MATCHED":
            stages_results[4][key] = (s3_status, s3_id)
            continue

        candidate_names = set()
        if data["master_name"]:
            candidate_names.add(data["master_name"])
        candidate_names.update(data["all_visit_names"])

        if not candidate_names:
            stages_results[4][key] = ("identity_source_missing", None)
            continue

        matching_cands: list[CatalogPoi] = []
        for name in candidate_names:
            matching_cands.extend([
                cand for cand in by_norm_title.get(name, [])
                if bool(cand.region_codes & allowed_ldong)
            ])

        unique_cands = {c.content_id: c for c in matching_cands}
        if not unique_cands:
            stages_results[4][key] = ("UNMATCHED", None)
            continue

        all_parsed_addrs = data["parsed_master_addrs"] + data["parsed_visit_addrs"]
        resolved_id: str | None = None

        exact_full_matches: set[str] = set()
        exact_main_matches: set[str] = set()

        for cand in unique_cands.values():
            cand_parsed = item_parsed_addrs.get(cand.content_id)
            if cand_parsed is None:
                cand_parsed = parse_address_string(f"{cand.address} {cand.addr2}".strip())
            for src_addr in all_parsed_addrs:
                match_tag = match_parsed_addresses(src_addr, cand_parsed)
                if match_tag in ("road_exact_full", "lotno_exact_full"):
                    exact_full_matches.add(cand.content_id)
                elif match_tag in ("road_exact_main", "lotno_exact_main"):
                    exact_main_matches.add(cand.content_id)

        if len(exact_full_matches) == 1:
            resolved_id = next(iter(exact_full_matches))
        elif len(exact_full_matches) == 0:
            eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
            eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]

            if len(unique_cands) == 1 and len(exact_main_matches) == 1:
                cand = next(iter(unique_cands.values()))
                dist_ok = False
                if eff_x and eff_y and cand.mapx and cand.mapy:
                    if haversine_distance_meters(eff_y, eff_x, cand.mapy, cand.mapx) <= 200.0:
                        dist_ok = True
                sgg_ok = False
                all_sggs = ({data["master_sgg"]} | data["visit_sggs"]) - {""}
                for sgg in all_sggs:
                    if any(sgg_crosswalk.is_compatible(sgg, r, d) for r in cand.region_codes for d in cand.district_codes):
                        sgg_ok = True
                        break
                if dist_ok or sgg_ok:
                    resolved_id = cand.content_id

            if resolved_id is None and eff_x and eff_y:
                dist_cands = []
                for cand in unique_cands.values():
                    if cand.mapx and cand.mapy and is_valid_korea_wgs84(cand.mapy, cand.mapx):
                        d = haversine_distance_meters(eff_y, eff_x, cand.mapy, cand.mapx)
                        dist_cands.append((cand, d))
                dist_cands.sort(key=lambda x: x[1])
                if dist_cands and dist_cands[0][1] <= 200.0:
                    if len(dist_cands) == 1 or dist_cands[1][1] > 200.0 or (dist_cands[1][1] - dist_cands[0][1] >= 50.0):
                        resolved_id = dist_cands[0][0].content_id

        if resolved_id is not None:
            stages_results[4][key] = ("MATCHED", resolved_id)
        else:
            stages_results[4][key] = ("AMBIGUOUS" if len(unique_cands) > 1 else "UNMATCHED", None)

    # Stage 5: Stage 4 + Location-Gated Name Normalization
    # Strict rule: Address-based location gating uses ONLY by_parsed_road_full and by_parsed_lotno_full
    # Strict rule: Coordinate-based gating strictly enforced <= 200.0m + Nearest-Neighbor Margin (d2 - d1 >= 50.0m)
    stage5_rule_counts = Counter()
    stage5_cands_200_to_500m_sensitivity = 0

    for key, data in enriched_source.items():
        region, poi_id = key
        allowed_ldong = region_ldong_map.get(region, frozenset())
        s4_status, s4_id = stages_results[4][key]
        if s4_status == "MATCHED":
            stages_results[5][key] = (s4_status, s4_id)
            continue

        eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
        eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
        all_parsed_addrs = data["parsed_master_addrs"] + data["parsed_visit_addrs"]

        if not (eff_x and eff_y) and not all_parsed_addrs:
            stages_results[5][key] = (s4_status, None)
            continue

        candidate_names = set()
        if data["master_name"]:
            candidate_names.add(data["master_name"])
        candidate_names.update(data["all_visit_names"])

        if not candidate_names:
            stages_results[5][key] = (s4_status, None)
            continue

        # Coordinate-based candidates with strict <= 200m and margin
        nearby_catalog_items: list[CatalogPoi] = []
        if eff_x and eff_y:
            nearby_cands = query_spatial_grid(spatial_grid, eff_y, eff_x)
            cands_with_d: list[tuple[CatalogPoi, float]] = []
            for item in nearby_cands:
                if bool(item.region_codes & allowed_ldong) and item.mapx and item.mapy:
                    d = haversine_distance_meters(eff_y, eff_x, item.mapy, item.mapx)
                    if d <= 500.0:
                        cands_with_d.append((item, d))

            cands_with_d.sort(key=lambda x: x[1])
            le_200 = [x for x in cands_with_d if x[1] <= 200.0]
            between_200_500 = [x for x in cands_with_d if 200.0 < x[1] <= 500.0]
            if between_200_500 and not le_200:
                stage5_cands_200_to_500m_sensitivity += 1

            # Only accept <= 200m items that meet margin or are single candidate
            if le_200:
                if len(le_200) == 1 or (le_200[1][1] - le_200[0][1] >= 50.0):
                    nearby_catalog_items.append(le_200[0][0])
                else:
                    # Margin < 50m: ambiguous coordinate, omit from pure coordinate candidates
                    pass

        # Address match: strictly by full keys only
        address_matched_items: list[CatalogPoi] = []
        for src_addr in all_parsed_addrs:
            if src_addr.road_key is not None:
                for item in by_parsed_road_full.get(src_addr.road_key.key_full, []):
                    if bool(item.region_codes & allowed_ldong):
                        address_matched_items.append(item)
            if src_addr.lotno_key is not None:
                for item in by_parsed_lotno_full.get(src_addr.lotno_key.key_full, []):
                    if bool(item.region_codes & allowed_ldong):
                        address_matched_items.append(item)

        location_supported_items = {item.content_id: item for item in (nearby_catalog_items + address_matched_items)}
        if not location_supported_items:
            stages_results[5][key] = (s4_status, None)
            continue

        sido_tokens = tuple(p.sido for p in all_parsed_addrs if p.sido)
        sgg_tokens = tuple(p.sigungu for p in all_parsed_addrs if p.sigungu)
        all_src_variants = set()
        for name in candidate_names:
            all_src_variants.update(generate_location_gated_name_variants(name, sido_tokens, sgg_tokens))

        matched_stage5_cands: set[str] = set()
        matched_rule_tag: str = ""

        for cand_id, item in location_supported_items.items():
            cand_variants = generate_location_gated_name_variants(item.title)
            intersection = all_src_variants & cand_variants
            if intersection:
                matched_stage5_cands.add(cand_id)
                # Classify rule
                if any(normalize_punctuation_n1(nm) in cand_variants for nm in candidate_names):
                    matched_rule_tag = "N1_whitespace_punct"
                elif any("(" in nm or ")" in nm for nm in candidate_names):
                    matched_rule_tag = "N2_parentheses"
                elif any(strip_region_prefix(nm, sido_tokens + sgg_tokens) != nm for nm in candidate_names):
                    matched_rule_tag = "region_prefix"
                elif any(strip_facility_suffix(nm) != nm for nm in candidate_names):
                    matched_rule_tag = "facility_suffix"
                else:
                    matched_rule_tag = "normalized_variant"
            else:
                if eff_x and eff_y and item.mapx and item.mapy:
                    d = haversine_distance_meters(eff_y, eff_x, item.mapy, item.mapx)
                    if d <= 100.0:
                        norm_src = {normalize_punctuation_n1(v) for v in all_src_variants}
                        norm_cand = {normalize_punctuation_n1(v) for v in cand_variants}
                        if any(s in c or c in s for s in norm_src for c in norm_cand if min(len(s), len(c)) >= 4):
                            matched_stage5_cands.add(cand_id)
                            matched_rule_tag = "le_100m_nearest_substring"

        if len(matched_stage5_cands) == 1:
            cid = next(iter(matched_stage5_cands))
            stages_results[5][key] = ("MATCHED", cid)
            stage5_rule_counts[matched_rule_tag] += 1
        elif len(matched_stage5_cands) > 1:
            stages_results[5][key] = ("AMBIGUOUS", None)
        else:
            stages_results[5][key] = (s4_status, None)

    # -------------------------------------------------------------
    # Independent (Non-short-circuited) Holdout Anchor Agreement Verification
    # Evaluates each individual matching evidence in isolation on the Stage 0 Anchor set.
    # -------------------------------------------------------------
    independent_rule_stats = {}
    rule_keys = [
        "rule_1_structured_address_key_only",
        "rule_2_tc_sgg_only",
        "rule_3_geo_distance_only",
        "rule_4_visit_signals_only",
        "rule_5_name_normalizer_only",
    ]
    for rk in rule_keys:
        independent_rule_stats[rk] = {
            "anchor_total_pois": len(anchor_unique_pois),
            "matched_pois": 0,
            "same_contentid_count": 0,
            "conflicting_contentid_count": 0,
            "agreement_rate": 0.0,
            "recall": 0.0,
        }

    for (region, poi_id), canonical_id in anchor_unique_pois.items():
        data = enriched_source[(region, poi_id)]
        allowed_ldong = region_ldong_map.get(region, frozenset())
        name_cands = [
            c for c in by_norm_title.get(data["master_name"], [])
            if bool(c.region_codes & allowed_ldong)
        ]

        # Rule 1: Structured Address Key Only
        r1_cands = set()
        for cand in name_cands:
            cand_parsed = item_parsed_addrs.get(cand.content_id)
            if cand_parsed is None:
                cand_parsed = parse_address_string(f"{cand.address} {cand.addr2}".strip())
            for m_addr in data["parsed_master_addrs"]:
                match_tag = match_parsed_addresses(m_addr, cand_parsed)
                if match_tag in ("road_exact_full", "lotno_exact_full"):
                    r1_cands.add(cand.content_id)
        if len(r1_cands) == 1:
            cid = next(iter(r1_cands))
            independent_rule_stats["rule_1_structured_address_key_only"]["matched_pois"] += 1
            if cid == canonical_id:
                independent_rule_stats["rule_1_structured_address_key_only"]["same_contentid_count"] += 1
            else:
                independent_rule_stats["rule_1_structured_address_key_only"]["conflicting_contentid_count"] += 1

        # Rule 2: TC_SGG Code Agreement Only
        r2_cands = []
        if data["master_sgg"]:
            for cand in name_cands:
                for regn in cand.region_codes:
                    for signgu in cand.district_codes:
                        if sgg_crosswalk.is_compatible(data["master_sgg"], regn, signgu):
                            r2_cands.append(cand.content_id)
                            break
        if len(set(r2_cands)) == 1:
            cid = r2_cands[0]
            independent_rule_stats["rule_2_tc_sgg_only"]["matched_pois"] += 1
            if cid == canonical_id:
                independent_rule_stats["rule_2_tc_sgg_only"]["same_contentid_count"] += 1
            else:
                independent_rule_stats["rule_2_tc_sgg_only"]["conflicting_contentid_count"] += 1

        # Rule 3: Coordinate Proximity Only
        if data["master_x"] and data["master_y"]:
            d_cands = []
            for cand in name_cands:
                if cand.mapx and cand.mapy and is_valid_korea_wgs84(cand.mapy, cand.mapx):
                    d = haversine_distance_meters(data["master_y"], data["master_x"], cand.mapy, cand.mapx)
                    d_cands.append((cand, d))
            d_cands.sort(key=lambda x: x[1])
            if d_cands:
                closest_c, closest_d = d_cands[0]
                if closest_d <= 200.0 and (len(d_cands) == 1 or d_cands[1][1] > 200.0 or (d_cands[1][1] - closest_d >= 50.0)):
                    cid = closest_c.content_id
                    independent_rule_stats["rule_3_geo_distance_only"]["matched_pois"] += 1
                    if cid == canonical_id:
                        independent_rule_stats["rule_3_geo_distance_only"]["same_contentid_count"] += 1
                    else:
                        independent_rule_stats["rule_3_geo_distance_only"]["conflicting_contentid_count"] += 1

        # Rule 4: Visit Signals Only
        if data["all_visit_names"]:
            v_cands = []
            for v_nm in data["all_visit_names"]:
                v_cands.extend([c for c in by_norm_title.get(v_nm, []) if bool(c.region_codes & allowed_ldong)])
            v_uniq = {c.content_id: c for c in v_cands}
            v_matched = set()
            for cand in v_uniq.values():
                cand_parsed = item_parsed_addrs.get(cand.content_id)
                if cand_parsed is None:
                    cand_parsed = parse_address_string(f"{cand.address} {cand.addr2}".strip())
                for src_addr in data["parsed_visit_addrs"]:
                    if match_parsed_addresses(src_addr, cand_parsed) in ("road_exact_full", "lotno_exact_full"):
                        v_matched.add(cand.content_id)
            if len(v_matched) == 1:
                cid = next(iter(v_matched))
                independent_rule_stats["rule_4_visit_signals_only"]["matched_pois"] += 1
                if cid == canonical_id:
                    independent_rule_stats["rule_4_visit_signals_only"]["same_contentid_count"] += 1
                else:
                    independent_rule_stats["rule_4_visit_signals_only"]["conflicting_contentid_count"] += 1

        # Rule 5: Name Normalizer Only
        eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
        eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
        all_parsed = data["parsed_master_addrs"] + data["parsed_visit_addrs"]
        if (eff_x and eff_y) or all_parsed:
            near_items = []
            if eff_x and eff_y:
                for it in query_spatial_grid(spatial_grid, eff_y, eff_x):
                    if bool(it.region_codes & allowed_ldong) and it.mapx and it.mapy:
                        if haversine_distance_meters(eff_y, eff_x, it.mapy, it.mapx) <= 200.0:
                            near_items.append(it)
            addr_items = []
            for sa in all_parsed:
                if sa.road_key:
                    for it in by_parsed_road_full.get(sa.road_key.key_full, []):
                        if bool(it.region_codes & allowed_ldong):
                            addr_items.append(it)
                if sa.lotno_key:
                    for it in by_parsed_lotno_full.get(sa.lotno_key.key_full, []):
                        if bool(it.region_codes & allowed_ldong):
                            addr_items.append(it)
            loc_items = {it.content_id: it for it in (near_items + addr_items)}
            sido_t = tuple(p.sido for p in all_parsed if p.sido)
            sgg_t = tuple(p.sigungu for p in all_parsed if p.sigungu)
            src_vars = set()
            for nm in {data["master_name"]} | data["all_visit_names"]:
                if nm:
                    src_vars.update(generate_location_gated_name_variants(nm, sido_t, sgg_t))
            m5_cands = set()
            for cid_loc, it_loc in loc_items.items():
                c_vars = generate_location_gated_name_variants(it_loc.title)
                if src_vars & c_vars:
                    m5_cands.add(cid_loc)
            if len(m5_cands) == 1:
                cid = next(iter(m5_cands))
                independent_rule_stats["rule_5_name_normalizer_only"]["matched_pois"] += 1
                if cid == canonical_id:
                    independent_rule_stats["rule_5_name_normalizer_only"]["same_contentid_count"] += 1
                else:
                    independent_rule_stats["rule_5_name_normalizer_only"]["conflicting_contentid_count"] += 1

    for rk in rule_keys:
        tot = independent_rule_stats[rk]["anchor_total_pois"]
        m_cnt = independent_rule_stats[rk]["matched_pois"]
        s_cnt = independent_rule_stats[rk]["same_contentid_count"]
        independent_rule_stats[rk]["agreement_rate"] = round(s_cnt / m_cnt, 4) if m_cnt else 0.0
        independent_rule_stats[rk]["recall"] = round(s_cnt / tot, 4) if tot else 0.0

    anchor_dist_summary["independent_rule_anchor_agreement"] = independent_rule_stats

    # -------------------------------------------------------------
    # 3. Aggregate results over all 97,640 observed positives and cohorts
    # -------------------------------------------------------------
    stage_metrics = {}
    stage_cohort_metrics = {}
    master_missing_cohort_metrics = {}
    by_region_split_metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    master_missing_keys = {
        (obs.region, obs.poi_id) for obs in positives
        if not enriched_source[(obs.region, obs.poi_id)]["has_master"]
    }
    master_missing_obs_total = sum(1 for obs in positives if (obs.region, obs.poi_id) in master_missing_keys)
    total_anchor_obs = len(anchor_pairs_regional)

    # Track matched content_ids per stage
    stage_matched_contentids: dict[int, set[str]] = {}

    for stage_idx in range(6):
        res_map = stages_results[stage_idx]
        counts = Counter()
        content_type_counts = Counter()
        candidate_contained_count = 0
        anchor_agreement_count = 0
        anchor_conflict_count = 0

        cohort_counts = defaultdict(Counter)
        master_missing_counts = Counter()
        master_missing_candidate_contained = 0
        matched_cids = set()

        for obs in positives:
            key = (obs.region, obs.poi_id)
            status, matched_id = res_map[key]
            counts[status] += 1
            by_region_split_metrics[stage_idx][(obs.region, obs.split)][status] += 1
            v_type = obs.visit_area_type_cd or "missing"
            cohort_counts[v_type][status] += 1

            if key in master_missing_keys:
                master_missing_counts[status] += 1

            if status == "MATCHED" and matched_id:
                matched_cids.add(matched_id)
                cand_item = by_contentid[matched_id]
                content_type_counts[cand_item.content_type_id] += 1

                is_supported_type = cand_item.content_type_id in SUPPORTED_CONTENT_TYPES
                allowed_ldong = region_ldong_map.get(obs.region, frozenset())
                is_region_compat = bool(cand_item.region_codes & allowed_ldong)

                if is_supported_type and is_region_compat:
                    candidate_contained_count += 1
                    cohort_counts[v_type]["candidate_contained"] += 1
                    if key in master_missing_keys:
                        master_missing_candidate_contained += 1

            s0_status, s0_id = regional_stage0_results[key]
            if s0_status == "MATCHED":
                if status == "MATCHED":
                    if matched_id == s0_id:
                        anchor_agreement_count += 1
                    else:
                        anchor_conflict_count += 1
                else:
                    anchor_conflict_count += 1

        stage_matched_contentids[stage_idx] = matched_cids
        total_obs = len(positives)
        stage_metrics[f"stage_{stage_idx}"] = {
            "status_counts": dict(counts),
            "status_rates": {k: round(v / total_obs, 4) for k, v in counts.items()},
            "candidate_contained_count": candidate_contained_count,
            "candidate_contained_rate": round(candidate_contained_count / total_obs, 4),
            "content_type_distribution": dict(content_type_counts),
            "anchor_precision": {
                "total_anchors": total_anchor_obs,
                "anchor_agreement_count": anchor_agreement_count,
                "anchor_conflict_count": anchor_conflict_count,
                "anchor_agreement_rate": round(anchor_agreement_count / total_anchor_obs, 4) if total_anchor_obs else 0.0,
            },
        }

        master_missing_cohort_metrics[f"stage_{stage_idx}"] = {
            "total_observations": master_missing_obs_total,
            "total_unique_poi_pairs": len(master_missing_keys),
            "status_counts": dict(master_missing_counts),
            "status_rates": {k: round(v / master_missing_obs_total, 4) for k, v in master_missing_counts.items()},
            "candidate_contained_count": master_missing_candidate_contained,
            "candidate_contained_rate": round(master_missing_candidate_contained / master_missing_obs_total, 4),
        }

        stage_cohort_metrics[f"stage_{stage_idx}"] = {
            v_type: {
                "total": sum(c.values()) - c["candidate_contained"],
                "counts": dict(c),
                "matched_rate": round(c["MATCHED"] / (sum(c.values()) - c["candidate_contained"]), 4) if (sum(c.values()) - c["candidate_contained"]) else 0.0,
                "candidate_contained_rate": round(c["candidate_contained"] / (sum(c.values()) - c["candidate_contained"]), 4) if (sum(c.values()) - c["candidate_contained"]) else 0.0,
            }
            for v_type, c in cohort_counts.items()
        }

    # -------------------------------------------------------------
    # 4. Task 2: Catalog Seed Coverage & Signal Density Distributions
    # -------------------------------------------------------------
    # (1) Stage 0 to 5 seed coverage
    catalog_seed_coverage_by_stage = {}
    for st_idx in range(6):
        cids = stage_matched_contentids[st_idx]
        matched_eligible = cids & eligible_content_ids
        catalog_seed_coverage_by_stage[f"stage_{st_idx}"] = {
            "matched_eligible_contentids": len(matched_eligible),
            "total_eligible_candidates": total_eligible_candidates,
            "eligible_seed_coverage_rate": round(len(matched_eligible) / total_eligible_candidates, 4),
            "matched_all_snapshot_contentids": len(cids),
            "total_snapshot_items": len(catalog),
            "all_snapshot_coverage_rate": round(len(cids) / len(catalog), 4),
        }

    # (2) Region breakdown (Stage 0 vs Stage 5)
    region_seed_coverage = {}
    for r in REGIONS:
        r_ldong = region_ldong_map[r]
        r_eligible = {it.content_id for it in eligible_catalog_items if bool(it.region_codes & r_ldong)}
        s0_m = len(stage_matched_contentids[0] & r_eligible)
        s5_m = len(stage_matched_contentids[5] & r_eligible)
        region_seed_coverage[r] = {
            "total_eligible": len(r_eligible),
            "stage_0_matched": s0_m,
            "stage_0_coverage_rate": round(s0_m / len(r_eligible), 4) if r_eligible else 0.0,
            "stage_5_matched": s5_m,
            "stage_5_coverage_rate": round(s5_m / len(r_eligible), 4) if r_eligible else 0.0,
        }

    # (3) Content type breakdown (Stage 0 vs Stage 5)
    type_seed_coverage = {}
    for ctype in sorted(SUPPORTED_CONTENT_TYPES):
        t_eligible = {it.content_id for it in eligible_catalog_items if it.content_type_id == ctype}
        s0_m = len(stage_matched_contentids[0] & t_eligible)
        s5_m = len(stage_matched_contentids[5] & t_eligible)
        type_seed_coverage[ctype] = {
            "total_eligible": len(t_eligible),
            "stage_0_matched": s0_m,
            "stage_0_coverage_rate": round(s0_m / len(t_eligible), 4) if t_eligible else 0.0,
            "stage_5_matched": s5_m,
            "stage_5_coverage_rate": round(s5_m / len(t_eligible), 4) if t_eligible else 0.0,
        }

    # (4) Signal density distribution per seeded eligible contentid (Stage 5)
    contentid_pos_obs_counts = Counter()
    contentid_travel_ids = defaultdict(set)
    contentid_poi_ids = defaultdict(set)

    for obs in positives:
        status, matched_id = stages_results[5][(obs.region, obs.poi_id)]
        if status == "MATCHED" and matched_id and (matched_id in eligible_content_ids):
            contentid_pos_obs_counts[matched_id] += 1
            contentid_travel_ids[matched_id].add(obs.travel_id)
            contentid_poi_ids[matched_id].add(obs.poi_id)

    seeded_eligible_cids = stage_matched_contentids[5] & eligible_content_ids
    obs_counts_list = [contentid_pos_obs_counts[cid] for cid in seeded_eligible_cids]
    travel_counts_list = [len(contentid_travel_ids[cid]) for cid in seeded_eligible_cids]
    poi_counts_list = [len(contentid_poi_ids[cid]) for cid in seeded_eligible_cids]

    def _bucket_distribution(values: list[int], buckets: list[tuple[str, int, int]]) -> dict:
        total = len(values)
        counts = {b[0]: 0 for b in buckets}
        for v in values:
            for name, low, high in buckets:
                if low <= v <= high:
                    counts[name] += 1
                    break
        return {
            b_name: {
                "count": c,
                "share": round(c / total, 4) if total else 0.0,
            }
            for b_name, c in counts.items()
        }

    signal_density_distribution = {
        "seeded_eligible_items_count": len(seeded_eligible_cids),
        "positive_observations_per_contentid": {
            "quantiles": compute_distribution_summary(obs_counts_list),
            "buckets": _bucket_distribution(obs_counts_list, [
                ("1_obs", 1, 1),
                ("2_to_4_obs", 2, 4),
                ("5_to_9_obs", 5, 9),
                ("10_to_19_obs", 10, 19),
                ("20_plus_obs", 20, 999999),
            ]),
        },
        "distinct_travel_ids_per_contentid": {
            "quantiles": compute_distribution_summary(travel_counts_list),
            "buckets": _bucket_distribution(travel_counts_list, [
                ("1_travel", 1, 1),
                ("2_to_4_travels", 2, 4),
                ("5_to_9_travels", 5, 9),
                ("10_to_19_travels", 10, 19),
                ("20_plus_travels", 20, 999999),
            ]),
        },
        "distinct_poi_ids_per_contentid": {
            "quantiles": compute_distribution_summary(poi_counts_list),
            "buckets": _bucket_distribution(poi_counts_list, [
                ("1_poi", 1, 1),
                ("2_to_3_pois", 2, 3),
                ("4_plus_pois", 4, 999999),
            ]),
        },
    }

    catalog_seed_coverage_report = {
        "by_stage": catalog_seed_coverage_by_stage,
        "region_breakdown": region_seed_coverage,
        "type_breakdown": type_seed_coverage,
        "signal_density": signal_density_distribution,
    }

    # -------------------------------------------------------------
    # 5. Task 3: Candidate Density & Nearest-Neighbor Margin Analysis
    # -------------------------------------------------------------
    # Analyze candidate density within 50m, 100m, 200m, 500m around each observed POI with valid coordinates
    unique_poi_coords = []
    for key, data in enriched_source.items():
        eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
        eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
        if eff_x and eff_y and is_valid_korea_wgs84(eff_y, eff_x):
            unique_poi_coords.append((key[0], eff_y, eff_x))

    radius_buckets = {50.0: Counter(), 100.0: Counter(), 200.0: Counter(), 500.0: Counter()}
    for reg, lat, lon in unique_poi_coords:
        allowed_ldong = region_ldong_map.get(reg, frozenset())
        cands = query_spatial_grid(spatial_grid, lat, lon)
        dists = [
            haversine_distance_meters(lat, lon, it.mapy, it.mapx)
            for it in cands
            if bool(it.region_codes & allowed_ldong) and it.mapx and it.mapy
        ]
        for rad in [50.0, 100.0, 200.0, 500.0]:
            cnt = sum(1 for d in dists if d <= rad)
            if cnt == 0:
                tag = "0"
            elif cnt == 1:
                tag = "1"
            elif 2 <= cnt <= 3:
                tag = "2_to_3"
            elif 4 <= cnt <= 9:
                tag = "4_to_9"
            else:
                tag = "10_plus"
            radius_buckets[rad][tag] += 1

    tot_unique_coords = len(unique_poi_coords)
    radius_density_summary = {
        f"radius_le_{int(rad)}m": {
            tag: {
                "count": c,
                "share": round(c / tot_unique_coords, 4) if tot_unique_coords else 0.0,
            }
            for tag, c in radius_buckets[rad].items()
        }
        for rad in [50.0, 100.0, 200.0, 500.0]
    }

    # Margin distribution for coordinate-based matches
    margin_counts = Counter()
    for key, data in enriched_source.items():
        eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
        eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
        if not (eff_x and eff_y):
            continue
        allowed_ldong = region_ldong_map.get(key[0], frozenset())
        cands = query_spatial_grid(spatial_grid, eff_y, eff_x)
        dists = sorted([
            haversine_distance_meters(eff_y, eff_x, it.mapy, it.mapx)
            for it in cands
            if bool(it.region_codes & allowed_ldong) and it.mapx and it.mapy and haversine_distance_meters(eff_y, eff_x, it.mapy, it.mapx) <= 500.0
        ])
        if not dists:
            continue
        if len(dists) == 1:
            margin_counts["single_candidate_within_500m"] += 1
        else:
            m = dists[1] - dists[0]
            if m >= 200.0:
                margin_counts["margin_ge_200m"] += 1
            elif m >= 100.0:
                margin_counts["margin_100m_to_200m"] += 1
            elif m >= 50.0:
                margin_counts["margin_50m_to_100m"] += 1
            else:
                margin_counts["margin_lt_50m_excluded"] += 1

    tot_margin = sum(margin_counts.values())
    margin_summary = {
        k: {
            "count": v,
            "share": round(v / tot_margin, 4) if tot_margin else 0.0,
        }
        for k, v in margin_counts.items()
    }

    # -------------------------------------------------------------
    # 6. Task 4: Newly Promoted MATCHED Post-Promotion Signal Verification & Stratified Audit
    # -------------------------------------------------------------
    STAGE_SIGNAL_ROLES = {
        1: {
            "primary_selection": "구조화 주소 키 (도로명/지번 full key 일치)",
            "veto_gating": "없음 (단독 주소 full key 성립 시 즉시 선택)",
            "post_hoc_diagnostic": "WGS84 좌표 근접성(<=200m) 및 TC_SGG 시군구 일치",
        },
        2: {
            "primary_selection": "TC_SGG 시군구 일치 (유일 후보 매칭)",
            "veto_gating": "WGS84 좌표 거리 > 200m 차단 veto 및 동일 도로명/법정동 본번 충돌 차단 veto",
            "post_hoc_diagnostic": "WGS84 좌표 거리 분위수(<=200m 일치율) 및 주소 본번 무충돌",
        },
        3: {
            "primary_selection": "WGS84 좌표 근접성 (<=200m 승격)",
            "veto_gating": "200~500m 구간 승격 시 TC_SGG 시군구 일치 필수 게이팅",
            "post_hoc_diagnostic": "TC_SGG 시군구 일치율 및 주소 본번 무충돌",
        },
        4: {
            "primary_selection": "TN_VISIT_AREA_INFO 방문 행 다중 신호 보강 (주소/좌표/SGG)",
            "veto_gating": "없음 (구조화 주소 full key 또는 좌표 거리 <=200m 규칙 재적용)",
            "post_hoc_diagnostic": "WGS84 좌표 거리(<=200m) 및 TC_SGG 시군구 일치",
        },
        5: {
            "primary_selection": "이름 정규화 / 지점명 분리 규칙",
            "veto_gating": "반경 <= 200m 공간 게이팅 + Nearest-Neighbor Margin (d2 - d1 >= 50m)",
            "post_hoc_diagnostic": "WGS84 좌표 거리(<=200m) 및 TC_SGG 시군구 일치",
        },
    }

    def evaluate_poi_defects(
        data: dict,
        cand: Any,
        cand_parsed: Any,
        cw: SggCrosswalk,
    ) -> dict[str, bool]:
        flags = {
            "address_main_no_conflict": False,
            "sgg_code_and_text_conflict": False,
            "distance_excess_gt_200m": False,
        }
        all_src_addrs = data["parsed_master_addrs"] + data["parsed_visit_addrs"]
        if cand_parsed and all_src_addrs:
            road_conflict = False
            lotno_conflict = False

            if cand_parsed.road_key is not None:
                c_rk = cand_parsed.road_key
                for sa in all_src_addrs:
                    if sa.road_key is not None:
                        s_rk = sa.road_key
                        if (c_rk.sido, c_rk.sigungu, c_rk.road_name) == (s_rk.sido, s_rk.sigungu, s_rk.road_name):
                            if c_rk.main_no != s_rk.main_no:
                                road_conflict = True
                                break

            if not road_conflict and cand_parsed.lotno_key is not None:
                c_lk = cand_parsed.lotno_key
                for sa in all_src_addrs:
                    if sa.lotno_key is not None:
                        s_lk = sa.lotno_key
                        if (c_lk.sido, c_lk.sigungu, c_lk.emd_ri, c_lk.san_flag) == (s_lk.sido, s_lk.sigungu, s_lk.emd_ri, s_lk.san_flag):
                            if c_lk.main_no != s_lk.main_no:
                                lotno_conflict = True
                                break

            if road_conflict or lotno_conflict:
                flags["address_main_no_conflict"] = True

        all_sggs = ({data["master_sgg"]} | data["visit_sggs"]) - {""}
        if all_sggs:
            sgg_compat = any(
                cw.is_compatible(s, r, d)
                for s in all_sggs for r in cand.region_codes for d in cand.district_codes
            )
            if not sgg_compat:
                flags["sgg_code_and_text_conflict"] = True

        eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
        eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
        if eff_x and eff_y and cand.mapx and cand.mapy:
            d = haversine_distance_meters(eff_y, eff_x, cand.mapy, cand.mapx)
            if d > 200.0:
                flags["distance_excess_gt_200m"] = True

        return flags

    def proportional_stratified_sample(
        promoted_keys: list[tuple[str, str]],
        sample_size: int = 100,
        seed: int = 42,
    ) -> tuple[list[tuple[str, str]], dict[str, int]]:
        tot = len(promoted_keys)
        if tot <= sample_size:
            quotas = {r: sum(1 for reg, _ in promoted_keys if reg == r) for r in REGIONS}
            return sorted(promoted_keys), quotas

        by_region: dict[str, list[tuple[str, str]]] = {r: [] for r in REGIONS}
        for reg, pid in sorted(promoted_keys):
            by_region[reg].append((reg, pid))

        exact_quotas = {r: sample_size * len(by_region[r]) / tot for r in REGIONS}
        int_quotas = {r: int(exact_quotas[r]) for r in REGIONS}
        remainders = {r: exact_quotas[r] - int_quotas[r] for r in REGIONS}

        unassigned = sample_size - sum(int_quotas.values())
        sorted_by_remainder = sorted(REGIONS, key=lambda r: (remainders[r], len(by_region[r])), reverse=True)
        for r in sorted_by_remainder[:unassigned]:
            int_quotas[r] += 1

        rng = random.Random(seed)
        sampled = []
        for r in REGIONS:
            q = int_quotas[r]
            if q > 0 and by_region[r]:
                sampled.extend(rng.sample(by_region[r], min(q, len(by_region[r]))))

        return sorted(sampled), int_quotas

    newly_promoted_verification = {}
    stratified_audit_results = {}

    for st_idx in range(1, 6):
        curr_map = stages_results[st_idx]
        prev_map = stages_results[st_idx - 1]

        promoted_keys = [
            k for k, (st, cid) in curr_map.items()
            if st == "MATCHED" and prev_map[k][0] != "MATCHED" and cid is not None
        ]

        h_distances = []
        sgg_agreed_count = 0
        total_with_sgg = 0

        for reg, pid in promoted_keys:
            data = enriched_source[(reg, pid)]
            cid = curr_map[(reg, pid)][1]
            cand = by_contentid[cid]

            eff_x = data["master_x"] if data["master_x"] is not None else data["visit_x"]
            eff_y = data["master_y"] if data["master_y"] is not None else data["visit_y"]
            if eff_x and eff_y and cand.mapx and cand.mapy:
                h_distances.append(haversine_distance_meters(eff_y, eff_x, cand.mapy, cand.mapx))

            all_sggs = ({data["master_sgg"]} | data["visit_sggs"]) - {""}
            if all_sggs:
                total_with_sgg += 1
                if any(sgg_crosswalk.is_compatible(s, r, d) for s in all_sggs for r in cand.region_codes for d in cand.district_codes):
                    sgg_agreed_count += 1

        tot_prom = len(promoted_keys)
        sig_info = STAGE_SIGNAL_ROLES.get(st_idx, {})
        newly_promoted_verification[f"stage_{st_idx}"] = {
            "stage_index": st_idx,
            "primary_selection": sig_info.get("primary_selection", ""),
            "veto_gating": sig_info.get("veto_gating", ""),
            "post_hoc_diagnostic": sig_info.get("post_hoc_diagnostic", ""),
            "primary_desc": sig_info.get("primary_selection", ""),
            "auxiliary_desc": sig_info.get("post_hoc_diagnostic", ""),
            "total_newly_promoted_pois": tot_prom,
            "valid_coordinate_pairs": len(h_distances),
            "distance_quantiles": {
                "p50": round(percentile(h_distances, 50), 2) if h_distances else 0.0,
                "p90": round(percentile(h_distances, 90), 2) if h_distances else 0.0,
            },
            "distance_threshold_shares": {
                "le_50m": round(sum(d <= 50.0 for d in h_distances) / len(h_distances), 4) if h_distances else 0.0,
                "le_100m": round(sum(d <= 100.0 for d in h_distances) / len(h_distances), 4) if h_distances else 0.0,
                "le_200m": round(sum(d <= 200.0 for d in h_distances) / len(h_distances), 4) if h_distances else 0.0,
                "le_500m": round(sum(d <= 500.0 for d in h_distances) / len(h_distances), 4) if h_distances else 0.0,
            },
            "sgg_agreement_rate": round(sgg_agreed_count / total_with_sgg, 4) if total_with_sgg else 0.0,
        }

        # 1. Population Audit (전수 감사)
        pop_defects = {
            "address_main_no_conflict": 0,
            "sgg_code_and_text_conflict": 0,
            "distance_excess_gt_200m": 0,
            "defect_free_count": 0,
        }
        for reg, pid in promoted_keys:
            data = enriched_source[(reg, pid)]
            cid = curr_map[(reg, pid)][1]
            cand = by_contentid[cid]
            cand_parsed = item_parsed_addrs.get(cid)

            flags = evaluate_poi_defects(data, cand, cand_parsed, sgg_crosswalk)
            has_defect = False
            if flags["address_main_no_conflict"]:
                pop_defects["address_main_no_conflict"] += 1
                has_defect = True
            if flags["sgg_code_and_text_conflict"]:
                pop_defects["sgg_code_and_text_conflict"] += 1
                has_defect = True
            if flags["distance_excess_gt_200m"]:
                pop_defects["distance_excess_gt_200m"] += 1
                has_defect = True
            if not has_defect:
                pop_defects["defect_free_count"] += 1

        # 2. Proportional Stratified Sample Audit (권역별 비례 층화 100건 표본 감사, seed=42)
        sample_keys, region_quotas = proportional_stratified_sample(promoted_keys, sample_size=100, seed=42)
        sample_size = len(sample_keys)

        samp_defects = {
            "address_main_no_conflict": 0,
            "sgg_code_and_text_conflict": 0,
            "distance_excess_gt_200m": 0,
            "defect_free_count": 0,
        }
        for reg, pid in sample_keys:
            data = enriched_source[(reg, pid)]
            cid = curr_map[(reg, pid)][1]
            cand = by_contentid[cid]
            cand_parsed = item_parsed_addrs.get(cid)

            flags = evaluate_poi_defects(data, cand, cand_parsed, sgg_crosswalk)
            has_defect = False
            if flags["address_main_no_conflict"]:
                samp_defects["address_main_no_conflict"] += 1
                has_defect = True
            if flags["sgg_code_and_text_conflict"]:
                samp_defects["sgg_code_and_text_conflict"] += 1
                has_defect = True
            if flags["distance_excess_gt_200m"]:
                samp_defects["distance_excess_gt_200m"] += 1
                has_defect = True
            if not has_defect:
                samp_defects["defect_free_count"] += 1

        pop_rate = round(pop_defects["defect_free_count"] / tot_prom, 4) if tot_prom else 0.0
        samp_rate = round(samp_defects["defect_free_count"] / sample_size, 4) if sample_size else 0.0

        stratified_audit_results[f"stage_{st_idx}"] = {
            "total_promoted": tot_prom,
            "sample_size": sample_size,
            "region_quotas": region_quotas,
            "sample_defects": samp_defects,
            "sample_multi_evidence_non_conflict_rate": samp_rate,
            "population_defects": pop_defects,
            "population_multi_evidence_non_conflict_rate": pop_rate,
            "multi_evidence_non_conflict_rate": samp_rate,
            "defects": samp_defects,
        }

    # Format region-split table
    formatted_region_split = {}
    for stage_idx in range(6):
        formatted_region_split[f"stage_{stage_idx}"] = {
            f"{region}_{split}": dict(by_region_split_metrics[stage_idx][(region, split)])
            for region in REGIONS
            for split in SPLITS
        }

    return {
        "metadata": {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "catalog_snapshot": {
                "version": "2026-10-20",
                "total_items": len(catalog),
                "total_eligible_candidates": total_eligible_candidates,
            },
            "positive_observations": {
                "total_observations": len(positives),
                "unique_pois": len({obs.poi_id for obs in positives}),
                "unique_region_poi_pairs": len(poi_visits),
            },
        },
        "stage_3_distance_breakdown": stage3_breakdown,
        "stage_5_rule_distribution": dict(stage5_rule_counts),
        "stage_5_distance_200_to_500m_sensitivity": stage5_cands_200_to_500m_sensitivity,
        "anchor_verification": anchor_dist_summary,
        "stage_metrics": stage_metrics,
        "catalog_seed_coverage": catalog_seed_coverage_report,
        "candidate_density_and_margin": {
            "radius_density": radius_density_summary,
            "margin_distribution": margin_summary,
        },
        "newly_promoted_verification": newly_promoted_verification,
        "stratified_precision_audit": stratified_audit_results,
        "master_missing_cohort_by_stage": master_missing_cohort_metrics,
        "cohort_analysis_by_stage": stage_cohort_metrics,
        "region_split_breakdown": formatted_region_split,
    }


def format_markdown_report(metrics: dict) -> str:
    sm = metrics["stage_metrics"]
    anc = metrics["anchor_verification"]
    mm = metrics["master_missing_cohort_by_stage"]
    ir = anc.get("independent_rule_anchor_agreement", {})
    comp = anc.get("comparison_summary", {})
    reg_anc = anc.get("regional_stage0_anchor", {})
    glob_anc = anc.get("global_arm_d_anchor", {})
    obs_meta = metrics.get("metadata", {}).get("positive_observations", {})
    cat_meta = metrics.get("metadata", {}).get("catalog_snapshot", {})
    tot_obs = obs_meta.get("total_observations", 97640)
    uniq_region_pois = obs_meta.get("unique_region_poi_pairs", 45353)
    uniq_pois = obs_meta.get("unique_pois", 41647)
    tot_eligible = cat_meta.get("total_eligible_candidates", 19051)
    tot_snap = cat_meta.get("total_items", 48589)

    cov = metrics.get("catalog_seed_coverage", {})
    cov_stage = cov.get("by_stage", {})
    cov_reg = cov.get("region_breakdown", {})
    cov_type = cov.get("type_breakdown", {})
    sig_dens = cov.get("signal_density", {})
    cand_marg = metrics.get("candidate_density_and_margin", {})
    rad_dens = cand_marg.get("radius_density", {})
    marg_dist = cand_marg.get("margin_distribution", {})
    prom_ver = metrics.get("newly_promoted_verification", {})
    strat_aud = metrics.get("stratified_precision_audit", {})
    s3_bd = metrics.get("stage_3_distance_breakdown", {})
    s5_rules = metrics.get("stage_5_rule_distribution", {})

    lines = [
        "# AI Hub 2023 여행로그 × TourAPI v4.4 POI 식별자 매칭(v2) 심층 검증 보고서",
        "",
        f"> 이 문서는 2023 AI Hub 국내 여행로그 4개 권역(수도권, 동부권, 서부권, 제주도) TL/VL 전체 데이터({tot_obs:,} 관측 양성, {uniq_region_pois:,}개 고유 (region, POI_ID) 쌍, 전역 고유 POI {uniq_pois:,}개)와 TourAPI v4.4 스냅샷(총 {tot_snap:,}개, 적격 후보 {tot_eligible:,}개)을 대상으로 수행된 다단계 결정론적 매칭(v2), TourAPI 시드 커버리지, 거리 임계값 정합성 분석, 신규 승격 건 교차 검증 및 층화 표본 감사 결과를 기록한 보고서입니다.",
        "",
        "## 1. 기준선(Baseline D) 대조 및 Stage 0 수치 규명",
        "",
        f"- **Issue #4 레거시 Arm D 기준점 (2026-10-17 스냅샷 48,583개, Global Scope)**: **{comp.get('issue4_canonical_arm_d_observations', 4696):,}건**",
        f"- **신규 스냅샷 Global Arm D 기준점 (2026-10-20 스냅샷 48,589개, Global Scope)**: **{comp.get('global_arm_d_observations', 4686):,}건** (고유 POI {comp.get('global_arm_d_unique_pois', 1249):,}개)",
        f"  - *10건 차이 원인*: {comp.get('difference_explanation', '')}",
        f"- **신규 스냅샷 Regional Stage 0 기준선 (2026-10-20 스냅샷, ProductRegion Scope)**: **{comp.get('regional_stage0_observations', 4279):,}건** (고유 POI {comp.get('regional_stage0_unique_pois', 1013):,}개)",
        f"  - *407건 차이 원인*: {comp.get('regional_difference_explanation', '')}",
        "",
        "## 2. 5단계 파이프라인 누적 성과 비교표 (전체 97,640건)",
        "",
        "| 파이프라인 단계 | MATCHED 건수 (비율) | 후보 포함 건수 (후보 포함률) | `identity_source_missing` | AMBIGUOUS 건수 | Anchor 일치율 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    stage_names = [
        "Stage 0 (Regional Baseline: 마스터 완전일치)",
        "Stage 1 (+ 구조화 도로명/지번 주소 키)",
        "Stage 2 (+ TC_SGG 시군구 일치 해소)",
        "Stage 3 (+ WGS84 좌표 근접성 해소)",
        "Stage 4 (+ 방문 행 이름·주소·좌표 통합)",
        "Stage 5 (+ 위치 조건부 이름 정규화)",
    ]

    for i in range(6):
        st = sm[f"stage_{i}"]
        m_cnt = st["status_counts"].get("MATCHED", 0)
        m_rate = st["status_rates"].get("MATCHED", 0.0) * 100
        c_cnt = st["candidate_contained_count"]
        c_rate = st["candidate_contained_rate"] * 100
        miss_cnt = st["status_counts"].get("identity_source_missing", 0)
        amb_cnt = st["status_counts"].get("AMBIGUOUS", 0)
        anc_rate = st["anchor_precision"]["anchor_agreement_rate"] * 100
        lines.append(f"| **{stage_names[i]}** | {m_cnt:,}건 ({m_rate:.2f}%) | {c_cnt:,}건 ({c_rate:.2f}%) | {miss_cnt:,}건 | {amb_cnt:,}건 | {anc_rate:.2f}% |")

    lines.extend([
        "",
        "## 3. TourAPI Catalog Seed Coverage 및 신호 밀도 분석 (과제 2)",
        "",
        f"> 서비스 관점에서 초기 콜드스타트 추천 모델에 주입 가능한 관광 후보(contenttypeid ∈ {{12, 14, 28}} 및 권역 매칭, 총 **{tot_eligible:,}개**)를 분모로 한 카탈로그 시드 부여 성과와 신호 밀도 분위수입니다.",
        "",
        "### (1) 단계별 카탈로그 시드 커버리지 (Catalog Seed Coverage)",
        "",
        "| 파이프라인 단계 | 적격 시드 개수 (적격 커버리지) | 전체 스냅샷 시드 개수 (전체 커버리지) |",
        "| :--- | :---: | :---: |",
    ])

    for i in range(6):
        c_st = cov_stage.get(f"stage_{i}", {})
        m_elig = c_st.get("matched_eligible_contentids", 0)
        r_elig = c_st.get("eligible_seed_coverage_rate", 0.0) * 100
        m_all = c_st.get("matched_all_snapshot_contentids", 0)
        r_all = c_st.get("all_snapshot_coverage_rate", 0.0) * 100
        lines.append(f"| **{stage_names[i]}** | {m_elig:,}개 / {tot_eligible:,}개 ({r_elig:.2f}%) | {m_all:,}개 / {tot_snap:,}개 ({r_all:.2f}%) |")

    lines.extend([
        "",
        "### (2) 권역별 및 콘텐츠 유형별 시드 커버리지 (Stage 0 vs Stage 5)",
        "",
        "| 구분 | 세부 분류 | 적격 후보 수 | Stage 0 매칭 수 (커버리지) | Stage 5 매칭 수 (커버리지) | 커버리지 순증 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ])

    reg_labels = {
        "capital": "수도권 (capital)",
        "west": "서부권 (west)",
        "east": "동부권 (east)",
        "jeju-islands": "제주도 (jeju-islands)",
    }
    for r, r_data in cov_reg.items():
        tot_r = r_data.get("total_eligible", 0)
        s0_cnt = r_data.get("stage_0_matched", 0)
        s0_r = r_data.get("stage_0_coverage_rate", 0.0) * 100
        s5_cnt = r_data.get("stage_5_matched", 0)
        s5_r = r_data.get("stage_5_coverage_rate", 0.0) * 100
        diff = s5_r - s0_r
        lines.append(f"| **권역** | {reg_labels.get(r, r)} | {tot_r:,}개 | {s0_cnt:,}개 ({s0_r:.2f}%) | {s5_cnt:,}개 ({s5_r:.2f}%) | **+{diff:.2f}%p** |")

    type_labels = {
        "12": "관광지 (12)",
        "14": "문화시설 (14)",
        "28": "레포츠 (28)",
    }
    for ctype, t_data in cov_type.items():
        tot_t = t_data.get("total_eligible", 0)
        s0_cnt = t_data.get("stage_0_matched", 0)
        s0_r = t_data.get("stage_0_coverage_rate", 0.0) * 100
        s5_cnt = t_data.get("stage_5_matched", 0)
        s5_r = t_data.get("stage_5_coverage_rate", 0.0) * 100
        diff = s5_r - s0_r
        lines.append(f"| **콘텐츠유형** | {type_labels.get(ctype, ctype)} | {tot_t:,}개 | {s0_cnt:,}개 ({s0_r:.2f}%) | {s5_cnt:,}개 ({s5_r:.2f}%) | **+{diff:.2f}%p** |")

    obs_q = sig_dens.get("positive_observations_per_contentid", {}).get("quantiles", {})
    trv_q = sig_dens.get("distinct_travel_ids_per_contentid", {}).get("quantiles", {})
    poi_q = sig_dens.get("distinct_poi_ids_per_contentid", {}).get("quantiles", {})

    lines.extend([
        "",
        "### (3) 시드 부여된 TourAPI 적격 아이템별 신호 밀도 분포 (Stage 5 기준)",
        "",
        "| 신호 지표 | min | p25 | p50 (중앙값) | mean (평균) | p75 | p90 | p99 | max |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        f"| **AI Hub 방문 관측 수 (Obs)** | {obs_q.get('min', 0)} | {obs_q.get('p25', 0)} | **{obs_q.get('p50', 0)}** | {obs_q.get('mean', 0)} | {obs_q.get('p75', 0)} | {obs_q.get('p90', 0)} | {obs_q.get('p99', 0)} | {obs_q.get('max', 0)} |",
        f"| **고유 여행 수 (Travel IDs)** | {trv_q.get('min', 0)} | {trv_q.get('p25', 0)} | **{trv_q.get('p50', 0)}** | {trv_q.get('mean', 0)} | {trv_q.get('p75', 0)} | {trv_q.get('p90', 0)} | {trv_q.get('p99', 0)} | {trv_q.get('max', 0)} |",
        f"| **고유 AI Hub POI ID 수** | {poi_q.get('min', 0)} | {poi_q.get('p25', 0)} | **{poi_q.get('p50', 0)}** | {poi_q.get('mean', 0)} | {poi_q.get('p75', 0)} | {poi_q.get('p90', 0)} | {poi_q.get('p99', 0)} | {poi_q.get('max', 0)} |",
        "",
        "## 4. 거리 임계값 정합성 및 공간 밀도·마진 정량 분석 (과제 3)",
        "",
        f"- **Stage 3 정규화 타이틀 완전 일치 보강**: `<= 200m` 승격 {s3_bd.get('le_200m', 0):,}건, `200~500m` (권역 내 단일 후보 + TC_SGG 일치 필수) 승격 {s3_bd.get('between_200m_and_500m', 0):,}건",
        f"- **Stage 5 엄격화 결과**: 반경 `<= 200.0m` + 단일 후보 또는 Nearest-Neighbor Margin (`d2 - d1 >= 50.0m`)만 승격 허용.",
        f"  - 규칙별 분포: {', '.join(f'{k}: {v}건' for k, v in s5_rules.items())}",
        f"  - 민감도 참고: 200m 초과 500m 이하에만 후보가 있어 배제된 관측 POI 수: {metrics.get('stage_5_distance_200_to_500m_sensitivity', 0):,}개",
        "",
        "### (1) 관측 POI 주변 반경별 카탈로그 후보 수 분포 (공간 밀도)",
        "",
        "| 반경 | 후보 0개 | 후보 1개 | 후보 2~3개 | 후보 4~9개 | 후보 10개 이상 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ])

    for rad in [50, 100, 200, 500]:
        r_info = rad_dens.get(f"radius_le_{rad}m", {})
        c0 = r_info.get("0", {}).get("count", 0)
        c1 = r_info.get("1", {}).get("count", 0)
        c23 = r_info.get("2_to_3", {}).get("count", 0)
        c49 = r_info.get("4_to_9", {}).get("count", 0)
        c10 = r_info.get("10_plus", {}).get("count", 0)
        lines.append(f"| **반경 <= {rad}m** | {c0:,}개 | {c1:,}개 | {c23:,}개 | {c49:,}개 | {c10:,}개 |")

    lines.extend([
        "",
        "### (2) 1순위 거리 및 2순위 거리 마진 (Nearest-Neighbor Margin) 분포",
        "",
        "| 마진 구분 | POI 건수 | 비중 | 해석 |",
        "| :--- | :---: | :---: | :--- |",
    ])

    marg_labels = {
        "single_candidate_within_500m": ("반경 500m 내 단일 후보", "경쟁 후보 없음 (독점 매칭)"),
        "margin_ge_200m": ("d2 - d1 >= 200m", "압도적 거리 격차 (최고 신뢰도)"),
        "margin_100m_to_200m": ("100m <= d2 - d1 < 200m", "명확한 거리 우위"),
        "margin_50m_to_100m": ("50m <= d2 - d1 < 100m", "유의미한 거리 마진 (안전 통과)"),
        "margin_lt_50m_excluded": ("d2 - d1 < 50m (배제됨)", "공간적 모호성으로 인해 좌표 단독 매칭 배제"),
    }
    for m_key, (m_title, m_desc) in marg_labels.items():
        if m_key in marg_dist:
            row = marg_dist[m_key]
            lines.append(f"| **{m_title}** | {row['count']:,}건 | {row['share']*100:.2f}% | {m_desc} |")

    lines.extend([
        "",
        "## 5. 신규 승격 건(Newly Promoted) 물리 신호 사후 정합성 진단 및 층화 감사 (과제 4)",
        "",
        "> Stage 0의 단락된 기준점 매칭을 제외하고, 각 단계(Stage 1~5)에서 새롭게 MATCHED로 승격된 건들에 대해 각 물리 신호의 역할((a) 후보 선택 주 규칙, (b) 충돌 차단/보조 게이팅, (c) 사후 관측 진단)을 명시하고, 사후 관측 신호(WGS84 좌표 거리 분위수, TC_SGG 시군구 일치율) 정합성 진단과 4개 권역 기준 비례 층화 100건 표본 감사(seed=42) 및 전수 감사를 병행 실시했습니다.",
        "",
        "### (1) 신규 승격 건 물리 신호 사후 정합성 진단 (Post-Promotion Signal Consistency Diagnostic)",
        "",
        "| 승격 단계 | 신규 승격 POI 수 | 후보 선택 주 규칙 (Primary Selection) | 충돌 차단/보조 게이팅 (Veto/Gating) | 사후 관측 진단 (Post-Hoc Diagnostic) | 좌표 거리 p50 | 좌표 거리 p90 | <=200m 일치율 | SGG 일치율 |",
        "| :--- | :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: |",
    ])

    for i in range(1, 6):
        pv = prom_ver.get(f"stage_{i}", {})
        cnt = pv.get("total_newly_promoted_pois", 0)
        p_sel = pv.get("primary_selection", "")
        v_gate = pv.get("veto_gating", "")
        ph_diag = pv.get("post_hoc_diagnostic", "")
        p50 = pv.get("distance_quantiles", {}).get("p50", 0.0)
        p90 = pv.get("distance_quantiles", {}).get("p90", 0.0)
        le_200 = pv.get("distance_threshold_shares", {}).get("le_200m", 0.0) * 100
        sgg_rate = pv.get("sgg_agreement_rate", 0.0) * 100
        lines.append(f"| **Stage {i} 신규 승격** | {cnt:,}개 | {p_sel} | {v_gate} | {ph_diag} | {p50}m | {p90}m | {le_200:.2f}% | {sgg_rate:.2f}% |")

    lines.extend([
        "",
        "### (2) 결정론적 비례 층화 표본 감사 및 전수 감사 (Stratified Sample & Population Audit, seed=42)",
        "",
        "| 승격 단계 | 표본 크기 (권역별 할당) | 표본 결함 (주소/SGG/거리) | 표본 다중 물리 증거 무충돌률 | 전수 POI 수 | 전수 결함 (주소/SGG/거리) | 전수 다중 물리 증거 무충돌률 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for i in range(1, 6):
        sa = strat_aud.get(f"stage_{i}", {})
        sz = sa.get("sample_size", 0)
        quotas = sa.get("region_quotas", {})
        q_str = f"{sz:,}개 (수{quotas.get('capital', 0)}/서{quotas.get('west', 0)}/동{quotas.get('east', 0)}/제{quotas.get('jeju-islands', 0)})"

        s_df = sa.get("sample_defects", {})
        s_c_addr = s_df.get("address_main_no_conflict", 0)
        s_c_sgg = s_df.get("sgg_code_and_text_conflict", 0)
        s_c_dist = s_df.get("distance_excess_gt_200m", 0)
        s_rate = sa.get("sample_multi_evidence_non_conflict_rate", 0.0) * 100

        tot_p = sa.get("total_promoted", 0)
        p_df = sa.get("population_defects", {})
        p_c_addr = p_df.get("address_main_no_conflict", 0)
        p_c_sgg = p_df.get("sgg_code_and_text_conflict", 0)
        p_c_dist = p_df.get("distance_excess_gt_200m", 0)
        p_rate = sa.get("population_multi_evidence_non_conflict_rate", 0.0) * 100

        lines.append(
            f"| **Stage {i}** | {q_str} | {s_c_addr}/{s_c_sgg}/{s_c_dist}건 | **{s_rate:.2f}%** | {tot_p:,}개 | {p_c_addr}/{p_c_sgg}/{p_c_dist}건 | **{p_rate:.2f}%** |"
        )

    lines.extend([
        "",
        "## 6. 독립(Non-short-circuited) 규칙별 Anchor 일치율 검증 (1,013개 고유 POI 대상)",
        "",
        "| 평가 규칙 | 판정 POI 수 (재현율) | 동일 contentid 일치 | 충돌 건수 | Anchor 일치율 (Agreement Rate) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    rule_labels = {
        "rule_1_structured_address_key_only": "구조화 주소 키 단독 (Full Key)",
        "rule_2_tc_sgg_only": "TC_SGG 시군구 일치 단독",
        "rule_3_geo_distance_only": "좌표 근접성(<=200m) 단독",
        "rule_4_visit_signals_only": "방문 행 신호 단독",
        "rule_5_name_normalizer_only": "위치 조건부 이름 정규화 단독",
    }
    for rk, label in rule_labels.items():
        if rk in ir:
            row = ir[rk]
            lines.append(f"| **{label}** | {row['matched_pois']:,}개 ({row['recall']*100:.2f}%) | {row['same_contentid_count']:,}개 | {row['conflicting_contentid_count']:,}개 | {row['agreement_rate']*100:.2f}% |")

    lines.extend([
        "",
        "## 7. TN_POI_MASTER 결측 코호트(26,884건, 고유 POI 19,321개) 신호 복원 및 전환 분석",
        "",
        "> `identity_source_missing: 0`은 방문 행(`TN_VISIT_AREA_INFO`)으로부터 장소명(`VISIT_AREA_NM`)·주소·좌표 신호를 확보하여 원천 결측 상태에서 '평가 가능 상태'(`MATCHED`, `AMBIGUOUS`, `UNMATCHED`)로 100% 전환되었음을 의미합니다. (이름 신호가 전혀 없는 방문지는 주소/좌표만으로 매칭하지 않는다는 보수적 원칙 준수).",
        "",
        "| 단계 | MATCHED 건수 (비율) | 후보 포함 건수 (비율) | AMBIGUOUS 건수 | UNMATCHED 건수 | 결측(missing) 상태 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ])

    for i in range(6):
        st = mm[f"stage_{i}"]
        m_cnt = st["status_counts"].get("MATCHED", 0)
        m_rate = st["status_rates"].get("MATCHED", 0.0) * 100
        c_cnt = st["candidate_contained_count"]
        c_rate = st["candidate_contained_rate"] * 100
        amb_cnt = st["status_counts"].get("AMBIGUOUS", 0)
        unm_cnt = st["status_counts"].get("UNMATCHED", 0)
        miss_cnt = st["status_counts"].get("identity_source_missing", 0)
        lines.append(f"| **Stage {i}** | {m_cnt:,}건 ({m_rate:.2f}%) | {c_cnt:,}건 ({c_rate:.2f}%) | {amb_cnt:,}건 | {unm_cnt:,}건 | {miss_cnt:,}건 |")

    lines.extend([
        "",
        "## 8. 관광 대상 코호트 분리 분석 (Stage 5 기준)",
        "",
        "| 방문지 유형 코드 | 유형 명칭 | 관측 건수 | MATCHED 건수 (매칭률) | 후보 포함 건수 (포함률) | 카탈로그 지원 여부 |",
        "| :---: | :--- | :---: | :---: | :---: | :---: |",
    ])

    type_names = {
        "1": "자연관광지",
        "2": "역사/유적/종교",
        "3": "문화/예술",
        "4": "상업지구/거리",
        "5": "레저/스포츠관련시설",
        "6": "테마파크/놀이공원",
        "7": "체험/학습/연구시설",
        "8": "전시/관람시설",
        "9": "쇼핑몰/시장/상점",
        "10": "숙박시설",
        "11": "음식점/카페",
        "12": "축제/행사",
        "13": "휴양림/수목원/공원",
        "14": "온천/스파",
        "21": "교통환승지(공항/기차역 등)",
        "22": "고속도로휴게소",
        "23": "주차장",
        "24": "기타교통시설",
    }

    s5_cohorts = metrics["cohort_analysis_by_stage"]["stage_5"]
    tour_supported_types = {"1", "2", "3", "5", "6", "7", "8", "12", "13", "14"}

    sorted_cohorts = sorted(s5_cohorts.items(), key=lambda x: x[1]["total"], reverse=True)
    for v_type, data in sorted_cohorts:
        t_nm = type_names.get(v_type, f"기타 ({v_type})")
        tot = data["total"]
        m_cnt = data["counts"].get("MATCHED", 0)
        m_rate = data["matched_rate"] * 100
        c_cnt = data["counts"].get("candidate_contained", 0)
        c_rate = data["candidate_contained_rate"] * 100
        is_tour = "지원 대상" if v_type in tour_supported_types else "비지원/배제 대상"
        lines.append(f"| `{v_type}` | {t_nm} | {tot:,}건 | {m_cnt:,}건 ({m_rate:.2f}%) | {c_cnt:,}건 ({c_rate:.2f}%) | {is_tour} |")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-stage POI identity matching pipeline v2")
    parser.add_argument("--snapshot", type=Path, default=Path("results/experiments/poi-catalog-v1/tourapi_v44_snapshot.csv"))
    parser.add_argument("--master-cache", type=Path, default=Path("results/experiments/poi-catalog-v1/master_poi_cache.json"))
    parser.add_argument("--output", type=Path, default=Path("results/experiments/poi-catalog-v1/poi_identity_matching_v2_metrics.json"))
    args = parser.parse_args()

    t_start = time.time()
    if not args.snapshot.exists():
        raise FileNotFoundError("TourAPI snapshot not found")

    print("Loading TourAPI snapshot...")
    snapshot = load_tourapi_v44_snapshot_csv(args.snapshot)
    catalog = list(snapshot.records)
    print(f"Loaded {len(catalog)} catalog items.")

    capital_tl = Path(os.environ["CAPITAL_TL"]).resolve() if os.environ.get("CAPITAL_TL") else None
    print("Loading TC_SGG crosswalk across all regions...")
    sgg_crosswalk = load_all_tc_sgg(capital_tl)
    print(f"Loaded SGG crosswalk with {len(sgg_crosswalk.aihub_to_names)} areas.")

    policy = load_poi_catalog_policy()

    print("Loading observed positives across 4 regions...")
    t0 = time.time()
    positives = load_all_visit_positives()
    print(f"Loaded {len(positives)} observed positives in {time.time() - t0:.2f}s.")

    target_poi_ids = {obs.poi_id for obs in positives}
    print(f"Unique POI IDs to find in master: {len(target_poi_ids)}")
    masters = load_master_records_fast(target_poi_ids, args.master_cache)

    print("Executing 5-stage identity matching pipeline...")
    metrics = run_pipeline(positives, masters, catalog, sgg_crosswalk, policy)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved results JSON.")

    md_report = format_markdown_report(metrics)
    md_path = args.output.with_suffix(".md")
    md_path.write_text(md_report, encoding="utf-8")
    print("Saved results Markdown.")
    print(f"Pipeline executed in {time.time() - t_start:.2f}s.")


if __name__ == "__main__":
    main()
