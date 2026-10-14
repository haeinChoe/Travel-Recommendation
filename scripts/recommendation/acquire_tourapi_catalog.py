"""Acquire a bounded, minimal KTO KorService2 listing snapshot for Issue #4.

The API key is read only from the process environment. Request URLs, raw
responses, and exception text are never logged or written. Public catalog
fields are kept only in Git-ignored results for local identity analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

RESULTS_ROOT = Path(__file__).resolve().parents[2] / "results" / "experiments" / "poi-catalog"
ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
FIELDS = (
    "contentid", "title", "addr1", "areacode", "sigungucode",
    "contenttypeid", "modifiedtime", "lDongRegnCd", "lDongSignguCd",
)


def has_symlink_component(path: Path) -> bool:
    """Reject an output path redirected through any existing parent symlink."""
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        if part in ("", "."):
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _page(opener: urllib.request.OpenerDirector, key: str, page: int,
          page_size: int) -> tuple[int, int, list[dict[str, str]]]:
    # The pre-existing public-list smoke check established that this key's
    # representation works when inserted unchanged. Never urlencode it again.
    query = ("?serviceKey=" + key + "&MobileOS=ETC&MobileApp=TravelRecommendationIssue4"
             + "&_type=json&numOfRows=" + str(page_size) + "&pageNo=" + str(page))
    request = urllib.request.Request(ENDPOINT + query, method="GET")
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("unexpected HTTP status")
        raw = response.read(16_000_001)
    if len(raw) > 16_000_000:
        raise ValueError("bounded response size exceeded")
    data = json.loads(raw)
    node = data.get("response", {})
    if node.get("header", {}).get("resultCode") != "0000":
        raise ValueError("provider did not report success")
    body = node.get("body", {})
    total = int(body["totalCount"])
    returned_size = int(body["numOfRows"])
    if int(body["pageNo"]) != page or not 0 < returned_size <= page_size:
        raise ValueError("pagination metadata inconsistent")
    items = body.get("items", {})
    records = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise ValueError("unexpected items shape")
    selected: list[dict[str, str]] = []
    for item in records:
        if not isinstance(item, dict) or not item.get("contentid"):
            raise ValueError("missing catalog identity")
        selected.append({field: str(item.get(field) or "") for field in FIELDS})
    return total, returned_size, selected


def acquire(run_id: str, *, page_size: int, max_pages: int) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run_id):
        raise ValueError("invalid run id")
    key = os.environ.get("TOUR_API_SERVICE_KEY")
    if not key:
        raise ValueError("service key unavailable")
    destination = RESULTS_ROOT / run_id
    if destination.exists() or has_symlink_component(destination.absolute()):
        raise ValueError("result destination unavailable")
    opener = urllib.request.build_opener(NoRedirect)
    started = datetime.now(UTC)
    total, actual_size, first = _page(opener, key, 1, page_size)
    if len(first) != actual_size:
        raise ValueError("first-page size inconsistent")
    page_count = math.ceil(total / actual_size)
    if total > 100_000 or page_count > max_pages:
        raise ValueError("catalog exceeds approved acquisition bound")
    records = list(first)
    first_ids = [item["contentid"] for item in first]
    for page in range(2, page_count + 1):
        time.sleep(0.2)
        reported_total, reported_size, part = _page(opener, key, page, page_size)
        expected_size = min(actual_size, total - (page - 1) * actual_size)
        if (reported_total != total or reported_size != expected_size
                or len(part) != expected_size):
            raise ValueError("catalog changed during pagination")
        records.extend(part)
    time.sleep(0.2)
    final_total, final_size, final_first = _page(opener, key, 1, page_size)
    if (final_total != total or final_size != actual_size
            or [item["contentid"] for item in final_first] != first_ids):
        raise ValueError("catalog changed during acquisition")
    ids = [item["contentid"] for item in records]
    if len(records) != total or len(set(ids)) != total:
        raise ValueError("catalog completeness or identity check failed")
    content = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n" for item in records)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    completed = datetime.now(UTC)
    manifest = {
        "provider": "Korea Tourism Organization",
        "service": "KorService2 areaBasedList2",
        "official_source": "https://www.data.go.kr/data/15101578/openapi.do",
        "official_manual_revision": "KTO Korean open-data manual v4.4",
        "authorization_basis": "Issue 4 existing-key public-catalog permission",
        "terms_reference": "https://www.data.go.kr/data/15101578/openapi.do",
        "acquisition_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "retrieved_from_utc": started.isoformat(timespec="seconds"),
        "retrieved_to_utc": completed.isoformat(timespec="seconds"),
        "snapshot_id": run_id,
        "catalog_sha256": digest,
        "total_count": total,
        "page_size": actual_size,
        "pages": page_count,
        "first_page_recheck": "same_total_and_content_ids",
        "unique_content_ids": total,
        "fields": list(FIELDS),
        "completeness": "all_reported_pages; mutable live API is not atomic",
        "listing_state_semantics": "present_in_current_public_listing_only",
        "product_type_allowlist": None,
        "legal_dong_crosswalk_version": None,
        "refresh_method": "bounded complete re-acquisition with new run ID and sync validation",
        "removed_and_temporary_closure_semantics": "unverified",
        "image_and_telephone_fields_stored": False,
        "key_or_request_url_stored": False,
    }
    destination.mkdir(parents=True, mode=0o700)
    (destination / "catalog.jsonl").write_text(content, encoding="utf-8")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"snapshot_id": run_id, "total_count": total, "pages": page_count,
            "unique_content_ids": total, "first_page_recheck": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=80)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 1000 or not 1 <= args.max_pages <= 100:
        print("[stopped] invalid acquisition bound", file=sys.stderr)
        return 2
    try:
        result = acquire(args.run_id, page_size=args.page_size, max_pages=args.max_pages)
    except Exception:  # Exception text can contain the credential or request URL.
        print("[stopped] catalog acquisition or validation failed safely", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
