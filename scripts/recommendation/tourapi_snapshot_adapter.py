"""TourAPI KorService2 v4.4 snapshot adapter and read-only collector."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

from scripts.recommendation.poi_catalog_candidate_contract import (
    CatalogPoi,
    CatalogSnapshot,
    SourcePoi,
    normalize_code,
)


SNAPSHOT_CSV_COLUMNS = (
    "contentid",
    "contenttypeid",
    "title",
    "addr1",
    "addr2",
    "mapx",
    "mapy",
    "lDongRegnCd",
    "lDongSignguCd",
    "lclsSystm1",
    "lclsSystm2",
    "lclsSystm3",
    "modifiedtime",
)


def normalize_tourapi_item(item: Mapping[str, object]) -> dict[str, str]:
    """Extract and clean canonical v4.4 fields from a raw TourAPI item."""
    clean: dict[str, str] = {}
    for col in SNAPSHOT_CSV_COLUMNS:
        val = item.get(col)
        clean[col] = "" if val is None else str(val).strip()
    return clean


@dataclass(frozen=True)
class TourApiFieldMap:
    content_id: str = "contentid"
    content_type_id: str = "contenttypeid"
    title: str = "title"
    region_codes: tuple[str, ...] = ("lDongRegnCd",)
    district_codes: tuple[str, ...] = ("lDongSignguCd",)
    classification_codes: tuple[str, ...] = ("lclsSystm1", "lclsSystm2", "lclsSystm3")
    address: str | None = "addr1"
    addr2: str | None = "addr2"
    mapx: str | None = "mapx"
    mapy: str | None = "mapy"
    modified_time: str | None = "modifiedtime"


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
    retrieved_at: str = "",
    request_config_hash: str = "",
    policy_version: str = "poi-catalog-candidate-v1",
) -> CatalogSnapshot:
    """Map v4.4 provider rows without assigning provider activity semantics."""
    if not snapshot_version.strip():
        raise ValueError("snapshot version is required")
    if not fields.region_codes or not all(field.strip() for field in fields.region_codes):
        raise ValueError("at least one reviewed region-code field is required")

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
        addr2_val = row.get(fields.addr2, "") if fields.addr2 else ""
        addr2 = str(addr2_val).strip() if addr2_val is not None else ""

        mapx: float | None = None
        if fields.mapx:
            raw_mapx = row.get(fields.mapx)
            if raw_mapx is not None and str(raw_mapx).strip():
                try:
                    mapx = float(str(raw_mapx).strip())
                except ValueError:
                    mapx = None

        mapy: float | None = None
        if fields.mapy:
            raw_mapy = row.get(fields.mapy)
            if raw_mapy is not None and str(raw_mapy).strip():
                try:
                    mapy = float(str(raw_mapy).strip())
                except ValueError:
                    mapy = None

        classification_codes = tuple(
            value.strip() for field in fields.classification_codes
            if isinstance((value := row.get(field)), str) and value.strip()
        )
        modified_time = row.get(fields.modified_time, "") if fields.modified_time else ""
        if not isinstance(modified_time, str):
            raise ValueError("snapshot modified-time field must be text")
        records.append(CatalogPoi(
            content_id=content_id,
            title=title,
            address=address,
            content_type_id=content_type,
            region_codes=region_codes,
            district_codes=district_codes,
            classification_codes=classification_codes,
            modified_time=modified_time.strip(),
            addr2=addr2,
            mapx=mapx,
            mapy=mapy,
        ))
    return CatalogSnapshot(
        snapshot_version=snapshot_version,
        records=tuple(records),
        retrieved_at=retrieved_at,
        request_config_hash=request_config_hash,
        policy_version=policy_version,
    )


def read_tourapi_snapshot_csv(
    path: str | Path,
    *,
    snapshot_version: str,
    fields: TourApiFieldMap,
    retrieved_at: str = "",
    request_config_hash: str = "",
    policy_version: str = "poi-catalog-candidate-v1",
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
            if fields.modified_time:
                required.add(fields.modified_time)
            required.update(fields.classification_codes)
            if not required.issubset(reader.fieldnames):
                raise ValueError("snapshot CSV is missing one or more explicitly mapped columns")
            return adapt_tourapi_snapshot(
                reader,
                snapshot_version=snapshot_version,
                fields=fields,
                retrieved_at=retrieved_at,
                request_config_hash=request_config_hash,
                policy_version=policy_version,
            )
    except UnicodeDecodeError as error:
        raise ValueError("snapshot CSV encoding is unsupported") from error


TOURAPI_BASE_URL = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
TOURAPI_SERVICE_KEY_ENV = "TOUR_API_SERVICE_KEY"
MAX_PAGE_SIZE = 1000
MAX_NETWORK_ATTEMPTS = 3


class TourApiCollectionError(RuntimeError):
    """Safe collection failure; never includes a URL, key, body, or provider row."""


def _read_json(request: Request, *, opener, sleep, failure_prefix: str) -> object:
    """Read a JSON GET response with bounded retries for transient transport errors."""
    for attempt in range(MAX_NETWORK_ATTEMPTS):
        try:
            with opener(request, timeout=45) as response:
                return json.loads(response.read())
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == MAX_NETWORK_ATTEMPTS:
                raise TourApiCollectionError(f"{failure_prefix} HTTP failure: {error.code}") from None
        except (URLError, TimeoutError, OSError):
            if attempt + 1 == MAX_NETWORK_ATTEMPTS:
                raise TourApiCollectionError(f"{failure_prefix} network or timeout failure") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            if attempt + 1 == MAX_NETWORK_ATTEMPTS:
                raise TourApiCollectionError(f"{failure_prefix} response was not valid JSON") from None
        sleep(float(2 ** attempt))
    raise TourApiCollectionError(f"{failure_prefix} network or timeout failure")


def collect_tourapi_snapshot(
    *,
    region_codes: Iterable[str],
    content_type_ids: Iterable[str],
    page_size: int = 1000,
    service_key: str | None = None,
    opener=urlopen,
    sleep=time.sleep,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Read every paginated v4.4 area list for explicit codes and types.

    Requests are sequential and capped to reduce quota pressure. The API key is
    read from the process environment by default and never included in errors.
    """
    key = service_key if service_key is not None else os.environ.get(TOURAPI_SERVICE_KEY_ENV)
    if not key or not key.strip():
        raise TourApiCollectionError("TourAPI credential is unavailable")
    # Public-data-portal keys are sometimes stored URL-encoded. Decode once
    # in memory before urlencode to avoid sending a double-encoded key.
    key = unquote(key.strip())
    codes = tuple(sorted({str(code).strip() for code in region_codes if str(code).strip()}))
    types = tuple(sorted({str(code).strip() for code in content_type_ids if str(code).strip()}))
    if not codes or any(not code.isdigit() for code in codes):
        raise ValueError("explicit numeric legal-dong region codes are required")
    if not types or any(not code.isdigit() for code in types):
        raise ValueError("explicit numeric content type IDs are required")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("page size is outside the supported range")

    rows: dict[str, dict[str, str]] = {}
    for region_code in codes:
        for content_type_id in types:
            page = 1
            total_count: int | None = None
            while total_count is None or page <= (total_count + page_size - 1) // page_size:
                params = {
                    "serviceKey": key,
                    "MobileOS": "ETC",
                    "MobileApp": "TravelRecommendationIssue4",
                    "_type": "json",
                    "numOfRows": str(page_size),
                    "pageNo": str(page),
                    "arrange": "A",
                    "contentTypeId": content_type_id,
                    "lDongRegnCd": region_code,
                }
                url = f"{TOURAPI_BASE_URL}?{urlencode(params)}"
                request = Request(url, headers={"Accept": "application/json"})
                payload = _read_json(request, opener=opener, sleep=sleep, failure_prefix="TourAPI")
                if not isinstance(payload, dict):
                    raise TourApiCollectionError("TourAPI response had an unexpected shape")
                response_payload = payload.get("response", {})
                if not isinstance(response_payload, dict):
                    raise TourApiCollectionError("TourAPI response wrapper had an unexpected shape")
                header = response_payload.get("header", {})
                if not isinstance(header, dict):
                    raise TourApiCollectionError("TourAPI response header had an unexpected shape")
                if header.get("resultCode") != "0000":
                    code = str(header.get("resultCode", "unknown"))
                    raise TourApiCollectionError(f"TourAPI application failure: {code}")
                body = response_payload.get("body", {})
                if body is None or body == "":
                    body = {"totalCount": 0, "items": {"item": []}}
                if not isinstance(body, dict):
                    raise TourApiCollectionError("TourAPI response body had an unexpected shape")
                try:
                    total_count = int(body.get("totalCount", 0))
                except (TypeError, ValueError):
                    raise TourApiCollectionError("TourAPI total count was malformed") from None
                items_block = body.get("items", {})
                if (items_block is None or items_block == "") and total_count == 0:
                    items_block = {"item": []}
                if not isinstance(items_block, dict):
                    raise TourApiCollectionError("TourAPI item collection had an unexpected shape")
                item_block = items_block.get("item", [])
                if (item_block is None or item_block == "") and total_count == 0:
                    item_block = []
                if isinstance(item_block, dict):
                    item_block = [item_block]
                if not isinstance(item_block, list):
                    raise TourApiCollectionError("TourAPI item collection had an unexpected shape")
                for item in item_block:
                    if not isinstance(item, dict):
                        continue
                    clean = normalize_tourapi_item(item)
                    content_id = clean.get("contentid", "").strip()
                    if not content_id:
                        raise TourApiCollectionError("TourAPI returned an item without contentid")
                    previous = rows.get(content_id)
                    if previous is not None and previous != clean:
                        raise TourApiCollectionError("TourAPI returned conflicting duplicate contentid")
                    rows[content_id] = clean
                page += 1
                sleep(0.25)
    request_config = {
        "endpoint": TOURAPI_BASE_URL.rsplit("/", 1)[-1],
        "manual_version": "4.4",
        "region_codes": codes,
        "content_type_ids": types,
        "page_size": page_size,
        "arrange": "A",
        "read_only": True,
    }
    request_hash = hashlib.sha256(
        json.dumps(request_config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return list(rows.values()), request_config | {"request_config_hash": request_hash}


def fetch_current_legal_region_codes(
    *,
    service_key: str | None = None,
    opener=urlopen,
) -> tuple[str, ...]:
    """Read the current KorService2 legal-dong province codes and names safely."""
    key = service_key if service_key is not None else os.environ.get(TOURAPI_SERVICE_KEY_ENV)
    if not key or not key.strip():
        raise TourApiCollectionError("TourAPI credential is unavailable")
    endpoint = "https://apis.data.go.kr/B551011/KorService2/ldongCode2"
    common_params = {
        "serviceKey": unquote(key.strip()),
        "MobileOS": "ETC",
        "MobileApp": "TravelRecommendationIssue4",
        "_type": "json",
        "numOfRows": str(MAX_PAGE_SIZE),
        "lDongListYn": "Y",
    }
    codes: set[str] = set()
    total_count: int | None = None
    page = 1
    while total_count is None or page <= (total_count + MAX_PAGE_SIZE - 1) // MAX_PAGE_SIZE:
        params = common_params | {"pageNo": str(page)}
        url = f"{endpoint}?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json"})
        payload = _read_json(request, opener=opener, sleep=time.sleep, failure_prefix="TourAPI legal-code")
        if not isinstance(payload, dict):
            raise TourApiCollectionError("TourAPI legal-code response had an unexpected shape")
        response_payload = payload.get("response", {})
        if not isinstance(response_payload, dict):
            raise TourApiCollectionError("TourAPI legal-code response wrapper had an unexpected shape")
        header = response_payload.get("header", {})
        if not isinstance(header, dict):
            raise TourApiCollectionError("TourAPI legal-code response header had an unexpected shape")
        if header.get("resultCode") != "0000":
            raise TourApiCollectionError(
                f"TourAPI legal-code application failure: {header.get('resultCode', 'unknown')}"
            )
        body = response_payload.get("body", {})
        if not isinstance(body, dict):
            raise TourApiCollectionError("TourAPI legal-code response body had an unexpected shape")
        try:
            total_count = int(body.get("totalCount", 0))
        except (TypeError, ValueError):
            raise TourApiCollectionError("TourAPI legal-code total count was malformed") from None
        items_block = body.get("items", {})
        if not isinstance(items_block, dict):
            raise TourApiCollectionError("TourAPI legal-code collection had an unexpected shape")
        items = items_block.get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise TourApiCollectionError("TourAPI legal-code collection had an unexpected shape")
        codes.update(
            str(item.get("lDongRegnCd", "")).strip()
            for item in items if isinstance(item, dict)
        )
        page += 1
    codes.discard("")
    if not codes or any(not code.isdigit() for code in codes):
        raise TourApiCollectionError("TourAPI legal-code list was empty or malformed")
    return tuple(sorted(codes))


def write_snapshot_csv(path: str | Path, rows: Iterable[Mapping[str, str]]) -> None:
    """Write only contract fields to a caller-selected Git-ignored path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in SNAPSHOT_CSV_COLUMNS} for row in rows)


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
