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


def valid_unique_trip_owner_rows(
    trip_rows: Iterable[Mapping[str, object]],
    traveler_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Match the canonical cohort: unique trips owned by unique traveler-master rows."""
    traveler_counts = Counter(
        traveler_id
        for row in traveler_rows
        if (traveler_id := _clean(row.get(TRAVELER_KEY)))
    )
    unique_travelers = {
        traveler_id for traveler_id, count in traveler_counts.items() if count == 1
    }
    rows_by_trip: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in trip_rows:
        trip_id = _clean(row.get(TRIP_KEY))
        if trip_id:
            rows_by_trip[trip_id].append(row)

    result = []
    for trip_id, rows in rows_by_trip.items():
        if len(rows) != 1:
            continue
        traveler_id = _clean(rows[0].get(TRAVELER_KEY))
        if traveler_id in unique_travelers:
            result.append({TRIP_KEY: trip_id, TRAVELER_KEY: traveler_id})
    return result


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

    Raw IDs are accepted and returned only for in-memory joins. Call once per region;
    the canonical identity grain includes region. Keep IDs out of artifacts and logs.
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


def deterministic_trip_level_split(
    trip_ids: Iterable[str],
    *,
    seed: str | int,
    validation_fraction: float = 0.2,
) -> dict[str, str]:
    """Assign individual trips deterministically for an aggregate comparison baseline."""
    if isinstance(validation_fraction, bool) or not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    trips = {_clean(trip_id) for trip_id in trip_ids}
    trips.discard(None)
    if len(trips) < 2:
        raise ValueError("At least two trips are required for a non-empty trip split")

    seed_text = str(seed)
    ranked = sorted(
        trips,
        key=lambda trip: (
            hashlib.sha256(f"{seed_text}\0{trip}".encode("utf-8")).hexdigest(),
            trip,
        ),
    )
    validation_count = max(1, min(len(ranked) - 1, round(len(ranked) * validation_fraction)))
    validation_trips = set(ranked[:validation_count])
    return {
        trip: "inner-validation" if trip in validation_trips else "inner-train"
        for trip in trips
    }


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
    source_split = _clean(row.get("source_split")) or _clean(row.get("split"))
    if source_split not in {"TL", "train"}:
        raise ValueError("Inner train-derived features require outer TL interactions/events")


def recompute_inner_train_positive_interaction_count(
    interactions: Iterable[Mapping[str, object]],
    partition_by_trip: Mapping[str, str],
    *,
    all_item_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Recompute I3 from one region's unique inner-train positive trip-item interactions."""
    pairs: set[tuple[str, str]] = set()
    item_ids = {_clean(item_id) for item_id in all_item_ids}
    item_ids.discard(None)
    for row in interactions:
        _require_tl_source(row)
        trip_id = _clean(row.get("trip_id", row.get("TRAVEL_ID")))
        item_id = _clean(row.get("item_id", row.get("POI_ID")))
        if not trip_id or not item_id:
            raise ValueError("Inner-train interaction is missing a trip or item key")
        if "observed_positive" not in row:
            raise ValueError("Inner-train interaction must declare observed_positive")
        if _clean(row.get("observed_positive")) != "1":
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

    Pass one region at a time because TRAVEL_ID is region-scoped. A trip-item is eligible
    when it has at least one tourism-core visit event. For that pair, all valid event
    visit-type codes are collected. The function never reads canonical item_features values.
    """
    if visit_events is None:
        raise I4SourceUnavailableError(
            "I4 requires inner-train visit events with trip, item, and visit-type fields"
        )

    codes_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    core_pairs: set[tuple[str, str]] = set()
    item_ids = {_clean(item_id) for item_id in all_item_ids}
    item_ids.discard(None)
    event_count = 0
    for row in visit_events:
        event_count += 1
        has_trip = "trip_id" in row or "TRAVEL_ID" in row
        has_item = "item_id" in row or "POI_ID" in row
        has_type = "visit_type" in row or "VISIT_AREA_TYPE_CD" in row
        has_split = "source_split" in row or "split" in row
        if not (has_trip and has_item and has_type and has_split):
            raise I4SourceUnavailableError(
                "I4 event source must expose trip, item, visit-type, and TL split fields"
            )
        _require_tl_source(row)
        trip_id = _clean(row.get("trip_id")) or _clean(row.get("TRAVEL_ID"))
        item_id = _clean(row.get("item_id")) or _clean(row.get("POI_ID"))
        if not trip_id or not item_id or partition_by_trip.get(trip_id) != "inner-train":
            continue
        visit_type = validate_code_domain(
            "VISIT_AREA_TYPE_CD",
            _clean(row.get("visit_type")) or _clean(row.get("VISIT_AREA_TYPE_CD")),
        )
        if visit_type is None:
            continue
        key = (trip_id, item_id)
        codes_by_pair[key].add(visit_type)
        if visit_type in TOURISM_CORE_TYPES:
            core_pairs.add(key)
        item_ids.add(item_id)

    if event_count == 0:
        raise I4SourceUnavailableError(
            "I4 event source must provide rows so its required fields can be verified"
        )
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
    """Build aggregate-only regional stats and region-scoped traveler group splits."""
    if set(region_rows) != set(REGION_ENV_PREFIX):
        raise ValueError("Exactly four TL region inputs are required")

    regions: dict[str, object] = {}
    for region in REGION_ENV_PREFIX:
        aggregate, owners = traveler_trip_distribution(region_rows[region])
        partitions = deterministic_traveler_group_split(
            owners, seed=seed, validation_fraction=validation_fraction
        )
        overlap = validate_no_traveler_overlap(owners, partitions)
        trip_partitions = deterministic_trip_level_split(
            owners, seed=seed, validation_fraction=validation_fraction
        )
        trip_split_travelers: dict[str, set[str]] = defaultdict(set)
        for trip_id, traveler_id in owners.items():
            trip_split_travelers[traveler_id].add(trip_partitions[trip_id])
        trip_split_overlap = sum(
            len(traveler_partitions) > 1
            for traveler_partitions in trip_split_travelers.values()
        )
        changed_trip_count = sum(
            partitions[trip_id] != trip_partitions[trip_id] for trip_id in owners
        )
        traveler_partition: dict[str, str] = {}
        for trip_id, traveler_id in owners.items():
            partition = partitions[trip_id]
            previous = traveler_partition.setdefault(traveler_id, partition)
            if previous != partition:
                raise ValueError("Traveler overlap detected across inner partitions")
        regions[region] = {
            **aggregate,
            "inner_split": {
                "train_travelers": sum(
                    partition == "inner-train" for partition in traveler_partition.values()
                ),
                "validation_travelers": sum(
                    partition == "inner-validation"
                    for partition in traveler_partition.values()
                ),
                "train_trips": sum(
                    partition == "inner-train" for partition in partitions.values()
                ),
                "validation_trips": sum(
                    partition == "inner-validation" for partition in partitions.values()
                ),
                "traveler_overlap": overlap,
            },
            "trip_split_comparison": {
                "changed_trip_assignments": changed_trip_count,
                "changed_trip_assignment_share": round(
                    changed_trip_count / len(owners), 6
                ),
                "traveler_overlap": trip_split_overlap,
                "traveler_overlap_share": round(
                    trip_split_overlap / len(trip_split_travelers), 6
                ),
            },
        }
    return {
        "audit_version": 1,
        "split": {
            "unit": "(region, TRAVELER_ID)",
            "group_scope": "within each TL region",
            "seed": seed,
            "validation_fraction": validation_fraction,
            "partition_names": ["inner-train", "inner-validation"],
            "traveler_overlap": 0,
        },
        "regions": regions,
        "privacy": {
            "raw_identifiers_written": False,
            "raw_paths_written": False,
            "output_scope": "aggregate counts only",
        },
    }


def _find_table_csv(folder: Path, table_name: str) -> Path:
    token = table_name.casefold()
    matches = [
        path for path in folder.glob("*.csv")
        if token in path.name.casefold() and not path.is_symlink()
    ]
    if table_name == "TN_TRAVEL":
        matches = [path for path in matches if "traveller" not in path.name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Each TL binding must contain exactly one {table_name} CSV")
    return matches[0]


def _read_csv_rows(path: Path, required_columns: frozenset[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(not name.strip() for name in reader.fieldnames):
            raise ValueError("Malformed TL source table header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Duplicate TL source table column")
        if not required_columns <= set(reader.fieldnames):
            raise ValueError("Required columns are missing from a TL source table")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed TL source table row")
            rows.append({str(key).strip(): value for key, value in row.items() if key is not None})
        return rows


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
            trip_rows = _read_csv_rows(
                _find_table_csv(Path(value), "TN_TRAVEL"),
                frozenset({TRIP_KEY, TRAVELER_KEY}),
            )
            traveler_rows = _read_csv_rows(
                _find_table_csv(Path(value), "TN_TRAVELLER_MASTER"),
                frozenset({TRAVELER_KEY}),
            )
            region_rows[region] = valid_unique_trip_owner_rows(trip_rows, traveler_rows)
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
