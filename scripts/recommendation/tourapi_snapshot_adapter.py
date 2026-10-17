"""Explicit-field adapter for an already authorized TourAPI item snapshot.

The official endpoint field semantics and bulk-retention terms remain under
review. Callers must therefore supply a verified field map and an explicit
status-value map; this module performs no network requests and guesses no
TourAPI field names.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from scripts.recommendation.poi_catalog_candidate_contract import (
    CatalogPoi,
    CatalogSnapshot,
    SourcePoi,
    normalize_code,
)


@dataclass(frozen=True)
class TourApiFieldMap:
    content_id: str
    content_type_id: str
    title: str
    region_codes: tuple[str, ...]
    district_codes: tuple[str, ...]
    address: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class SourceObservationFieldMap:
    request_id: str
    source_item_id: str
    region: str | None = None
    name: str | None = None
    district_code: str | None = None
    address: str | None = None
    category: str | None = None


def _required_text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("snapshot row has a missing or non-string required field")
    return value


def adapt_tourapi_snapshot(
    rows: Iterable[Mapping[str, object]],
    *,
    snapshot_version: str,
    fields: TourApiFieldMap,
    status_values: Mapping[str, str] | None = None,
) -> CatalogSnapshot:
    """Map verified provider rows while preserving IDs and unknown statuses."""
    if not snapshot_version.strip():
        raise ValueError("snapshot version is required")
    if not fields.region_codes or not all(field.strip() for field in fields.region_codes):
        raise ValueError("at least one reviewed region-code field is required")
    status_map: dict[str, str] = {}
    for key, value in (status_values or {}).items():
        normalized_key = normalize_code(key)
        normalized_value = normalize_code(value)
        if normalized_key in status_map and status_map[normalized_key] != normalized_value:
            raise ValueError("status mapping keys collide after normalization")
        status_map[normalized_key] = normalized_value
    if any(value not in {"active", "inactive"} for value in status_map.values()):
        raise ValueError("status values must map explicitly to active or inactive")

    records: list[CatalogPoi] = []
    seen_ids: set[str] = set()
    for row in rows:
        content_id = _required_text(row, fields.content_id)
        if content_id in seen_ids:
            raise ValueError("snapshot contains duplicate provider content IDs")
        seen_ids.add(content_id)
        content_type = _required_text(row, fields.content_type_id)
        title = _required_text(row, fields.title)
        region_codes = frozenset(
            value.strip() for field in fields.region_codes
            if isinstance((value := row.get(field)), str) and value.strip()
        )
        district_codes = frozenset(
            value.strip() for field in fields.district_codes
            if isinstance((value := row.get(field)), str) and value.strip()
        )
        address = row.get(fields.address, "") if fields.address else ""
        if not isinstance(address, str):
            raise ValueError("snapshot address field must be text")
        raw_status = row.get(fields.status, "") if fields.status else ""
        if not isinstance(raw_status, str):
            raise ValueError("snapshot status field must be text")
        status = status_map.get(normalize_code(raw_status), "unknown") if raw_status else "unknown"
        records.append(CatalogPoi(
            content_id=content_id,
            title=title,
            address=address,
            content_type_id=content_type,
            region_codes=region_codes,
            district_codes=district_codes,
            catalog_status=status,
        ))
    return CatalogSnapshot(snapshot_version=snapshot_version, records=tuple(records))


def read_tourapi_snapshot_csv(
    path: str | Path,
    *,
    snapshot_version: str,
    fields: TourApiFieldMap,
    status_values: Mapping[str, str] | None = None,
) -> CatalogSnapshot:
    """Read a caller-approved, local CSV snapshot without emitting row data."""
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("snapshot CSV must have a header")
            required = {fields.content_id, fields.content_type_id, fields.title, *fields.region_codes}
            if fields.address:
                required.add(fields.address)
            if fields.status:
                required.add(fields.status)
            if not required.issubset(reader.fieldnames):
                raise ValueError("snapshot CSV is missing one or more explicitly mapped columns")
            return adapt_tourapi_snapshot(
                reader,
                snapshot_version=snapshot_version,
                fields=fields,
                status_values=status_values,
            )
    except UnicodeDecodeError as error:
        raise ValueError("snapshot CSV encoding is unsupported") from error


def read_source_observations_csv(
    path: str | Path,
    *,
    fields: SourceObservationFieldMap,
    default_region: str | None = None,
) -> list[SourcePoi]:
    """Read only explicitly mapped source fields for an in-memory join."""
    if fields.region is None and not (default_region and default_region.strip()):
        raise ValueError("a source region column or explicit default region is required")
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("source CSV must have a header")
            required = {fields.request_id, fields.source_item_id}
            required.update(field for field in (fields.region, fields.name, fields.district_code,
                                                 fields.address, fields.category) if field)
            if not required.issubset(reader.fieldnames):
                raise ValueError("source CSV is missing one or more explicitly mapped columns")
            result: list[SourcePoi] = []
            for row in reader:
                request_id = row.get(fields.request_id)
                source_item_id = row.get(fields.source_item_id)
                region = row.get(fields.region) if fields.region else default_region
                if not all(isinstance(value, str) for value in (request_id, source_item_id, region)):
                    raise ValueError("source CSV contains an invalid identity field")
                result.append(SourcePoi(
                    source_item_id=source_item_id,
                    region=region,
                    request_id=request_id,
                    name=row.get(fields.name, "") if fields.name else "",
                    district_code=row.get(fields.district_code, "") if fields.district_code else "",
                    address=row.get(fields.address, "") if fields.address else "",
                    category=row.get(fields.category, "") if fields.category else "",
                ))
            return result
    except UnicodeDecodeError as error:
        raise ValueError("source CSV encoding is unsupported") from error
