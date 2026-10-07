"""2023 국내 여행로그 권역 1개를 비식별 집계로 프로파일링한다 (Issue #12).

설계 원칙 (docs/data/aihub-workflow.md, AGENTS.md 준수)
- 입력은 기본적으로 ``data/raw/`` 아래에서 읽기 전용으로 연다. ``--raw-root``로
  호출자가 지정한 외부 원본 루트도 허용한다. 결과·DuckDB 임시 파일은
  ``results/eda/travel-log-2023/``에만 쓴다.
- 공식 코드북이 아직 없으므로 컬럼 의미를 가정하지 않는다. 값을 보여 줄지는 의미가 아니라
  "타입·카디널리티·컬럼명 토큰·최소 셀 크기" 같은 구조 규칙으로만 정하고, 억제된 컬럼은
  억제 사유를 결과에 남긴다. 이 규칙은 휴리스틱이므로 결과를 공유하기 전 사람이 검토해야 한다.
- 원본 행, 개별 ID 값, 정확한 좌표, 정확한 날짜, 자유 텍스트, 사진 내용은 어떤 출력에도 쓰지 않는다.
  정확한 수치 분포값은 단일 관측값 노출 가능성 때문에 전부 생략한다. count/rate 집계는
  관련 셀 중 하나라도 k 미만이면 상호 보완되는 전체 묶음을 억제한다.
  날짜는 연-월 단위로만 요약하고, 범주 빈도도 최소 셀 크기(k) 미만을 병합·억제한다.
- 결측 처리, 중복 제거, 이상치 제거 등 정제는 하지 않는다. 관찰만 기록한다.
- 전체 파일을 pandas로 적재하지 않는다. DuckDB가 파일을 직접 스캔하고
  pandas는 작은 집계표 저장에만 쓴다.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import heapq
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw"
RESULTS_ROOT = REPO_ROOT / "results" / "eda" / "travel-log-2023"
TMP_ROOT = RESULTS_ROOT / "tmp"

TABULAR_EXTS = {".csv": "csv", ".json": "json", ".jsonl": "json", ".ndjson": "json"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic"}
OTHER_KNOWN_EXTS = {
    ".7z",
    ".avi",
    ".doc",
    ".docx",
    ".gz",
    ".html",
    ".md",
    ".mp4",
    ".pdf",
    ".rar",
    ".tar",
    ".txt",
    ".xml",
    ".zip",
}

# 스크립트가 만드는 결과 파일 이름. --overwrite는 이 목록의 파일만 교체한다.
ARTIFACTS = [
    "profile.json",
    "run_metadata.json",
    "files_inventory.csv",
    "photo_summary.csv",
    "other_files_summary.csv",
    "tables.csv",
    "columns.csv",
    "numeric_summary.csv",
    "categorical_values.csv",
    "date_months.csv",
    "relations.csv",
    "codebook_check.csv",
    "json_structure.csv",
    "anomalies.csv",
]

EXIT_GUARD = 2  # 승인·데이터·경로 조건 미충족으로 의도적으로 중단

GUIDE = """\
[중단] {reason}

실행 전 확인 (Issue #12 / docs/data/aihub-workflow.md):
  1. AI Hub 상세페이지에서 해당 권역 데이터셋의 다운로드 승인 상태를 사용자가 확인했다.
  2. 데이터별 공식 이용·취급 조건을 확인해 Issue에 기록했다.
  3. 사용자가 datasetkey/filekey를 Issue에 기록하고 다운로드 권한을 선택했다.
  4. 승인된 파일을 읽기 전용 원본 폴더에 aihubshell로 내려받았다.
     저장소 밖 원본은 --raw-root로 그 부모 폴더를 지정한다.
그 뒤에 아래와 같이 실행한다. 두 확인 옵션은 별개의 사용자 확인이다:
  uv run python scripts/eda/profile_travel_log.py \\
    --raw-root /path/to/raw --input /path/to/raw/2023-travel-log-<region> \\
    --output results/eda/travel-log-2023/<region> \\
    --confirm-approved --confirm-terms
"""

# --- 컬럼명 토큰 규칙: 의미 추정이 아니라 "노출 위험 방지용" 보수적 억제 규칙 -----------------
COORD_TOKENS = {
    "lat", "latitude", "lon", "lng", "long", "longitude", "x", "y", "mapx", "mapy",
    "coord", "coords", "coordinate", "coordinates", "gps", "geom", "geometry", "wkt",
}  # fmt: skip
COORD_SUBSTR = ("위도", "경도", "좌표")
ID_TOKENS = {
    "id", "ids", "uid", "uuid", "key", "sn", "no", "num", "seq", "idx", "index", "pk", "fk",
}  # fmt: skip
ID_SUBSTR = ("번호", "식별", "아이디")
# 장소명·캡션·주소 등 텍스트성 컬럼은 저카디널리티여도 기본 억제한다.
# 코드북으로 행정구역 등 공개 가능한 범주임을 확인한 컬럼만 --allow-value-column으로 허용한다.
TEXT_TOKENS = {
    "name", "nm", "title", "caption", "text", "memo", "desc", "description", "addr", "address",
    "poi", "place", "comment", "remark",
}  # fmt: skip
TEXT_SUBSTR = ("명칭", "장소", "주소", "내용", "캡션", "제목", "메모", "설명")

DATE_RE = r"^\d{4}[-./]?\d{2}[-./]?\d{2}([ T]\d{1,2}:?\d{2}(:?\d{2}(\.\d+)?)?)?$"
INT_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
}  # fmt: skip


def qi(name: str) -> str:
    """SQL 식별자 인용."""
    return '"' + name.replace('"', '""') + '"'


def ql(text: str) -> str:
    """SQL 문자열 리터럴 인용."""
    return "'" + text.replace("'", "''") + "'"


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [t for t in re.split(r"[^0-9A-Za-z가-힣]+", spaced.lower()) if t]


def is_coord_name(name: str) -> bool:
    return bool(set(name_tokens(name)) & COORD_TOKENS) or any(s in name for s in COORD_SUBSTR)


def is_id_name(name: str) -> bool:
    return bool(set(name_tokens(name)) & ID_TOKENS) or any(s in name for s in ID_SUBSTR)


def is_text_name(name: str) -> bool:
    return bool(set(name_tokens(name)) & TEXT_TOKENS) or any(s in name for s in TEXT_SUBSTR)


def type_class(duck_type: str) -> str:
    t = duck_type.upper()
    if t in INT_TYPES:
        return "integer"
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return "float"
    if t == "BOOLEAN":
        return "boolean"
    if t == "DATE" or t.startswith("TIMESTAMP"):
        return "datetime"
    if t == "VARCHAR":
        return "varchar"
    if t == "BLOB":
        return "blob"
    if t.startswith(("STRUCT", "MAP", "UNION")) or t.endswith("]") or t == "JSON":
        return "nested"
    return "other"


def clean_label(value: Any, limit: int = 60) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    return text[:limit]


def safe_counts(rows: list[tuple[str, int]], k: int) -> list[tuple[str, int]]:
    """최소 셀 크기 k 미만 범주를 병합한다.

    억제된 범주가 하나뿐이면 전체 합계와의 차이로 역산되므로, 병합 합계가 k 미만이면
    가장 작은 공개 범주도 함께 병합해 역산을 막는다(보완 공개 방지).
    """
    shown = sorted([r for r in rows if r[1] >= k], key=lambda r: -r[1])
    hidden = sum(n for _, n in rows if n < k)
    while 0 < hidden < k and shown:
        hidden += shown.pop()[1]
    out = list(shown)
    if hidden:
        out.append(("<suppressed>", hidden))
    return out


# --- 환경·경로 가드 --------------------------------------------------------------------------


def read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024  # kB -> bytes
    except (OSError, ValueError, IndexError):
        pass
    return info


def decide_memory_limit(override: str | None) -> tuple[str, dict[str, Any]]:
    """실제 가용 RAM을 읽어 DuckDB memory_limit을 정한다.

    다른 작업이 같은 호스트를 쓸 수 있으므로 MemAvailable의 25%를 쓰되 1~16GiB로 제한한다.
    """
    info = read_meminfo()
    detail = {
        "mem_total_bytes": info.get("MemTotal"),
        "mem_available_bytes": info.get("MemAvailable"),
        "policy": "25% of MemAvailable, clamped to [1GiB, 16GiB]",
    }
    if override:
        detail["policy"] = "user override"
        return override, detail
    avail = info.get("MemAvailable")
    if avail is None:
        raise SystemExit("MemAvailable을 읽을 수 없습니다. --memory-limit 을 직접 지정하세요.")
    gib = 2**30
    limit = min(max(int(avail * 0.25), 1 * gib), 16 * gib)
    return f"{limit // 2**20}MiB", detail


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def has_symlink_component(path: Path) -> bool:
    """Walk lexical path components before resolving away symlink ancestors."""
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


def safe_artifact_path(out: Path, name: str) -> Path:
    """Return an output target only when it resolves directly inside the output directory."""
    target = out / name
    resolved_out = out.resolve()
    if out.is_symlink() or not is_within(resolved_out, RESULTS_ROOT.resolve()):
        guard_stop("출력 폴더가 심볼릭 링크이거나 허용된 결과 경로를 벗어납니다.")
    if target.is_symlink():
        guard_stop(f"결과 파일이 심볼릭 링크입니다: {name}")
    resolved_target = target.resolve(strict=False)
    if resolved_target.parent != resolved_out:
        guard_stop(f"결과 파일 경로가 출력 폴더를 벗어납니다: {name}")
    if target.exists() and not target.is_file():
        guard_stop(f"결과 파일 위치가 일반 파일이 아닙니다: {name}")
    return target


def guard_stop(reason: str) -> None:
    print(GUIDE.format(reason=reason), file=sys.stderr)
    raise SystemExit(EXIT_GUARD)


# --- 파일 목록 ------------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_inventory(root: Path, skip_checksum: bool):
    """파일 메타데이터만 수집하고 경로 대신 순번 라벨을 결과에 쓴다."""
    tabular: list[dict[str, Any]] = []
    others: Counter[str] = Counter()
    other_bytes: Counter[str] = Counter()
    photos: dict[str, list[int]] = {}
    symlinks = 0
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        # 디렉터리 심볼릭 링크는 탐색하지 않고 파일과 동일하게 건너뛴다.
        dirs[:] = sorted(d for d in dirs if not (Path(dirpath) / d).is_symlink())
        for name in sorted(files):
            path = Path(dirpath) / name
            if path.is_symlink():
                symlinks += 1
                continue
            ext = path.suffix.lower()
            size = path.stat().st_size
            rel = path.relative_to(root).as_posix()
            if ext in TABULAR_EXTS:
                tabular.append(
                    {
                        # 파일명·상위 경로가 식별자나 장소명을 담을 수 있으므로 출력용 경로는
                        # 실제 상대 경로 대신 결정적인 순번 ID로 만든다.
                        "path": rel,
                        "abs": path,
                        "format": TABULAR_EXTS[ext],
                        "ext": ext,
                        "size_bytes": size,
                        "sha256": None if skip_checksum else sha256_of(path),
                    }
                )
            elif ext in PHOTO_EXTS:
                photos.setdefault(ext, []).append(size)
            else:
                safe_ext = ext if ext in OTHER_KNOWN_EXTS else "<other>"
                others[safe_ext] += 1
                other_bytes[safe_ext] += size
    tabular.sort(key=lambda r: r["path"])
    for i, item in enumerate(tabular, start=1):
        item["path"] = f"table_{i:06d}{item['ext']}"
    photo_rows = [
        {
            "ext": ext,
            "count": len(sizes),
            "total_bytes": sum(sizes),
            "min_bytes": min(sizes),
            "median_bytes": int(statistics.median(sizes)),
            "max_bytes": max(sizes),
        }
        for ext, sizes in sorted(photos.items())
    ]
    other_rows = [
        {"ext": ext, "count": n, "total_bytes": other_bytes[ext]}
        for ext, n in sorted(others.items())
    ]
    return tabular, photo_rows, other_rows, symlinks


def detect_encoding(path: Path) -> str:
    """앞 1MiB로 인코딩을 판별한다. DuckDB가 네트워크 없이 읽는 utf-8/utf-16만 지원한다."""
    with path.open("rb") as fh:
        head = fh.read(1 << 20)
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(head, final=False)  # 경계에서 잘린 멀티바이트는 허용
    except UnicodeDecodeError:
        return "non-utf8"
    return "utf-8"


def json_structure(path: Path, max_mb: int) -> dict[str, Any]:
    """표준 라이브러리 json으로 최상위 구조만 확인한다(값은 기록하지 않음)."""
    if path.stat().st_size > max_mb * 2**20:
        return {"status": "skipped_too_large", "top_level_type": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": f"not_single_json_document:{type(exc).__name__}", "top_level_type": None}
    out: dict[str, Any] = {"status": "ok", "top_level_type": type(data).__name__}
    if isinstance(data, list):
        out["top_level_len"] = len(data)
        key_count_distribution: Counter[int] = Counter()
        elem_types: Counter[str] = Counter()
        for item in data:
            elem_types[type(item).__name__] += 1
            if isinstance(item, dict):
                # 키는 동적 식별자일 수 있어 이름·빈도 모두 저장하지 않는다.
                key_count_distribution[len(item)] += 1
        out["element_types"] = dict(elem_types)
        out["element_key_count_distribution"] = {
            str(n): count for n, count in sorted(key_count_distribution.items())
        }
    elif isinstance(data, dict):
        # 최상위 dict의 키는 식별자일 수 있으므로 이름을 기록하지 않고 개수·값 타입만 남긴다.
        out["top_level_len"] = len(data)
        out["value_types"] = dict(Counter(type(v).__name__ for v in data.values()))
    return out


# --- DuckDB 프로파일링 -----------------------------------------------------------------------


class Profiler:
    def __init__(self, con: duckdb.DuckDBPyConnection, args: argparse.Namespace):
        self.con = con
        self.k = args.min_cell_count
        self.max_cat = args.max_categories
        self.args = args
        self.allow_values = {c.lower() for c in args.allow_value_column}
        self.rec: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "tables", "columns", "numeric_summary", "categorical_values", "date_months",
                "relations", "codebook_check", "json_structure", "anomalies",
            )
        }  # fmt: skip
        self.views: dict[str, str] = {}  # 상대경로 -> 뷰 이름
        self.col_meta: dict[str, dict[str, dict[str, Any]]] = {}  # 뷰 -> 실제컬럼명 -> 메타
        self.label_of: dict[tuple[str, str], str] = {}  # (표, 실제컬럼명) -> 출력용 라벨

    def q(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    def flag(self, level: str, table: str, column: str | None, flag: str, count: Any = None):
        self.rec["anomalies"].append(
            {"level": level, "table": table, "column": column, "flag": flag, "count": count}
        )

    def create_view(self, view: str, item: dict[str, Any]) -> dict[str, Any]:
        """원본 파일을 읽는 뷰를 만든다. 행을 복사·물질화하지 않는다."""
        path = ql(str(item["abs"]))
        info: dict[str, Any] = {"encoding": None, "status": "ok", "error_class": None}
        if item["format"] == "csv":
            enc = detect_encoding(item["abs"])
            info["encoding"] = enc
            if enc == "non-utf8":
                info["status"] = "unsupported_encoding"
                return info
            base = f"read_csv({path}, header=true, sample_size=-1, encoding={ql(enc)}"
            attempts = [base + ")", base + ", all_varchar=true)"]
        else:
            attempts = [f"read_json_auto({path}, maximum_object_size=268435456)"]
        for i, source in enumerate(attempts):
            try:
                self.con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM {source}")
                if i == 1:
                    info["status"] = "ok_all_varchar_fallback"
                return info
            except duckdb.Error as exc:
                # 오류 메시지에는 원본 값이 섞일 수 있어 클래스명만 기록한다.
                info["error_class"] = type(exc).__name__
        info["status"] = "read_failed"
        return info

    def profile_table(self, item: dict[str, Any], view: str) -> None:
        rel = item["path"]
        info = self.create_view(view, item)
        table_rec: dict[str, Any] = {
            "table": rel, "format": item["format"], "size_bytes": item["size_bytes"],
            "encoding": info["encoding"], "status": info["status"],
            "error_class": info["error_class"], "rows": None, "columns": None,
            "duplicate_rows": None, "unique_single_columns": "", "unique_composite_pairs": "",
            "names_suppressed": False,
        }  # fmt: skip
        self.rec["tables"].append(table_rec)
        if item["format"] == "json":
            structure = json_structure(item["abs"], self.args.json_stdlib_max_mb)
            self.rec["json_structure"].append(
                {"table": rel}
                | {k: json.dumps(v) if isinstance(v, dict) else v for k, v in structure.items()}
            )
        if info["status"] not in ("ok", "ok_all_varchar_fallback"):
            self.flag(
                "error", rel, None, f"table_not_profiled:{info['status']}", info["error_class"]
            )
            return
        if info["status"] == "ok_all_varchar_fallback":
            self.flag("warn", rel, None, "type_inference_failed_fallback_all_varchar")

        describe = self.q(f"DESCRIBE SELECT * FROM {view}")
        rows = self.q(f"SELECT count(*) FROM {view}")[0][0]
        table_rec["rows"], table_rec["columns"] = rows, len(describe)
        names_suppressed = len(describe) > self.args.max_columns_named
        table_rec["names_suppressed"] = names_suppressed
        meta: dict[str, dict[str, Any]] = {}
        for pos, (cname, ctype, *_rest) in enumerate(describe):
            label = f"col_{pos:04d}" if names_suppressed else cname
            self.label_of[(rel, cname)] = label
            meta[cname] = {"label": label, "type": ctype, "class": type_class(ctype), "pos": pos}
        self.col_meta[view] = meta
        if names_suppressed:
            self.flag("warn", rel, None, "column_names_suppressed_too_many_columns", len(describe))
        try:
            dup = self.q(f"SELECT {rows} - (SELECT count(*) FROM (SELECT DISTINCT * FROM {view}))")[
                0
            ][0]
            table_rec["duplicate_rows"] = dup
            if dup:
                self.flag("warn", rel, None, "fully_duplicated_rows", dup)
        except duckdb.Error as exc:
            self.flag("warn", rel, None, f"duplicate_row_check_failed:{type(exc).__name__}")

        self.basic_stats(rel, view, rows, meta)
        for cname, m in meta.items():
            try:
                self.column_detail(rel, view, rows, cname, m)
            except duckdb.Error as exc:
                m.setdefault("value_policy", "error")
                self.flag("warn", rel, m["label"], f"column_detail_failed:{type(exc).__name__}")
        table_rec["unique_single_columns"] = ";".join(
            m["label"] for m in meta.values() if m.get("unique")
        )
        table_rec["unique_composite_pairs"] = self.composite_keys(rel, view, rows, meta)
        for m in meta.values():
            public = {k: v for k, v in m.items() if not k.startswith("_") and k != "label"}
            self.rec["columns"].append({"table": rel} | public)

    # 1단계: 컬럼 묶음당 한 번의 스캔으로 기본 통계
    def basic_stats(self, rel: str, view: str, rows: int, meta: dict[str, dict[str, Any]]):
        cols = list(meta)
        for start in range(0, len(cols), 20):
            chunk = cols[start : start + 20]
            exprs: list[str] = []
            for j, cname in enumerate(chunk):
                c, cls = qi(cname), meta[cname]["class"]
                exprs.append(f"count({c})")
                if cls in ("nested", "blob", "other"):
                    continue
                exprs.append(f"count(DISTINCT {c})")
                if cls == "varchar":
                    exprs += [
                        f"count(*) FILTER (WHERE trim({c}) = '')",
                        f"min(length({c}))", f"avg(length({c}))", f"max(length({c}))",
                    ]  # fmt: skip
                if cls == "float":
                    cd = f"CAST({c} AS DOUBLE)"
                    exprs += [
                        f"count(*) FILTER (WHERE {c} IS NOT NULL AND NOT isfinite({cd}))",
                        f"min({cd}) FILTER (WHERE isfinite({cd}))",
                        f"max({cd}) FILTER (WHERE isfinite({cd}))",
                    ]
                if cls == "integer":
                    exprs += [f"min({c})", f"max({c})"]
            values = list(self.q(f"SELECT {', '.join(exprs)} FROM {view}")[0])
            it = iter(values)
            for cname in chunk:
                m, cls = meta[cname], meta[cname]["class"]
                non_null = next(it)
                m.update(column=m["label"], non_null=non_null, null_count=rows - non_null)
                m["null_rate"] = round((rows - non_null) / rows, 6) if rows else None
                m.update(
                    distinct=None,
                    duplicate_value_rows=None,
                    blank_count=None,
                    nonfinite_count=None,
                    min_len=None,
                    avg_len=None,
                    max_len=None,
                    _min=None,
                    _max=None,
                )  # fmt: skip
                if cls in ("nested", "blob", "other"):
                    continue
                m["distinct"] = next(it)
                m["duplicate_value_rows"] = non_null - m["distinct"]
                if cls == "varchar":
                    m["blank_count"], m["min_len"] = next(it), next(it)
                    avg = next(it)
                    m["avg_len"] = round(avg, 2) if avg is not None else None
                    m["max_len"] = next(it)
                elif cls == "float":
                    m["nonfinite_count"], m["_min"], m["_max"] = next(it), next(it), next(it)
                elif cls == "integer":
                    m["_min"], m["_max"] = next(it), next(it)
                m["unique"] = bool(rows and non_null == rows and m["distinct"] == rows)
                if non_null == 0:
                    self.flag("info", rel, m["label"], "column_all_null", rows)
                elif m["distinct"] == 1:
                    self.flag("info", rel, m["label"], "column_constant", non_null)
                if m["blank_count"]:
                    self.flag("info", rel, m["label"], "blank_string_values", m["blank_count"])
                if m["nonfinite_count"]:
                    self.flag("warn", rel, m["label"], "nan_or_inf_values", m["nonfinite_count"])

    def decide_policy(self, cname: str, m: dict[str, Any]) -> str:
        """값 노출 정책. 'structure_only' 또는 'suppressed:<사유>' 또는 'profile'."""
        cls, non_null, distinct = m["class"], m["non_null"], m["distinct"]
        if cls in ("nested", "blob", "other"):
            return "structure_only"
        if non_null == 0:
            return "all_null"
        if is_coord_name(cname):
            return "suppressed:coordinate_name"
        if is_id_name(cname):
            return "suppressed:identifier_name"
        if is_text_name(cname) and cname.lower() not in self.allow_values:
            return "suppressed:name_or_text_like"
        ratio = distinct / non_null
        lo, hi = m["_min"], m["_max"]
        if cls == "float" and lo is not None and lo >= -180 and hi <= 180 and ratio >= 0.5:
            return "suppressed:coordinate_like_range"
        if cls == "integer":
            if lo is not None and (
                946684800 <= lo and hi <= 4102444800 or 946684800000 <= lo and hi <= 4102444800000
            ):
                return "suppressed:epoch_like"
            if ratio >= 0.9:
                return "suppressed:row_unique_integer"
        return "profile"

    # 2단계: 컬럼별 상세
    def column_detail(self, rel: str, view: str, rows: int, cname: str, m: dict[str, Any]):
        policy = self.decide_policy(cname, m)
        m["value_policy"] = policy
        label, cls, c = m["label"], m["class"], qi(cname)
        if policy != "profile":
            if policy.startswith("suppressed"):
                self.flag("info", rel, label, f"values_{policy.replace(':', '_')}", m["non_null"])
            return
        non_null, distinct = m["non_null"], m["distinct"]
        date_kind = self.date_kind(view, c, cls, m)
        if date_kind:
            m["value_policy"] = "date_month_only"
            self.date_months(rel, view, label, c, date_kind)
            return
        if cls == "varchar" and ((m["avg_len"] or 0) > 40 or distinct / non_null > 0.2):
            m["value_policy"] = "suppressed:high_cardinality_or_text_like"
            self.flag(
                "info", rel, label, "values_suppressed_high_cardinality_or_text_like", non_null
            )
            return
        if cls in ("integer", "float"):
            self.numeric_summary(rel, view, label, c)
        if distinct <= self.max_cat and distinct / non_null <= 0.2:
            if non_null < self.k:
                m["value_policy"] = "suppressed:cohort_below_k"
                self.flag("info", rel, label, "value_counts_suppressed_below_k", "<k")
                return
            m["value_policy"] = "profile+value_counts"
            self.value_counts(rel, view, label, c)

    def date_kind(self, view: str, c: str, cls: str, m: dict[str, Any]) -> str | None:
        non_null = m["non_null"]
        if cls == "datetime":
            return "datetime"
        if cls == "varchar":
            hit = self.q(
                "SELECT count(*) FILTER (WHERE "
                f"regexp_full_match(trim({c}), {ql(DATE_RE)})) FROM {view}"
            )[0][0]
            return "varchar" if hit >= 0.95 * non_null else None
        if (
            cls == "integer"
            and m["_min"] is not None
            and 19000101 <= m["_min"]
            and m["_max"] <= 21001231
        ):
            hit = self.q(
                f"SELECT count(*) FILTER (WHERE (({c} // 100) % 100) BETWEEN 1 AND 12 "
                f"AND ({c} % 100) BETWEEN 1 AND 31) FROM {view}"
            )[0][0]
            return "int8" if hit >= 0.95 * non_null else None
        return None

    def date_months(self, rel: str, view: str, label: str, c: str, kind: str) -> None:
        """정확한 날짜는 버리고 연-월 단위 빈도만 남긴다."""
        ym = {
            "datetime": f"strftime({c}, '%Y%m')",
            "varchar": f"substr(regexp_replace(trim({c}), '[^0-9]', '', 'g'), 1, 6)",
            "int8": f"CAST({c} // 100 AS VARCHAR)",
        }[kind]
        data = self.q(
            f"SELECT ym, count(*) FROM (SELECT {ym} AS ym "
            f"FROM {view} WHERE {c} IS NOT NULL) GROUP BY ym"
        )
        valid = [
            (f"{ym[:4]}-{ym[4:6]}", n)
            for ym, n in data
            if ym and re.fullmatch(r"(19|20)\d{2}(0[1-9]|1[0-2])", ym)
        ]
        invalid = sum(n for _, n in data) - sum(n for _, n in valid)
        if invalid:
            self.flag(
                "warn",
                rel,
                label,
                "date_values_with_invalid_year_month",
                invalid if invalid >= self.k else "<k",
            )
        if not valid:
            return
        if sum(n for _, n in valid) < self.k:
            self.flag("info", rel, label, "date_summary_suppressed_below_k", "<k")
            return
        counts = safe_counts(valid, self.k)
        # 소수 월이 억제되면 실제 관측 범위도 드러내지 않는다.
        has_suppressed_months = any(month == "<suppressed>" for month, _ in counts)
        visible_months = [(month, n) for month, n in counts if month != "<suppressed>"]
        if not has_suppressed_months and visible_months:
            self.rec["date_months"].append(
                {"table": rel, "column": label, "month": "__range__", "rows": None,
                 "min_month": min(v[0] for v in visible_months),
                 "max_month": max(v[0] for v in visible_months),
                 "invalid_rows": invalid if invalid >= self.k else ("<k" if invalid else 0)}
            )  # fmt: skip
        for month, n in counts:
            self.rec["date_months"].append(
                {"table": rel, "column": label, "month": month, "rows": n,
                 "min_month": None, "max_month": None, "invalid_rows": None}
            )  # fmt: skip

    def numeric_summary(self, rel: str, view: str, label: str, c: str) -> None:
        sql = (
            "SELECT count(*), count(*) FILTER (WHERE v < 0), count(*) FILTER (WHERE v = 0) "
            f"FROM (SELECT CAST({c} AS DOUBLE) AS v FROM {view} "
            f"WHERE {c} IS NOT NULL) WHERE isfinite(v)"
        )
        n, neg, zero = self.q(sql)[0]
        if not n:
            return
        rec = {
            "table": rel,
            "column": label,
            "finite_count": n if n >= self.k else "<k",
            "negative_count": neg if neg >= self.k else "<k",
            "zero_count": zero if zero >= self.k else "<k",
            "distribution_suppression": (
                "exact_values_withheld" if n >= self.k else "cohort_below_k"
            ),
        }
        self.rec["numeric_summary"].append(rec)
        if n < self.k:
            self.flag("info", rel, label, "numeric_counts_suppressed_below_k", "<k")
        if neg:
            self.flag("info", rel, label, "negative_values_present", neg if neg >= self.k else "<k")

    def value_counts(self, rel: str, view: str, label: str, c: str) -> None:
        data = self.q(
            f"SELECT CAST({c} AS VARCHAR), count(*) FROM {view} WHERE {c} IS NOT NULL GROUP BY 1"
        )
        if sum(n for _, n in data) < self.k:
            self.flag("info", rel, label, "value_counts_suppressed_below_k", "<k")
            return
        merged: Counter[str] = Counter()
        for value, n in data:
            merged[clean_label(value)] += n
        for value, n in safe_counts(list(merged.items()), self.k):
            self.rec["categorical_values"].append(
                {"table": rel, "column": label, "value": value, "count": n}
            )

    # 키 후보: 단일 컬럼 유일성은 1단계에서 확인했고, 없을 때만 상위 카디널리티 컬럼 쌍을 검사
    def composite_keys(
        self, rel: str, view: str, rows: int, meta: dict[str, dict[str, Any]]
    ) -> str:
        if (
            not rows
            or any(m.get("unique") for m in meta.values())
            or self.args.max_composite_columns < 2
        ):
            return ""
        cand = [
            n
            for n, m in meta.items()
            if m["class"] in ("integer", "varchar", "float", "datetime", "boolean")
            and m["non_null"] == rows
        ]  # fmt: skip
        cand = sorted(cand, key=lambda n: -meta[n]["distinct"])[: self.args.max_composite_columns]
        found = []
        for i, a in enumerate(cand):
            for b in cand[i + 1 :]:
                d = self.q(f"SELECT count(DISTINCT ({qi(a)}, {qi(b)})) FROM {view}")[0][0]
                if d == rows:
                    found.append(f"{meta[a]['label']}+{meta[b]['label']}")
        return ";".join(found)

    # 테이블 간 연결 후보: 이름이 같은 컬럼 사이의 값 포함 관계(값 자체는 기록하지 않음)
    def relations(self) -> None:
        by_column: dict[str, dict[str, tuple[str, str, str, dict[str, Any]]]] = {}
        for rel, view in self.views.items():
            for cname, m in self.col_meta.get(view, {}).items():
                ok_class = m["class"] in ("integer", "varchar")
                text_like = m["class"] == "varchar" and (m["avg_len"] or 0) > 64
                if ok_class and m["non_null"] and not text_like and not is_coord_name(cname):
                    group = by_column.setdefault(cname.lower(), {})
                    candidate = (rel, view, cname, m)
                    previous = group.get(rel)
                    if (
                        previous is None
                        or m["distinct"] > previous[3]["distinct"]
                        or (m["distinct"] == previous[3]["distinct"] and cname < previous[2])
                    ):
                        group[rel] = candidate

        def pair_stream(entries):
            """Yield pairs by descending distinct-count sum without materializing combinations."""
            row_heap: list[tuple[int, int, int]] = []
            for i, left in enumerate(entries[:-1]):
                j = i + 1
                if j < len(entries):
                    score = left[3]["distinct"] + entries[j][3]["distinct"]
                    heapq.heappush(row_heap, (-score, i, j))
            while row_heap:
                neg_score, i, j = heapq.heappop(row_heap)
                yield entries[i], entries[j], -neg_score
                next_j = j + 1
                if next_j < len(entries):
                    score = entries[i][3]["distinct"] + entries[next_j][3]["distinct"]
                    heapq.heappush(row_heap, (-score, i, next_j))

        # Keep one next candidate per column-name group in a global heap. Initial
        # generation is one pair per group; each selected pair advances one stream.
        candidate_heap = []
        for stream_id, name in enumerate(sorted(by_column)):
            entries = sorted(
                by_column[name].values(),
                key=lambda entry: (-entry[3]["distinct"], entry[0], entry[2]),
            )
            stream = pair_stream(entries)
            first = next(stream, None)
            if first is not None:
                left, right, score = first
                heapq.heappush(candidate_heap, (-score, name, stream_id, left, right, stream))

        limit = max(0, self.args.max_relation_pairs)
        selected = []
        while candidate_heap and len(selected) < limit:
            neg_score, name, stream_id, left, right, stream = heapq.heappop(candidate_heap)
            selected.append((left, right))
            following = next(stream, None)
            if following is not None:
                next_left, next_right, next_score = following
                heapq.heappush(
                    candidate_heap,
                    (-next_score, name, stream_id, next_left, next_right, stream),
                )
        if candidate_heap:
            self.flag("warn", "*", None, "relation_pairs_truncated", f"at_least_{limit + 1}")

        suppressed_metrics = 0
        for left, right in selected:
            r1, v1, c1, m1 = left
            r2, v2, c2, m2 = right
            a, b = qi(c1), qi(c2)
            try:
                dl, dr, both = self.q(
                    f"WITH l AS (SELECT DISTINCT CAST({a} AS VARCHAR) k "
                    f"FROM {v1} WHERE {a} IS NOT NULL), "
                    f"r AS (SELECT DISTINCT CAST({b} AS VARCHAR) k "
                    f"FROM {v2} WHERE {b} IS NOT NULL) "
                    "SELECT (SELECT count(*) FROM l), (SELECT count(*) FROM r), "
                    "(SELECT count(*) FROM l WHERE k IN (SELECT k FROM r))"
                )[0]
                miss_l = self.q(
                    f"SELECT count(*) FROM {v1} WHERE {a} IS NOT NULL AND NOT EXISTS "
                    f"(SELECT 1 FROM {v2} WHERE CAST({b} AS VARCHAR) = CAST({a} AS VARCHAR))"
                )[0][0]
                miss_r = self.q(
                    f"SELECT count(*) FROM {v2} WHERE {b} IS NOT NULL AND NOT EXISTS "
                    f"(SELECT 1 FROM {v1} WHERE CAST({a} AS VARCHAR) = CAST({b} AS VARCHAR))"
                )[0][0]
            except duckdb.Error as exc:
                self.flag("warn", f"{r1}|{r2}", c1, f"relation_check_failed:{type(exc).__name__}")
                continue
            # Suppress the complete metric bundle if any component is below k.
            # This prevents shared counts or containment ratios from recovering a
            # small distinct/unmatched count by subtraction or division.
            if min(dl, dr, both, miss_l, miss_r) < self.k:
                suppressed_metrics += 1
                continue
            self.rec["relations"].append(
                {"left_table": r1, "right_table": r2, "left_column": m1["label"],
                 "right_column": m2["label"], "status": "ok",
                 "left_distinct": dl, "right_distinct": dr,
                 "shared_distinct": both,
                 "left_containment": round(both / dl, 6) if dl else None,
                 "right_containment": round(both / dr, 6) if dr else None,
                 "left_rows_without_match": miss_l, "right_rows_without_match": miss_r}
            )  # fmt: skip
            if miss_l or miss_r:
                self.flag("info", f"{r1}|{r2}", m1["label"], "relation_rows_without_match",
                          f"{miss_l}/{miss_r}")  # fmt: skip
        if suppressed_metrics:
            self.flag(
                "info",
                "*",
                None,
                "relation_metrics_suppressed_below_k",
                suppressed_metrics if suppressed_metrics >= self.k else "<k",
            )

    # 코드북 대조: 공식 코드북에서 사람이 옮겨 적은 허용 값 목록과 정확히 문자열 비교
    def codebook(self, path: Path) -> str:
        spec = json.loads(path.read_text(encoding="utf-8-sig"))
        source = str(spec.get("source", ""))
        if not source:
            raise SystemExit("코드북 JSON에는 공식 출처를 뜻하는 'source' 필드가 필요합니다.")
        for rel, columns in spec.get("tables", {}).items():
            view = self.views.get(rel)
            if view is None or view not in self.col_meta:
                self.rec["codebook_check"].append(
                    {"table": rel, "column": None, "status": "table_not_profiled"}
                )
                continue
            for cname, allowed in columns.items():
                if cname not in self.col_meta[view]:
                    self.rec["codebook_check"].append(
                        {"table": rel, "column": cname, "status": "column_missing_in_data"}
                    )
                    continue
                c = qi(cname)
                in_list = ", ".join(ql(str(v)) for v in allowed) or "NULL"
                has_code = (
                    f"{c} IS NOT NULL AND NOT regexp_full_match("
                    f"CAST({c} AS VARCHAR), '[[:space:]]*')"
                )
                bad_rows, bad_distinct, non_null_rows = self.q(
                    f"SELECT count(*) FILTER (WHERE {has_code} AND "
                    f"CAST({c} AS VARCHAR) NOT IN ({in_list})), "
                    f"count(DISTINCT CAST({c} AS VARCHAR)) FILTER (WHERE {has_code} AND "
                    f"CAST({c} AS VARCHAR) NOT IN ({in_list})), "
                    f"count(*) FILTER (WHERE {has_code}) FROM {view}"
                )[0]
                self.rec["codebook_check"].append(
                    {"table": rel, "column": self.col_meta[view][cname]["label"],
                     "status": "mismatch" if bad_rows else "match",
                     "allowed_value_count": len(allowed), "non_null_rows": non_null_rows,
                     "rows_outside_codebook": bad_rows,
                     "distinct_outside_codebook": bad_distinct}
                )  # fmt: skip
                if bad_rows:
                    self.flag(
                        "warn",
                        rel,
                        self.col_meta[view][cname]["label"],
                        "values_outside_codebook",
                        bad_rows,
                    )
        return source


# --- 실행 ------------------------------------------------------------------------------------


def git_state() -> dict[str, Any]:
    def run(*cmd: str) -> str | None:
        try:
            out = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
            return out.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "dirty": bool(run("git", "status", "--porcelain")),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="2023 국내 여행로그 권역 1개를 비식별 집계로 프로파일링한다 (Issue #12).",
        epilog="원본은 읽기 전용이며 결과는 results/eda/travel-log-2023/ 아래에만 쓴다.",
    )
    p.add_argument(
        "--raw-root",
        type=Path,
        default=RAW_ROOT,
        help="읽기 전용 원본 루트 (기본: 저장소 data/raw; 외부 경로를 명시할 수 있음)",
    )
    p.add_argument("--input", required=True, type=Path, help="지정한 raw-root 아래의 데이터셋 폴더")
    p.add_argument(
        "--output", required=True, type=Path, help="results/eda/travel-log-2023/<region>"
    )
    p.add_argument(
        "--confirm-approved", action="store_true",
        help="AI Hub 다운로드 승인과 Issue의 데이터 접근 권한을 사용자가 확인했다는 선언",
    )  # fmt: skip
    p.add_argument(
        "--confirm-terms", action="store_true",
        help="데이터셋의 공식 이용·취급 조건을 확인해 Issue에 기록했다는 사용자 선언",
    )  # fmt: skip
    p.add_argument("--overwrite", action="store_true", help="이 스크립트가 만든 결과 파일만 교체")
    p.add_argument("--memory-limit", help="DuckDB memory_limit (기본: 가용 RAM의 25%%, 1~16GiB)")
    p.add_argument("--threads", type=int, help="DuckDB 스레드 수 (기본: DuckDB 기본값)")
    p.add_argument("--min-cell-count", type=int, default=10, help="공개 최소 셀 크기 k (기본 10)")
    p.add_argument("--max-categories", type=int, default=50, help="값 빈도를 낼 최대 고유값 수")
    p.add_argument("--max-columns-named", type=int, default=200, help="초과 시 컬럼명 비공개")
    p.add_argument("--max-composite-columns", type=int, default=8, help="복합키 검사 컬럼 수(0=끔)")
    p.add_argument("--max-relation-pairs", type=int, default=200, help="연결 후보 검사 상한")
    p.add_argument(
        "--json-stdlib-max-mb", type=int, default=64, help="json 구조 확인 파일 크기 상한"
    )
    p.add_argument("--skip-checksum", action="store_true", help="sha256 계산 생략")
    p.add_argument(
        "--codebook",
        type=Path,
        help='{"source": "...", "tables": {"<상대경로>": {"<컬럼>": [허용값]}}}',
    )
    p.add_argument("--region-label", help="결과에 기록할 권역 라벨 (기본: 입력 폴더명)")
    p.add_argument(
        "--allow-value-column", action="append", default=[], metavar="COLUMN",
        help="이름·텍스트류 억제 규칙의 예외 컬럼(대소문자 무시, 반복 가능). "
        "코드북으로 행정구역 등 공개 가능한 범주임을 확인한 컬럼에만 사용",
    )  # fmt: skip
    return p


def _count_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        return int(value)
    return None


def _below_k(value: Any, k: int) -> bool:
    n = _count_value(value)
    return n is not None and 0 < n < k


def _suppress_fields(record: dict[str, Any], fields: tuple[str, ...]) -> int:
    changed = 0
    for field in fields:
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            record[field] = "<k"
            changed += 1
        elif isinstance(value, str) and value not in ("<k", ""):
            if _count_value(value) is not None:
                record[field] = "<k"
                changed += 1
    return changed


def _suppress_json_count_distribution(value: Any, k: int) -> tuple[Any, bool]:
    was_string = isinstance(value, str)
    try:
        parsed = json.loads(value) if was_string else value
    except json.JSONDecodeError:
        return value, False
    if not isinstance(parsed, dict):
        return value, False
    counts = [_count_value(count) for count in parsed.values()]
    if not any(n is not None and 0 < n < k for n in counts):
        return value, False
    safe = {key: "<k" for key in parsed}
    return (json.dumps(safe, ensure_ascii=False, sort_keys=True) if was_string else safe), True


def suppress_small_aggregate_cells(sections: dict[str, list[dict[str, Any]]], k: int) -> int:
    """Suppress positive sub-k aggregate cells and complementary count/rate bundles."""
    changed = 0
    table_rows: dict[str, int | None] = {}
    for row in sections.get("tables", []):
        table = str(row.get("table", ""))
        n = _count_value(row.get("rows"))
        table_rows[table] = n
        if n is not None and n < k:
            changed += _suppress_fields(row, ("rows", "columns", "duplicate_rows"))
            row["unique_single_columns"] = ""
            row["unique_composite_pairs"] = ""
        else:
            changed += _suppress_fields(row, ("columns", "duplicate_rows"))

    column_counts = (
        "non_null",
        "null_count",
        "distinct",
        "duplicate_value_rows",
        "blank_count",
        "nonfinite_count",
    )
    column_stats = column_counts + ("null_rate", "min_len", "avg_len", "max_len")
    for row in sections.get("columns", []):
        cohort_n = table_rows.get(str(row.get("table", "")))
        if cohort_n is not None and cohort_n < k:
            changed += _suppress_fields(row, column_stats)
            row["unique"] = None
            row["value_policy"] = "suppressed:cohort_below_k"
            continue
        if any(_below_k(row.get(field), k) for field in column_counts):
            changed += _suppress_fields(row, column_stats)
            row["unique"] = None

    # Per-file JSON structural counts can also describe small cohorts. If any
    # type/count bucket is small, suppress its complete distribution and total.
    for row in sections.get("json_structure", []):
        hidden = False
        for field in ("value_types", "element_key_count_distribution"):
            safe, suppressed = _suppress_json_count_distribution(row.get(field), k)
            if suppressed:
                row[field] = safe
                hidden = True
                changed += 1
        if _below_k(row.get("top_level_len"), k):
            hidden = True
        if hidden:
            if row.get("top_level_len") is not None and row.get("top_level_len") != "<k":
                row["top_level_len"] = "<k"
                changed += 1

    # Numeric summaries contain only counts; suppress a small total as a cohort.
    for row in sections.get("numeric_summary", []):
        fields = ("finite_count", "negative_count", "zero_count")
        if any(_below_k(row.get(field), k) for field in fields):
            changed += _suppress_fields(row, fields)

    # Preserve safe_counts complementary suppression if older artifacts contain
    # small cells that were not merged before serialization.
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in sections.get("categorical_values", []):
        grouped.setdefault((str(row.get("table")), str(row.get("column"))), []).append(row)
    sanitized_categories: list[dict[str, Any]] = []
    for group in grouped.values():
        hidden_rows = [row for row in group if _below_k(row.get("count"), k)]
        hidden = sum(_count_value(row.get("count")) or 0 for row in hidden_rows)
        shown = [row for row in group if row not in hidden_rows]
        while 0 < hidden < k and shown:
            smallest = min(shown, key=lambda row: _count_value(row.get("count")) or 0)
            shown.remove(smallest)
            hidden += _count_value(smallest.get("count")) or 0
        sanitized_categories.extend(shown)
        if hidden:
            sample = group[0]
            sanitized_categories.append(
                {
                    "table": sample.get("table"),
                    "column": sample.get("column"),
                    "value": "<suppressed>",
                    "count": hidden if hidden >= k else "<k",
                }
            )
        changed += len(hidden_rows) + int(len(shown) != len(group))
    if grouped:
        sections["categorical_values"] = sanitized_categories

    for row in sections.get("date_months", []):
        if _below_k(row.get("rows"), k):
            row["month"] = "<suppressed>"
            row["rows"] = "<k"
            changed += 1
        if _below_k(row.get("invalid_rows"), k):
            row["invalid_rows"] = "<k"
            changed += 1
    date_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in sections.get("date_months", []):
        date_groups.setdefault((str(row.get("table")), str(row.get("column"))), []).append(row)
    for group in date_groups.values():
        if any(row.get("month") == "<suppressed>" for row in group):
            for row in group:
                if row.get("month") == "__range__":
                    row["min_month"] = None
                    row["max_month"] = None

    for row in sections.get("anomalies", []):
        value = row.get("count")
        if _below_k(value, k):
            row["count"] = "<k"
            changed += 1
            continue
        if isinstance(value, str) and re.fullmatch(r"\d+/\d+", value):
            parts = value.split("/")
            if any(_below_k(part, k) for part in parts):
                row["count"] = "<k"
                changed += 1

    # Codebook rows carry two separate cohort statistics. Suppress them as a
    # bundle when either positive count is below k, and hide all findings for
    # a profiled table whose entire cohort is below k.
    for row in sections.get("codebook_check", []):
        table_value = table_rows.get(str(row.get("table", "")))
        table_n = _count_value(table_value)
        non_null_value = row.get("non_null_rows")
        non_null_n = _count_value(non_null_value)
        row_count = _count_value(row.get("rows_outside_codebook"))
        distinct_count = _count_value(row.get("distinct_outside_codebook"))
        if (
            (table_n is not None and table_n < k)
            or (isinstance(table_value, str) and table_value.startswith("<"))
            or (non_null_n is not None and non_null_n < k)
            or (isinstance(non_null_value, str) and non_null_value.startswith("<"))
        ):
            changed += _suppress_fields(
                row, ("non_null_rows", "rows_outside_codebook", "distinct_outside_codebook")
            )
            if row.get("status") != "suppressed_cohort_below_k":
                row["status"] = "suppressed_cohort_below_k"
                changed += 1
            continue
        if (row_count is not None and 0 < row_count < k) or (
            distinct_count is not None and 0 < distinct_count < k
        ):
            changed += _suppress_fields(row, ("rows_outside_codebook", "distinct_outside_codebook"))
            row["status"] = "suppressed_below_k"
            changed += 1

    # File-group counts below k do not support safe size aggregates.
    for section in ("photo_summary", "other_files_summary"):
        for row in sections.get(section, []):
            if _below_k(row.get("count"), k):
                changed += _suppress_fields(
                    row, ("count", "total_bytes", "min_bytes", "median_bytes", "max_bytes")
                )

    for row in sections.get("relations", []):
        fields = (
            "left_distinct",
            "right_distinct",
            "shared_distinct",
            "left_rows_without_match",
            "right_rows_without_match",
        )
        if any(_below_k(row.get(field), k) for field in fields):
            changed += _suppress_fields(row, fields + ("left_containment", "right_containment"))
    return changed


def sanitize_existing_output(out: Path) -> int:
    """Re-sanitize existing generated aggregates only; never opens the raw input."""
    requested = Path(os.path.abspath(out))
    if has_symlink_component(requested):
        guard_stop("기존 결과 경로에 심볼릭 링크가 있어 안전하게 정리할 수 없습니다.")
    resolved = requested.resolve()
    if not is_within(resolved, RESULTS_ROOT.resolve()) or resolved == RESULTS_ROOT.resolve():
        guard_stop("기존 결과 정리는 허용된 권역 결과 폴더에서만 수행할 수 있습니다.")
    profile_path = safe_artifact_path(resolved, "profile.json")
    if not profile_path.is_file():
        guard_stop("기존 profile.json이 없어 원본 재처리 없이 결과를 정리할 수 없습니다.")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    run = profile.get("run")
    if not isinstance(run, dict) or run.get("region_label") != "capital":
        guard_stop("기존 결과가 수도권 profile이 아니므로 정리를 중단합니다.")
    k = int(run.get("min_cell_count", run.get("options", {}).get("min_cell_count", 10)))
    if k != 10:
        guard_stop("기존 결과의 k가 10이 아니므로 자동 정리를 중단합니다.")
    sections = {
        name: profile.get(name, [])
        for name in (
            "files_inventory",
            "photo_summary",
            "other_files_summary",
            "tables",
            "columns",
            "numeric_summary",
            "categorical_values",
            "date_months",
            "relations",
            "codebook_check",
            "json_structure",
            "anomalies",
        )
    }
    suppressed = suppress_small_aggregate_cells(sections, k)
    profile.update(sections)

    csv_stems = tuple(sections)
    staged: dict[str, str] = {}
    for name in tuple(f"{stem}.csv" for stem in csv_stems) + ("profile.json",):
        safe_artifact_path(resolved, name)
    for stem in csv_stems:
        buffer = io.StringIO()
        pd.DataFrame(sections[stem]).to_csv(buffer, index=False, encoding="utf-8")
        staged[f"{stem}.csv"] = buffer.getvalue()
    staged["profile.json"] = json.dumps(profile, ensure_ascii=False, indent=2, default=str)
    # Prepare all content before replacing any artifact; stage on the same filesystem.
    with tempfile.TemporaryDirectory(prefix=".privacy-sanitize-", dir=resolved) as temp_name:
        temp = Path(temp_name)
        for name, content in staged.items():
            (temp / name).write_text(content, encoding="utf-8")
        for name in staged:
            target = safe_artifact_path(resolved, name)
            os.replace(temp / name, target)
    return suppressed


def write_outputs(out: Path, prof: Profiler, run: dict[str, Any], files, photos, others) -> None:
    # Validate before mkdir as well as at each write. This prevents a symlinked
    # output ancestor from causing even directory creation outside RESULTS_ROOT.
    for name in ARTIFACTS:
        safe_artifact_path(out, name)
    out.mkdir(parents=True, exist_ok=True)
    csv_tables = {
        "files_inventory": files,
        "photo_summary": photos,
        "other_files_summary": others,
        **prof.rec,
    }
    suppress_small_aggregate_cells(csv_tables, run.get("min_cell_count", 10))
    for stem, records in csv_tables.items():
        pd.DataFrame(records).to_csv(
            safe_artifact_path(out, f"{stem}.csv"), index=False, encoding="utf-8"
        )
    safe_artifact_path(out, "run_metadata.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), "utf-8"
    )
    profile = {"run": run, **csv_tables}
    safe_artifact_path(out, "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, default=str), "utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Check the caller's lexical paths before abspath()/resolve(), which would
    # collapse a symlink followed by '..' and hide that symlink component.
    requested_out = args.output
    if has_symlink_component(requested_out):
        guard_stop("출력 경로에 심볼릭 링크가 있어 결과 위치를 확인할 수 없습니다.")
    if has_symlink_component(args.raw_root):
        guard_stop("--raw-root 경로에 심볼릭 링크가 있어 읽기 전용 루트를 확인할 수 없습니다.")
    if has_symlink_component(args.input):
        guard_stop("--input 경로에 심볼릭 링크가 있어 입력 경로를 확인할 수 없습니다.")
    requested_raw_root = Path(os.path.abspath(args.raw_root))
    requested_input = Path(os.path.abspath(args.input))
    if not requested_raw_root.is_dir():
        guard_stop("--raw-root 폴더가 없습니다.")
    raw_root = requested_raw_root.resolve()
    inp, out = requested_input.resolve(), args.output.resolve()

    if not is_within(inp, raw_root) or inp == raw_root:
        guard_stop("입력은 지정한 --raw-root의 하위 데이터셋 폴더여야 합니다.")
    if not inp.is_dir():
        guard_stop(f"입력 폴더가 없습니다: {inp.relative_to(raw_root)} (원본 미다운로드)")
    if not args.confirm_approved:
        guard_stop("--confirm-approved 가 없습니다. 승인 확인 전에는 원본을 읽지 않습니다.")
    if not args.confirm_terms:
        guard_stop(
            "--confirm-terms 가 없습니다. 공식 이용·취급 조건 확인 기록 전에는 "
            "원본을 읽지 않습니다."
        )
    if (
        not is_within(out, RESULTS_ROOT)
        or out in (RESULTS_ROOT, TMP_ROOT)
        or is_within(out, TMP_ROOT)
    ):
        guard_stop(f"출력은 {RESULTS_ROOT.relative_to(REPO_ROOT)}/<권역> 하위여야 합니다.")
    existing_paths = [
        safe_artifact_path(out, n)
        for n in ARTIFACTS
        if (out / n).exists() or (out / n).is_symlink()
    ]
    existing = [p.name for p in existing_paths]
    if existing and not args.overwrite:
        guard_stop(f"출력 폴더에 기존 결과가 있습니다({len(existing)}개). 덮어쓰려면 --overwrite")
    if args.min_cell_count < 2:
        raise SystemExit("--min-cell-count 는 2 이상이어야 합니다.")
    if args.codebook and not args.codebook.is_file():
        raise SystemExit("--codebook 파일을 찾을 수 없습니다.")

    tabular, photos, others, symlinks = scan_inventory(inp, args.skip_checksum)
    if not tabular:
        guard_stop("입력 폴더에서 CSV/JSON 파일을 찾지 못했습니다(압축 해제·다운로드 상태 확인).")

    memory_limit, mem_detail = decide_memory_limit(args.memory_limit)
    if TMP_ROOT.is_symlink() or not is_within(TMP_ROOT.resolve(), RESULTS_ROOT.resolve()):
        guard_stop("DuckDB 임시 폴더가 심볼릭 링크이거나 허용된 결과 경로를 벗어납니다.")
    tmp_dir = TMP_ROOT / f"{out.name}-{os.getpid()}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC)
    try:
        free = shutil.disk_usage(RESULTS_ROOT).free
        config: dict[str, Any] = {
            "memory_limit": memory_limit,
            "temp_directory": str(tmp_dir),
            "max_temp_directory_size": f"{max(free // 2 // 2**20, 1)}MiB",
            "autoinstall_known_extensions": False,  # 확장 자동 설치(네트워크 접근) 차단
        }
        if args.threads:
            config["threads"] = args.threads
        con = duckdb.connect(":memory:", config=config)  # DB 파일을 만들지 않는다
        con.execute("SET preserve_insertion_order = false")  # 대용량 스캔의 메모리 사용 감소
        prof = Profiler(con, args)
        for i, item in enumerate(tabular):
            view = f"t{i}"
            prof.views[item["path"]] = view
            prof.profile_table(item, view)
        prof.relations()
        codebook_source = prof.codebook(args.codebook) if args.codebook else None
        if not args.codebook:
            prof.flag("info", "*", None, "codebook_check_not_run_no_codebook_provided")
        run = {
            "region_label": args.region_label or inp.name,
            "input": inp.relative_to(raw_root).as_posix(),
            "raw_root_mode": "external" if raw_root != RAW_ROOT.resolve() else "repository_default",
            "output": out.relative_to(REPO_ROOT).as_posix(),
            "started_utc": started.isoformat(), "finished_utc": datetime.now(UTC).isoformat(),
            # 원래 argv에는 로컬 코드북 경로 등이 있을 수 있으므로 원문은 저장하지 않는다.
            "options": {
                "threads": args.threads,
                "min_cell_count": args.min_cell_count,
                "max_categories": args.max_categories,
                "max_columns_named": args.max_columns_named,
                "max_composite_columns": args.max_composite_columns,
                "max_relation_pairs": args.max_relation_pairs,
                "json_stdlib_max_mb": args.json_stdlib_max_mb,
                "skip_checksum": args.skip_checksum,
                "codebook_provided": bool(args.codebook),
            },
            "code": git_state(), "python": sys.version.split()[0],
            "duckdb": duckdb.__version__, "pandas": pd.__version__,
            "duckdb_config": {k: str(v) for k, v in config.items()},
            "memory_detail": mem_detail,
            "disk_free_bytes_results": free,
            "seed": None, "sampling": "none (full scan; no random sampling)",
            "min_cell_count": args.min_cell_count, "max_categories": args.max_categories,
            "allow_value_columns": sorted(prof.allow_values),
            "codebook_source": codebook_source, "symlinks_skipped": symlinks,
            "terms_confirmed": True,
            "date_granularity": "year-month only",
            "disclosure_controls": [
                "no raw rows", "k-suppression with complementary merge",
                "coordinate/identifier/epoch/row-unique/free-text columns: values suppressed",
                "photos: extension/count/size only (no names, no content, no image header read)",
            ],
        }  # fmt: skip
        write_outputs(
            out,
            prof,
            run,
            [{k: v for k, v in t.items() if k != "abs"} for t in tabular],
            photos,
            others,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            TMP_ROOT.rmdir()  # 비어 있을 때만 제거
        except OSError:
            pass
    print(f"완료: {out.relative_to(REPO_ROOT)} (표 {len(tabular)}개, memory_limit={memory_limit})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
