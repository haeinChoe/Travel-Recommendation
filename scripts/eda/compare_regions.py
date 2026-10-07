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
            stop(f"{d.relative_to(REPO_ROOT)}/profile.json 이 없습니다. 먼저 profile_travel_log.py 실행")
        data = json.loads(profile.read_text(encoding="utf-8"))
        label = data["run"]["region_label"]
        if label not in EXPECTED_REGIONS or d.name != label:
            stop(
                f"권역 라벨과 입력 폴더는 {', '.join(sorted(EXPECTED_REGIONS))} 중 하나로 정확히 일치해야 합니다: {d.name}"
            )
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
                "tabular_files": len(tables),
                "profiled_tables": len(ok),
                "failed_tables": len(tables) - len(ok),
                "total_rows": int(ok["rows"].sum()),
                "total_tabular_bytes": int(tables["size_bytes"].sum()),
                "photo_files": sum(p["count"] for p in data["photo_summary"]),
                "photo_bytes": sum(p["total_bytes"] for p in data["photo_summary"]),
                "tables_with_suppressed_column_names": int(ok["names_suppressed"].sum()),
                "duplicate_rows_total": int(ok["duplicate_rows"].fillna(0).sum()),
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
                    "rows": int(t["rows"]),
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
                    "rows": int(rows),
                    "null_count": int(c["null_count"]),
                    "value_policy": c.get("value_policy"),
                }
            )
        for d in data.get("date_months", []):
            if d["month"] == "__range__":
                dates.append(
                    {
                        "region": region,
                        "column": str(d["column"]).lower(),
                        "min_month": d["min_month"],
                        "max_month": d["max_month"],
                        "invalid_rows": d["invalid_rows"],
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
        .agg(tables=("table", "count"), rows=("rows", "sum"))
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
            tables=("rows", "count"),
            rows=("rows", "sum"),
            null_count=("null_count", "sum"),
            types=("type", lambda s: ";".join(sorted(set(s)))),
        )
        .reset_index()
    )
    presence["null_rate"] = (presence["null_count"] / presence["rows"]).round(6)
    n_regions = len(regions)
    presence["regions_with_column"] = presence.groupby("column")["region"].transform("nunique")
    presence["in_all_regions"] = presence["regions_with_column"] == n_regions
    presence["type_conflict"] = presence.groupby("column")["types"].transform("nunique") > 1
    return {
        "region_summary": pd.DataFrame(summary),
        "schema_groups": schema_groups,
        "column_presence": presence,
        "date_ranges": pd.DataFrame(dates),
    }


def draw_figures(out: Path, frames: dict[str, pd.DataFrame]) -> None:
    sg = frames["schema_groups"]
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.barplot(data=sg, x="schema_group", y="rows", hue="region", ax=ax)
    ax.set_yscale("log")
    ax.set_title("Rows per schema group (same column-name set) by region")
    fig.tight_layout()
    fig.savefig(safe_output_path(out, "schema_group_rows.png"), dpi=150)
    plt.close(fig)

    pres = frames["column_presence"]
    common = pres[pres["in_all_regions"]]
    if common.empty:
        return
    heat = common.pivot(index="column", columns="region", values="null_rate")
    heat = heat.loc[heat.max(axis=1).sort_values(ascending=False).index[:40]]
    fig, ax = plt.subplots(figsize=(8, max(4, 0.3 * len(heat))))
    sns.heatmap(heat, annot=True, fmt=".2f", vmin=0, vmax=1, cmap="viridis_r", ax=ax)
    ax.set_title("Null rate of columns present in every region (top 40)")
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
    existing = [
        n for n in OUTPUTS if (out / n).exists() or (out / n).is_symlink()
    ]
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
        "codebook_sources": {r: d["run"].get("codebook_source") for r, d in regions.items()},
        "code_commits": {r: d["run"].get("code", {}).get("commit") for r, d in regions.items()},
        "comparison_basis": "lowercased column-name sets; no column semantics assumed",
        "tables": {k: json.loads(v.to_json(orient="records")) for k, v in frames.items()},
    }
    safe_output_path(out, "comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"완료: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
