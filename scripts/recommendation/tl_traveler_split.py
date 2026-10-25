"""Privacy-safe TL traveler/trip audit and cold-user inner-split primitives (Issue #80)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.training_data_contract import (
    TOURISM_CORE_VISIT_AREA_TYPES,
    validate_code_domain,
)

REGION_ENV_PREFIX = {
    "capital": "CAPITAL",
    "west": "WEST",
    "east": "EAST",
    "jeju-islands": "JEJU",
}
TRIP_COLUMNS = frozenset({"TRAVEL_ID", "TRAVELER_ID"})
TRIP_KEY = "TRAVEL_ID"
TRAVELER_KEY = "TRAVELER_ID"
TOURISM_CORE_TYPES = TOURISM_CORE_VISIT_AREA_TYPES


class I4SourceUnavailableError(ValueError):
    """Raised when visit-event provenance is absent for Historical POI recomputation."""


def _clean(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def traveler_trip_distribution(
    trip_rows: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, str]]:
    """Return aggregate-only TL traveler/trip statistics and an in-memory trip-owner map.

    The returned owner map contains raw IDs for same-process splitting only. Callers must
    never serialize, log, or print it.
    """
    trip_owner: dict[str, str] = {}
    for row in trip_rows:
        trip_id = _clean(row.get(TRIP_KEY))
        traveler_id = _clean(row.get(TRAVELER_KEY))
        if not trip_id or not traveler_id:
            continue
        previous_owner = trip_owner.get(trip_id)
        if previous_owner is not None and previous_owner != traveler_id:
            raise ValueError("A trip has conflicting traveler ownership")
        trip_owner[trip_id] = traveler_id

    if not trip_owner:
        raise ValueError("No valid traveler-trip rows are available")

    trips_per_traveler = Counter(trip_owner.values())
    trip_counts = list(trips_per_traveler.values())
    one_trip = sum(count == 1 for count in trip_counts)
    two_trips = sum(count == 2 for count in trip_counts)
    three_plus = sum(count >= 3 for count in trip_counts)
    traveler_count = len(trips_per_traveler)

    aggregate = {
        "distinct_travelers": traveler_count,
        "distinct_trips": len(trip_owner),
        "traveler_trip_count": {
            "one_trip_travelers": one_trip,
            "two_trip_travelers": two_trips,
            "three_or_more_trip_travelers": three_plus,
        },
        "mean_trips_per_traveler": round(mean(trip_counts), 6),
        "median_trips_per_traveler": float(median(trip_counts)),
        "max_trips_per_traveler": max(trip_counts),
        "multi_trip_traveler_share": round(
            (two_trips + three_plus) / traveler_count, 6
        ),
    }
    if one_trip + two_trips + three_plus != traveler_count:
        raise ValueError("Traveler-trip distribution does not reconcile")
    return aggregate, trip_owner


def deterministic_traveler_group_split(
    trip_owner: Mapping[str, str],
    *,
    seed: str | int,
    validation_fraction: float = 0.2,
) -> dict[str, str]:
    """Assign all trips for each traveler to one deterministic inner partition.

    Raw IDs are accepted and returned only for in-memory joins. The caller is responsible
    for keeping them out of artifacts and logs.
    """
    if isinstance(validation_fraction, bool) or not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    owners = {trip: traveler for trip, traveler in trip_owner.items() if trip and traveler}
    if not owners or len(owners) != len(trip_owner):
        raise ValueError("Trip ownership must contain only valid trip and traveler IDs")
    travelers = set(owners.values())
    if len(travelers) < 2:
        raise ValueError("At least two travelers are required for a non-empty group split")

    seed_text = str(seed)
    ranked = sorted(
        travelers,
        key=lambda traveler: (
            hashlib.sha256(f"{seed_text}\0{traveler}".encode("utf-8")).hexdigest(),
            traveler,
        ),
    )
    validation_count = max(1, min(len(ranked) - 1, round(len(ranked) * validation_fraction)))
    validation_travelers = set(ranked[:validation_count])
    partitions = {
        trip: "inner-validation" if traveler in validation_travelers else "inner-train"
        for trip, traveler in owners.items()
    }
    validate_no_traveler_overlap(owners, partitions)
    return partitions


def validate_no_traveler_overlap(
    trip_owner: Mapping[str, str], partition_by_trip: Mapping[str, str]
) -> int:
    """Raise on any traveler appearing in both partitions; return the safe overlap count."""
    if set(partition_by_trip) != set(trip_owner):
        raise ValueError("Every valid trip must have exactly one inner partition")
    by_traveler: dict[str, set[str]] = defaultdict(set)
    for trip, traveler in trip_owner.items():
        partition = partition_by_trip.get(trip)
        if partition not in {"inner-train", "inner-validation"}:
            raise ValueError("Every valid trip must have exactly one inner partition")
        by_traveler[traveler].add(partition)
    overlap_count = sum(len(partitions) > 1 for partitions in by_traveler.values())
    if overlap_count:
        raise ValueError("Traveler overlap detected across inner partitions")
    return overlap_count


def _require_tl_source(row: Mapping[str, object]) -> None:
    source_split = _clean(row.get("source_split", row.get("split")))
    if source_split not in {"TL", "train"}:
        raise ValueError("Inner train-derived features require outer TL interactions/events")


def recompute_inner_train_positive_interaction_count(
    interactions: Iterable[Mapping[str, object]],
    partition_by_trip: Mapping[str, str],
    *,
    all_item_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Recompute I3 from unique inner-train positive trip-item interactions only."""
    pairs: set[tuple[str, str]] = set()
    item_ids = {_clean(item_id) for item_id in all_item_ids}
    item_ids.discard(None)
    for row in interactions:
        _require_tl_source(row)
        trip_id = _clean(row.get("trip_id", row.get("TRAVEL_ID")))
        item_id = _clean(row.get("item_id", row.get("POI_ID")))
        if not trip_id or not item_id:
            continue
        if _clean(row.get("observed_positive", 1)) != "1":
            raise ValueError("Only observed-positive interactions are supported")
        partition = partition_by_trip.get(trip_id)
        if partition not in {"inner-train", "inner-validation"}:
            raise ValueError("Every interaction trip must have an inner partition")
        if partition == "inner-train":
            pairs.add((trip_id, item_id))
            item_ids.add(item_id)
    counts = Counter(item_id for _, item_id in pairs)
    return {item_id: counts[item_id] for item_id in sorted(item_ids)}


def recompute_inner_train_visit_type_codes(
    visit_events: Iterable[Mapping[str, object]] | None,
    partition_by_trip: Mapping[str, str],
    *,
    all_item_ids: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Recompute I4 from inner-train TN_VISIT_AREA_INFO events; fail closed if unavailable.

    A trip-item is eligible when it has at least one tourism-core visit event. For that
    eligible pair, all valid event visit-type codes are collected, matching the canonical
    item-feature rule. The function never reads canonical item_features values.
    """
    if visit_events is None:
        raise I4SourceUnavailableError(
            "I4 requires inner-train visit events with trip, item, and visit-type fields"
        )

    codes_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    core_pairs: set[tuple[str, str]] = set()
    item_ids = {_clean(item_id) for item_id in all_item_ids}
    item_ids.discard(None)
    for row in visit_events:
        _require_tl_source(row)
        trip_id = _clean(row.get("trip_id", row.get("TRAVEL_ID")))
        item_id = _clean(row.get("item_id", row.get("POI_ID")))
        if not trip_id or not item_id or partition_by_trip.get(trip_id) != "inner-train":
            continue
        visit_type = validate_code_domain(
            "VISIT_AREA_TYPE_CD",
            row.get("visit_type", row.get("VISIT_AREA_TYPE_CD")),
        )
        if visit_type is None:
            continue
        key = (trip_id, item_id)
        codes_by_pair[key].add(visit_type)
        if visit_type in TOURISM_CORE_TYPES:
            core_pairs.add(key)
        item_ids.add(item_id)

    result: dict[str, set[str]] = defaultdict(set)
    for trip_id, item_id in core_pairs:
        result[item_id].update(codes_by_pair[(trip_id, item_id)])
    return {
        item_id: sorted(result.get(item_id, set()), key=lambda code: (int(code), code))
        for item_id in sorted(item_ids)
    }


def audit_payload(
    region_rows: Mapping[str, Iterable[Mapping[str, object]]],
    *,
    seed: str,
    validation_fraction: float,
) -> dict[str, object]:
    """Build a serializable audit containing only aggregate counts and safe metadata."""
    regions: dict[str, object] = {}
    for region in REGION_ENV_PREFIX:
        if region not in region_rows:
            raise ValueError("Exactly four TL region inputs are required")
        aggregate, owners = traveler_trip_distribution(region_rows[region])
        partitions = deterministic_traveler_group_split(
            owners, seed=seed, validation_fraction=validation_fraction
        )
        validate_no_traveler_overlap(owners, partitions)
        traveler_partition: dict[str, str] = {}
        for trip, traveler in owners.items():
            partition = partitions[trip]
            previous = traveler_partition.setdefault(traveler, partition)
            if previous != partition:
                raise ValueError("Traveler overlap detected across inner partitions")
        train_trips = sum(partition == "inner-train" for partition in partitions.values())
        validation_trips = sum(partition == "inner-validation" for partition in partitions.values())
        regions[region] = {
            **aggregate,
            "inner_split": {
                "train_travelers": sum(
                    partition == "inner-train" for partition in traveler_partition.values()
                ),
                "validation_travelers": sum(
                    partition == "inner-validation" for partition in traveler_partition.values()
                ),
                "train_trips": train_trips,
                "validation_trips": validation_trips,
                "traveler_overlap": 0,
            },
        }
    return {
        "audit_version": 1,
        "split": {
            "unit": "TRAVELER_ID",
            "seed": seed,
            "validation_fraction": validation_fraction,
            "partition_names": ["inner-train", "inner-validation"],
        },
        "regions": regions,
        "privacy": {
            "raw_identifiers_written": False,
            "raw_paths_written": False,
            "output_scope": "aggregate counts only",
        },
    }


def _find_travel_csv(folder: Path) -> Path:
    matches = [
        path for path in folder.glob("*.csv")
        if "tn_travel" in path.name.casefold()
        and "traveller" not in path.name.casefold()
        and not path.is_symlink()
    ]
    if len(matches) != 1:
        raise ValueError("Each TL binding must contain exactly one TN_TRAVEL CSV")
    return matches[0]


def _read_trip_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not TRIP_COLUMNS <= set(reader.fieldnames):
            raise ValueError("TN_TRAVEL must include TRAVEL_ID and TRAVELER_ID")
        return list(reader)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self._print_message(
            "Invalid command-line arguments; details are suppressed.\n", sys.stderr
        )
        raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeArgumentParser(
        description="Aggregate TL traveler-trip distribution without emitting raw identifiers"
    )
    parser.add_argument("--seed", default="issue80-v1")
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    args = parser.parse_args(argv)
    try:
        if not 0 < args.validation_fraction < 1:
            raise ValueError("Invalid validation fraction")
        region_rows = {}
        for region, prefix in REGION_ENV_PREFIX.items():
            value = os.environ.get(f"{prefix}_TL")
            if not value:
                raise ValueError("Missing TL input binding")
            region_rows[region] = _read_trip_rows(_find_travel_csv(Path(value)))
        result = audit_payload(
            region_rows,
            seed=args.seed,
            validation_fraction=args.validation_fraction,
        )
    except Exception:
        print(
            "TL traveler-trip audit failed; diagnostic details are suppressed for privacy.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
