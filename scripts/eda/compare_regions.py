"""권역별 profile.json(비식별 집계)만 읽어 네 권역을 같은 기준으로 비교한다 (Issue #12).

비교 기준(컬럼 의미를 가정하지 않는 구조 기준)
- 스키마 그룹: 테이블의 (소문자) 컬럼명 집합이 같으면 같은 그룹으로 본다.
- 컬럼 존재/타입/결측률: 컬럼명(소문자)이 같은 컬럼을 권역 간에 이어서 비교한다.
- 날짜: 연-월 단위 범위만 비교한다.
원본 데이터는 읽지 않으며 입력·출력 모두 results/eda/travel-log-2023/ 아래여야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # 화면 없이 파일로만 저장

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "eda" / "travel-log-2023"
OUTPUTS = [
    "region_summary.csv",
    "schema_groups.csv",
    "column_presence.csv",
    "date_ranges.csv",
    "comparison.json",
    "schema_group_rows.png",
    "null_rate_heatmap.png",
]
EXIT_GUARD = 2
EXPECTED_REGIONS = {"capital", "west", "east", "jeju-islands"}
COUNT_BUCKETS = {"0", "<10", "10+", "suppressed"}
RATE_BANDS = {
    "<10/suppressed", "0-<10%", "10-<25%", "25-<50%", "50-<75%",
    "75-<90%", "90-100%", "mixed", "suppressed",
}
PUBLIC_RATE_BANDS = (
    "0-<10%", "10-<25%", "25-<50%", "50-<75%", "75-<90%", "90-100%"
)


def count_bucket(value: Any) -> str:
    if isinstance(value, str) and value in COUNT_BUCKETS:
        return value
    if isinstance(value, bool):
        return "suppressed"
    if isinstance(value, float) and not value.is_integer():
        return "suppressed"
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "suppressed"
    if count < 0:
        return "suppressed"
    if count == 0:
        return "0"
    return "<10" if count < 10 else "10+"


def sum_count_buckets(values: Any) -> str:
    buckets = [count_bucket(value) for value in values]
    if "10+" in buckets:
        return "10+"
    if "suppressed" in buckets:
        return "suppressed"
    if not buckets or all(value == "0" for value in buckets):
        return "0"
    small = buckets.count("<10")
    if small == 1:
        return "<10"
    return "suppressed"


def coarse_rate(value: Any, numerator: Any = None, denominator: Any = None) -> str:
    if denominator in ("<10", "suppressed"):
        return "<10/suppressed"
    if isinstance(denominator, (int, float)) and denominator < 10:
        return "<10/suppressed"
    if numerator in ("<10", "suppressed"):
        return "<10/suppressed"
    if isinstance(numerator, (int, float)) and 0 < numerator < 10:
        return "<10/suppressed"
    if isinstance(value, str) and value in RATE_BANDS:
        return value
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "suppressed"
    if not 0 <= rate <= 1:
        return "suppressed"
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


def combined_rate_bands(values: Any) -> str:
    bands = {str(value) for value in values if value is not None}
    if not bands:
        return "suppressed"
    if len(bands) == 1:
        return next(iter(bands))
    if "<10/suppressed" in bands or "suppressed" in bands:
        return "<10/suppressed"
    return "mixed"


def size_band(value: Any) -> str:
    if isinstance(value, str) and value in {
        "0", "<1MiB", "1-<10MiB", "10-<100MiB", "100MiB+", "suppressed"
    }:
        return value
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "suppressed"
    if size == 0:
        return "0"
    if size < 2**20:
        return "<1MiB"
    if size < 10 * 2**20:
        return "1-<10MiB"
    if size < 100 * 2**20:
        return "10-<100MiB"
    return "100MiB+"


def combined_size_bands(values: Any) -> str:
    bands = [size_band(value) for value in values]
    if not bands or all(value == "0" for value in bands):
        return "0"
    if "100MiB+" in bands:
        return "100MiB+"
    if "10-<100MiB" in bands:
        return "10MiB+"
    if "1-<10MiB" in bands:
        return "1MiB+"
    return "suppressed"


def decade_band(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return f"{int(text[:4]) // 10 * 10}s"
    return text if text.endswith("s") and text[:-1].isdigit() else "suppressed"


def stop(message: str) -> None:
    print(f"[중단] {message}", file=sys.stderr)
    raise SystemExit(EXIT_GUARD)


def within_results(path: Path) -> bool:
    try:
        path.relative_to(RESULTS_ROOT.resolve())
        return True
    except ValueError:
        return False


def has_symlink_component(path: Path) -> bool:
    """Check an absolute lexical path before resolve() hides symlink ancestors."""
    absolute = Path(path.anchor) / path.relative_to(path.anchor)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def safe_output_path(out: Path, name: str) -> Path:
    target = out / name
    resolved_out = out.resolve()
    if out.is_symlink() or not within_results(resolved_out):
        stop("출력 폴더가 심볼릭 링크이거나 허용된 결과 경로를 벗어납니다.")
    if target.is_symlink():
        stop(f"결과 파일이 심볼릭 링크입니다: {name}")
    if target.resolve(strict=False).parent != resolved_out:
        stop(f"결과 파일 경로가 출력 폴더를 벗어납니다: {name}")
    if target.exists() and not target.is_file():
        stop(f"결과 파일 위치가 일반 파일이 아닙니다: {name}")
    return target


def load_regions(dirs: list[Path]) -> dict[str, dict[str, Any]]:
    regions: dict[str, dict[str, Any]] = {}
    for d in dirs:
        profile = d / "profile.json"
        if profile.is_symlink():
            stop(f"profile.json 이 심볼릭 링크입니다: {d.name}")
        if not profile.is_file():
            stop(
                f"{d.relative_to(REPO_ROOT)}/profile.json 이 없습니다. "
                "먼저 profile_travel_log.py를 실행하세요."
            )
        data = json.loads(profile.read_text(encoding="utf-8"))
        label = data["run"]["region_label"]
        if label not in EXPECTED_REGIONS or d.name != label:
            expected = ", ".join(sorted(EXPECTED_REGIONS))
            stop(f"권역 라벨과 입력 폴더는 {expected} 중 하나와 정확히 일치해야 합니다: {d.name}")
        if label in regions:
            stop(f"권역 라벨이 중복됩니다: {label} (입력 프로필을 확인하세요)")
        regions[label] = data
    return regions


def build_frames(regions: dict[str, dict[str, Any]]) -> dict[str, pd.DataFrame]:
    summary, groups, cols, dates = [], [], [], []
    for region, data in regions.items():
        tables = pd.DataFrame(data["tables"])
        columns = pd.DataFrame(data["columns"])
        ok = tables[tables["status"].isin(["ok", "ok_all_varchar_fallback"])]
        summary.append(
            {
                "region": region,
                "tabular_files": count_bucket(len(tables)),
                "profiled_tables": count_bucket(len(ok)),
                "failed_tables": count_bucket(len(tables) - len(ok)),
                "total_rows": sum_count_buckets(ok["rows"].tolist()),
                "total_tabular_size_band": combined_size_bands(tables["size_bytes"].tolist()),
                "tables_with_suppressed_column_names": count_bucket(
                    int(ok["names_suppressed"].sum())
                ),
                "duplicate_rows_total": sum_count_buckets(ok["duplicate_rows"].tolist()),
            }
        )
        # 컬럼명이 비공개된 표(col_NNNN)는 이름 기준 비교가 불가능하므로 제외한다.
        usable = ok[~ok["names_suppressed"]]
        for _, t in usable.iterrows():
            tcols = columns[columns["table"] == t["table"]]
            groups.append(
                {
                    "region": region,
                    "table": t["table"],
                    "rows": count_bucket(t["rows"]),
                    "signature": "|".join(sorted(tcols["column"].str.lower())),
                }
            )
        for _, c in columns[columns["table"].isin(usable["table"])].iterrows():
            rows = tables.loc[tables["table"] == c["table"], "rows"].iloc[0]
            cols.append(
                {
                    "region": region,
                    "column": str(c["column"]).lower(),
                    "type": c["type"],
                    "rows": count_bucket(rows),
                    "null_count": count_bucket(c["null_count"]),
                    "null_rate": coarse_rate(c.get("null_rate"), c.get("null_count"), rows),
                    "value_policy": c.get("value_policy"),
                }
            )
        for d in data.get("date_months", []):
            if d["month"] == "__range__":
                dates.append(
                    {
                        "region": region,
                        "column": str(d["column"]).lower(),
                        "min_period": decade_band(d["min_month"]),
                        "max_period": decade_band(d["max_month"]),
                        "invalid_rows": count_bucket(d["invalid_rows"]),
                    }
                )
    g = pd.DataFrame(groups)
    sig_order = (
        g.groupby("signature")["region"].nunique().sort_values(ascending=False, kind="stable")
    )
    sig_id = {s: f"S{i + 1:02d}" for i, s in enumerate(sig_order.index)}
    g["schema_group"] = g["signature"].map(sig_id)
    schema_groups = (
        g.groupby(["schema_group", "region"])
        .agg(
            tables=("table", lambda values: count_bucket(len(values))),
            rows=("rows", sum_count_buckets),
        )
        .reset_index()
        .merge(
            g.drop_duplicates("schema_group")[["schema_group", "signature"]],
            on="schema_group",
        )
        .rename(columns={"signature": "columns"})
    )
    c = pd.DataFrame(cols)
    presence = (
        c.groupby(["column", "region"])
        .agg(
            tables=("rows", lambda values: count_bucket(len(values))),
            rows=("rows", sum_count_buckets),
            null_count=("null_count", sum_count_buckets),
            types=("type", lambda s: ";".join(sorted(set(s)))),
            null_rate=("null_rate", combined_rate_bands),
        )
        .reset_index()
    )
    n_regions = len(regions)
    presence["in_all_regions"] = (
        presence.groupby("column")["region"].transform("nunique") == n_regions
    )
    presence["type_conflict"] = presence.groupby("column")["types"].transform("nunique") > 1
    return {
        "region_summary": pd.DataFrame(summary),
        "schema_groups": schema_groups,
        "column_presence": presence,
        "date_ranges": pd.DataFrame(dates),
    }


def draw_figures(out: Path, frames: dict[str, pd.DataFrame]) -> None:
    sg = frames["schema_groups"]
    row_order = {"0": 0, "<10": 1, "10+": 2, "suppressed": 1}
    plot_rows = sg.assign(_row_bucket=sg["rows"].map(row_order).fillna(1))
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.barplot(data=plot_rows, x="schema_group", y="_row_bucket", hue="region", ax=ax)
    ax.set_yticks([0, 1, 2], labels=["0", "<10", "10+"])
    ax.set_title("Row-count bucket per schema group by region")
    fig.tight_layout()
    fig.savefig(safe_output_path(out, "schema_group_rows.png"), dpi=150)
    plt.close(fig)

    pres = frames["column_presence"]
    common = pres[pres["in_all_regions"]]
    if common.empty:
        return
    heat_labels = common.pivot(index="column", columns="region", values="null_rate")
    rate_labels = ("<10/suppressed", *PUBLIC_RATE_BANDS, "mixed", "suppressed")
    rate_order = {name: index for index, name in enumerate(rate_labels)}
    heat_codes = heat_labels.apply(lambda column: column.map(rate_order).fillna(-1))
    heat_codes = heat_codes.loc[heat_codes.max(axis=1).sort_values(ascending=False).index[:40]]
    heat_labels = heat_labels.loc[heat_codes.index]
    fig, ax = plt.subplots(figsize=(8, max(4, 0.3 * len(heat_codes))))
    sns.heatmap(
        heat_codes, annot=heat_labels, fmt="", vmin=-1, vmax=len(rate_order) - 1,
        cmap="viridis_r", ax=ax,
    )
    ax.set_title("Null-rate bands for columns present in every region (top 40)")
    fig.tight_layout()
    fig.savefig(safe_output_path(out, "null_rate_heatmap.png"), dpi=150)
    plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="권역별 profile.json(비식별 집계)을 같은 기준으로 비교한다 (Issue #12).",
        epilog="입력과 출력은 모두 results/eda/travel-log-2023/ 아래여야 한다. 원본은 읽지 않는다.",
    )
    p.add_argument(
        "--inputs", nargs="+", required=True, type=Path,
        help="profile_travel_log.py 결과 폴더들 (capital, west, east, jeju-islands 각 1개)",
    )  # fmt: skip
    p.add_argument(
        "--output", type=Path, default=RESULTS_ROOT / "comparison",
        help="비교 결과 폴더 (기본: results/eda/travel-log-2023/comparison)",
    )  # fmt: skip
    p.add_argument("--overwrite", action="store_true", help="이 스크립트가 만든 결과 파일만 교체")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inputs = [p.resolve() for p in args.inputs]
    requested_out = args.output.absolute()
    if has_symlink_component(requested_out):
        stop("출력 경로에 심볼릭 링크가 있어 결과 위치를 확인할 수 없습니다.")
    out = args.output.resolve()
    if not all(within_results(p) for p in inputs) or not within_results(out):
        stop("입력·출력 모두 results/eda/travel-log-2023/ 하위여야 합니다.")
    existing = [n for n in OUTPUTS if (out / n).exists() or (out / n).is_symlink()]
    for name in existing:
        safe_output_path(out, name)
    if existing and not args.overwrite:
        stop(f"출력 폴더에 기존 결과가 있습니다({len(existing)}개). 덮어쓰려면 --overwrite")
    for name in OUTPUTS:
        safe_output_path(out, name)
    regions = load_regions(inputs)
    if set(regions) != EXPECTED_REGIONS:
        stop(
            "정확히 네 권역(capital, west, east, jeju-islands)의 프로필이 필요합니다. "
            f"현재 라벨: {', '.join(sorted(regions))}"
        )

    frames = build_frames(regions)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(safe_output_path(out, f"{name}.csv"), index=False, encoding="utf-8")
    draw_figures(out, frames)
    summary = {
        "regions": list(regions),
        "codebook_provided": {
            r: bool(d["run"].get("codebook_source_recorded", d["run"].get("codebook_source")))
            for r, d in regions.items()
        },
        "code_commits": {r: d["run"].get("code", {}).get("commit") for r, d in regions.items()},
        "comparison_basis": "lowercased column-name sets; no column semantics assumed",
        "public_output_policy": (
            "count buckets 0/<10/10+ or suppressed; coarse rate bands; no raw values"
        ),
        "tables": {k: json.loads(v.to_json(orient="records")) for k, v in frames.items()},
    }
    safe_output_path(out, "comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"완료: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
