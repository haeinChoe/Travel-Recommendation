"""Collect and persist one Git-ignored, read-only TourAPI KorService2 v4.4 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.poi_catalog_candidate_contract import normalize_code
from scripts.recommendation.poi_catalog_policy import load_poi_catalog_policy, validate_live_region_codes
from scripts.recommendation.tourapi_snapshot_adapter import (
    TourApiCollectionError,
    TourApiFieldMap,
    adapt_tourapi_snapshot,
    collect_tourapi_snapshot,
    fetch_current_legal_region_codes,
    write_snapshot_csv,
)


V44_CONTENT_TYPE_IDS = ("12", "14", "15", "25", "28", "32", "38", "39")


def _snapshot_content_hash(rows: list[dict[str, str]]) -> str:
    canonical = sorted([
        {key: row.get(key, "") for key in (
            "contentid", "contenttypeid", "title", "addr1", "lDongRegnCd",
            "lDongSignguCd", "lclsSystm1", "lclsSystm2", "lclsSystm3", "modifiedtime",
        )}
        for row in rows
    ], key=lambda row: row["contentid"])
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def collect_and_write(output: Path, *, page_size: int = 1000) -> dict[str, object]:
    if not output.parts or output.parts[0] != "results":
        raise ValueError("snapshot output must be under the Git-ignored results/ directory")
    policy = load_poi_catalog_policy()
    supported_types = policy.supported_content_type_ids
    policy_version = policy.version
    if not supported_types or not supported_types.issubset(V44_CONTENT_TYPE_IDS):
        raise ValueError("versioned POI catalog policy has unsupported content types")
    regions = fetch_current_legal_region_codes()
    try:
        validate_live_region_codes(regions, policy)
    except ValueError as error:
        raise TourApiCollectionError(str(error)) from None
    rows, request_config = collect_tourapi_snapshot(
        region_codes=regions,
        content_type_ids=V44_CONTENT_TYPE_IDS,
        page_size=page_size,
    )
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    content_hash = _snapshot_content_hash(rows)
    snapshot_version = (
        f"tourapi-korservice2-v4.4-{retrieved_at.replace(':', '').replace('-', '')}-"
        f"{content_hash[:8]}"
    )
    snapshot = adapt_tourapi_snapshot(
        rows,
        snapshot_version=snapshot_version,
        fields=TourApiFieldMap(),
        retrieved_at=retrieved_at,
        request_config_hash=str(request_config["request_config_hash"]),
        policy_version=policy_version,
    )
    write_snapshot_csv(output, rows)
    metadata = {
        "provider": "tourapi-korservice2",
        "manual_version": "4.4",
        "snapshot_version": snapshot.snapshot_version,
        "retrieved_at_utc": retrieved_at,
        "request_config": request_config,
        "policy_version": policy_version,
        "policy_config_sha256": policy.policy_sha256,
        "snapshot_sha256": content_hash,
        "catalog_item_count": len(snapshot.records),
        "content_type_counts": dict(sorted(Counter(
            normalize_code(item.content_type_id) for item in snapshot.records
        ).items())),
        "supported_content_type_ids_v1": sorted(supported_types),
        "status_policy": "snapshot_membership_and_field_validity_only",
    }
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Git-ignored results/ path")
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()
    try:
        result = collect_and_write(args.output, page_size=args.page_size)
    except (TourApiCollectionError, ValueError) as error:
        # Exception text is constructed to exclude API keys, URLs, and response data.
        parser.exit(2, f"TourAPI snapshot failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
