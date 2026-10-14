"""Acquire bounded KTO display-state evidence without logging credentials.

The official KorService2 v4.4 manual defines areaBasedSyncList2 showflag:
1 = displayed, 0 = not displayed. This does not establish opening hours or
historical 2023 availability. Minimal rows stay in Git-ignored results.
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
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from acquire_tourapi_catalog import NoRedirect, has_symlink_component

RESULTS_ROOT = Path(__file__).resolve().parents[2] / "results" / "experiments" / "poi-sync-state"
ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/areaBasedSyncList2"


def _page(opener: urllib.request.OpenerDirector, key: str, flag: str,
          page: int, page_size: int) -> tuple[int, int, list[dict[str, str]]]:
    query = ("?serviceKey=" + key + "&MobileOS=ETC&MobileApp=TravelRecommendationIssue4"
             + "&_type=json&showflag=" + flag + "&numOfRows=" + str(page_size)
             + "&pageNo=" + str(page))
    with opener.open(urllib.request.Request(ENDPOINT + query, method="GET"), timeout=30) as response:
        if response.status != 200:
            raise ValueError("unexpected HTTP status")
        raw = response.read(16_000_001)
    if len(raw) > 16_000_000:
        raise ValueError("bounded response size exceeded")
    node = json.loads(raw).get("response", {})
    if node.get("header", {}).get("resultCode") != "0000":
        raise ValueError("provider did not report success")
    body = node.get("body", {})
    total = int(body["totalCount"])
    returned_size = int(body["numOfRows"])
    if int(body["pageNo"]) != page or not 0 < returned_size <= page_size:
        raise ValueError("pagination metadata inconsistent")
    items = body.get("items", {})
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("unexpected items shape")
    selected = []
    for item in rows:
        if (not isinstance(item, dict) or not item.get("contentid")
                or str(item.get("showflag")) != flag):
            raise ValueError("display-state field mismatch")
        selected.append({"contentid": str(item["contentid"]),
                         "showflag": flag,
                         "modifiedtime": str(item.get("modifiedtime") or "")})
    return total, returned_size, selected


def _collect(opener: urllib.request.OpenerDirector, key: str, flag: str,
             page_size: int, max_pages: int) -> tuple[list[dict[str, str]], int]:
    total, actual_size, first = _page(opener, key, flag, 1, page_size)
    if len(first) != actual_size:
        raise ValueError("first-page size inconsistent")
    pages = math.ceil(total / actual_size)
    if total > 100_000 or pages > max_pages:
        raise ValueError("sync-state acquisition bound exceeded")
    rows = list(first)
    first_ids = [item["contentid"] for item in first]
    for page in range(2, pages + 1):
        time.sleep(0.2)
        reported_total, reported_size, part = _page(opener, key, flag, page, page_size)
        expected = min(actual_size, total - (page - 1) * actual_size)
        if reported_total != total or reported_size != expected or len(part) != expected:
            raise ValueError("sync-state pagination changed")
        rows.extend(part)
    time.sleep(0.2)
    final_total, final_size, final_first = _page(opener, key, flag, 1, page_size)
    if (final_total != total or final_size != actual_size
            or [item["contentid"] for item in final_first] != first_ids):
        raise ValueError("sync-state changed during acquisition")
    ids = [item["contentid"] for item in rows]
    if len(rows) != total or len(set(ids)) != total:
        raise ValueError("sync-state completeness check failed")
    return rows, pages


def acquire(run_id: str, *, page_size: int, max_pages: int) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run_id):
        raise ValueError("invalid run ID")
    key = os.environ.get("TOUR_API_SERVICE_KEY")
    if not key:
        raise ValueError("service key unavailable")
    target = RESULTS_ROOT / run_id
    if target.exists() or has_symlink_component(target.absolute()):
        raise ValueError("result destination unavailable")
    opener = urllib.request.build_opener(NoRedirect)
    started = datetime.now(UTC)
    shown, shown_pages = _collect(opener, key, "1", page_size, max_pages)
    hidden, hidden_pages = _collect(opener, key, "0", page_size, max_pages)
    shown_ids = {row["contentid"] for row in shown}
    hidden_ids = {row["contentid"] for row in hidden}
    if shown_ids & hidden_ids:
        raise ValueError("conflicting display states")
    rows = shown + hidden
    content = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    manifest = {
        "provider": "Korea Tourism Organization",
        "service": "KorService2 areaBasedSyncList2",
        "official_source": "https://www.data.go.kr/data/15101578/openapi.do",
        "official_manual": "KTO Korean open-data manual v4.4",
        "authorization_basis": "Issue 4 existing-key public-catalog permission",
        "terms_reference": "https://www.data.go.kr/data/15101578/openapi.do",
        "acquisition_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "retrieved_from_utc": started.isoformat(timespec="seconds"),
        "retrieved_to_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot_id": run_id,
        "sync_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "shown_count": len(shown), "hidden_count": len(hidden),
        "shown_pages": shown_pages, "hidden_pages": hidden_pages,
        "first_page_recheck": "passed_for_each_flag",
        "state_meaning": "1=displayed;0=not_displayed;not_operational_open_status",
        "refresh_method": "bounded complete re-acquisition with new run ID and listing validation",
        "key_or_request_url_stored": False,
    }
    target.mkdir(parents=True, mode=0o700)
    (target / "sync_state.jsonl").write_text(content, encoding="utf-8")
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"snapshot_id": run_id, "shown_count": len(shown),
            "hidden_count": len(hidden), "pages": shown_pages + hidden_pages}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 1000 or not 1 <= args.max_pages <= 100:
        print("[stopped] invalid acquisition bound", file=sys.stderr)
        return 2
    try:
        result = acquire(args.run_id, page_size=args.page_size, max_pages=args.max_pages)
    except Exception:  # Never reveal exception text: it may contain the URL or key.
        print("[stopped] sync-state acquisition or validation failed safely", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
