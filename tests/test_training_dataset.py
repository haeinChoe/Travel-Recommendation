from __future__ import annotations

import csv
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from scripts.recommendation.training_data_contract import REGION_ENV_PREFIX, REGIONS, SPLITS, VISIT_AREA_TYPE_LABELS
from scripts.recommendation.training_dataset import (
    MODEL_FEATURE_ALLOWLIST,
    SOURCE_TO_CANONICAL_COLUMNS,
    _sgg_outcome,
    resolve_item_sgg,
    strict_sgg,
    surrogate_key,
    transform,
    validate_dataset_keys,
    validate_feature_allowlist,
    validate_sgg_reconciliation,
    main,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def create_fixture(root: Path, *, bad_codebook: tuple[str, str] | None = None,
                   malformed_visit: bool = False,
                   multi_trip_sgg_conflict: bool = False) -> tuple[dict[tuple[str, str], Path], dict[str, Path]]:
    inputs: dict[tuple[str, str], Path] = {}
    masters: dict[str, Path] = {}
    for region in REGIONS:
        master_dir = root / f"{region}-other"
        masters[region] = master_dir / "tn_poi_master_POIMaster_all.csv"
        write_csv(master_dir / "tn_poi_master_POIMaster_all.csv",
            ["POI_ID", "SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC",
             "ROAD_NM_ADDR", "LOTNO_ADDR"], [
                {"POI_ID": "POI1", "SGG_CD": "11110", "ASORT_LCLASDC": "L1",
                 "ASORT_MLSFCDC": "M1", "ASORT_SDASDC": "S1", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
                {"POI_ID": "POI3", "SGG_CD": "11110", "ASORT_LCLASDC": "L3",
                 "ASORT_MLSFCDC": "M3", "ASORT_SDASDC": "S3", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
                {"POI_ID": "POI5", "SGG_CD": "", "ASORT_LCLASDC": "",
                 "ASORT_MLSFCDC": "", "ASORT_SDASDC": "", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
                {"POI_ID": "POI6", "SGG_CD": "11200", "ASORT_LCLASDC": "L6",
                 "ASORT_MLSFCDC": "M6", "ASORT_SDASDC": "S6", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
                {"POI_ID": "POI9", "SGG_CD": "11110", "ASORT_LCLASDC": "L9",
                 "ASORT_MLSFCDC": "M9", "ASORT_SDASDC": "S9", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
                {"POI_ID": "POI10", "SGG_CD": "11110", "ASORT_LCLASDC": "L10",
                 "ASORT_MLSFCDC": "M10", "ASORT_SDASDC": "S10", "ROAD_NM_ADDR": "",
                 "LOTNO_ADDR": ""},
            ])
        for split in SPLITS:
            folder = root / f"{region}-{split}"
            inputs[(region, split)] = folder
            traveler = {"TRAVELER_ID": "RAW_TRAVELER", "TRAVEL_STATUS_DESTINATION": "DEST",
                "TRAVEL_STATUS_ACCOMPANY": "1", "TRAVEL_COMPANIONS_NUM": "2"}
            traveler.update({f"TRAVEL_STYL_{i}": "1" for i in range(1, 9)})
            traveler.update({f"TRAVEL_MOTIVE_{i}": "2" for i in range(1, 4)})
            write_csv(folder / "tn_traveller_master.csv", list(traveler), [traveler])
            write_csv(folder / "tn_travel.csv",
                ["TRAVEL_ID", "TRAVELER_ID", "TRAVEL_START_YMD", "TRAVEL_END_YMD"],
                [{"TRAVEL_ID": f"RAW_TRIP_{split}", "TRAVELER_ID": "RAW_TRAVELER",
                  "TRAVEL_START_YMD": "2023-04-01", "TRAVEL_END_YMD": "2023-04-03"},
                 *([{"TRAVEL_ID": "RAW_TRIP_TL_2", "TRAVELER_ID": "RAW_TRAVELER",
                     "TRAVEL_START_YMD": "2023-04-04", "TRAVEL_END_YMD": "2023-04-05"}]
                   if multi_trip_sgg_conflict and region == "capital" and split == "TL" else [])])
            codebook = [{"cd_a": "VIS", "cd_b": code,
                "cd_nm": ("wrong" if bad_codebook == (region, split) and code == "12" else label)}
                for code, label in VISIT_AREA_TYPE_LABELS.items()]
            write_csv(folder / "tc_codeb.csv", ["cd_a", "cd_b", "cd_nm"], codebook)
            write_csv(folder / "tc_sgg.csv", ["SGG_CD", "SGG_CD1", "SGG_CD2", "SIDO_NM", "SGG_NM"], [
                {"SGG_CD": "11110", "SGG_CD1": "11", "SGG_CD2": "110",
                 "SIDO_NM": "서울특별시", "SGG_NM": "중구"},
                {"SGG_CD": "11200", "SGG_CD1": "11", "SGG_CD2": "200",
                 "SIDO_NM": "서울특별시", "SGG_NM": "종로구"},
            ])
            visits = [
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V1", "POI_ID": "POI1", "VISIT_AREA_TYPE_CD": "1", "SGG_CD": "11110", "ROAD_NM_ADDR": "street", "LOTNO_ADDR": "", "X_COORD": "1", "Y_COORD": "2"},
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V2", "POI_ID": "POI1", "VISIT_AREA_TYPE_CD": "1", "SGG_CD": "11200", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "lot", "X_COORD": "", "Y_COORD": ""},
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V3", "POI_ID": "POI3", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V3N", "POI_ID": "POI3", "VISIT_AREA_TYPE_CD": "11", "SGG_CD": "11200", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V4", "POI_ID": "POI4", "VISIT_AREA_TYPE_CD": "2", "SGG_CD": "99999", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V5", "POI_ID": "POI5", "VISIT_AREA_TYPE_CD": "11", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
            ]
            if split == "VL":
                visits = [
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V1", "POI_ID": "POI1", "VISIT_AREA_TYPE_CD": "1", "SGG_CD": "11110", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V6", "POI_ID": "VL_ONLY", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "11200", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                ]
            elif multi_trip_sgg_conflict and region == "capital":
                visits[2]["SGG_CD"] = "11110"
                visits.append({"TRAVEL_ID": "RAW_TRIP_TL_2", "VISIT_AREA_ID": "V7", "POI_ID": "POI3",
                    "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "11200", "ROAD_NM_ADDR": "",
                    "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""})
                visits.extend([
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V8", "POI_ID": "POI6", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "11110", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V9", "POI_ID": "POI6", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V10", "POI_ID": "POI7", "VISIT_AREA_TYPE_CD": "", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V11", "POI_ID": "POI8", "VISIT_AREA_TYPE_CD": "99", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V12", "POI_ID": "", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V13", "POI_ID": "POI9", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "11110", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V14", "POI_ID": "POI10", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V15", "POI_ID": "POI11", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "11110", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                    {"TRAVEL_ID": "RAW_TRIP", "VISIT_AREA_ID": "V16", "POI_ID": "POI11", "VISIT_AREA_TYPE_CD": "13", "SGG_CD": "", "ROAD_NM_ADDR": "", "LOTNO_ADDR": "", "X_COORD": "", "Y_COORD": ""},
                ])
            for visit in visits:
                if visit["TRAVEL_ID"] == "RAW_TRIP":
                    visit["TRAVEL_ID"] = f"RAW_TRIP_{split}"
            headers = ["TRAVEL_ID", "VISIT_AREA_ID", "POI_ID", "VISIT_AREA_TYPE_CD", "SGG_CD", "ROAD_NM_ADDR", "LOTNO_ADDR", "X_COORD", "Y_COORD"]
            if malformed_visit:
                headers.remove("POI_ID")
            write_csv(folder / "tn_visit_area_info.csv", headers, visits)
    return inputs, masters


class TrainingDatasetTests(unittest.TestCase):
    def test_master_address_only_and_code_address_conflict_reach_output(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root)
            for master_path in masters.values():
                with master_path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                for row in rows:
                    if row["POI_ID"] == "POI5":
                        row["ROAD_NM_ADDR"] = "서울특별시 중구 세종대로 1"
                    elif row["POI_ID"] == "POI6":
                        row["ROAD_NM_ADDR"] = "서울특별시 중구 세종대로 2"
                write_csv(master_path, list(rows[0]), rows)
            output = root / "out"
            transform(inputs, masters, output, "synthetic-run")
            con = duckdb.connect()
            by_address = con.execute(
                "SELECT canonical_admin_sgg_code, canonical_admin_location_status, "
                "canonical_admin_provenance "
                "FROM read_parquet(?) WHERE canonical_admin_provenance = ['master_address']",
                [str(output / "item_features.parquet")],
            ).fetchall()
            conflicts = con.execute(
                "SELECT canonical_admin_sgg_code, canonical_admin_location_status, "
                "canonical_admin_conflict_sources "
                "FROM read_parquet(?) WHERE source_category_l1_code = 'L6'",
                [str(output / "item_features.parquet")],
            ).fetchall()
            con.close()
            self.assertEqual(
                by_address,
                [("11110", "resolved_single_source", ["master_address"])] * len(REGIONS),
            )
            self.assertEqual(conflicts, [(None, "conflict", ["master"])] * len(REGIONS))

    def test_mapping_schema_keys_tl_isolation_and_reconciliation(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root)
            output = root / "out"
            manifest = transform(inputs, masters, output, "synthetic-run")
            self.assertEqual(manifest["outputs"]["trip_item_interaction"], 20)
            con = duckdb.connect()
            items = con.execute("SELECT * FROM read_parquet(?) ORDER BY region, item_key", [str(output / "item_features.parquet")]).fetchall()
            observed_splits = con.execute("SELECT observed_in_splits FROM read_parquet(?)", [str(output / "item_features.parquet")]).fetchall()
            columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(output / "item_features.parquet")]).fetchall()]
            schema = {r[0]: r[1] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(output / "item_features.parquet")]).fetchall()}
            interactions = con.execute("SELECT * FROM read_parquet(?)", [str(output / "trip_item_interaction.parquet")]).fetchall()
            ctx_schema = {r[0]: r[1] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(output / "trip_context.parquet")]).fetchall()}
            interaction_columns = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(output / "trip_item_interaction.parquet")]).fetchall()}
            unseen_static = con.execute(
                "SELECT source_category_l1_code, canonical_admin_sgg_code, observed_in_splits, "
                "train_positive_interaction_count FROM read_parquet(?) "
                "WHERE source_category_l1_code = 'L9'",
                [str(output / "item_features.parquet")],
            ).fetchall()
            vl_only = con.execute(
                "SELECT canonical_admin_sgg_code, canonical_admin_location_status, "
                "observed_in_splits "
                "FROM read_parquet(?) WHERE observed_in_splits = ['validation']",
                [str(output / "item_features.parquet")],
            ).fetchall()
            con.close()
            self.assertEqual(schema["train_observed_visit_type_codes"], "VARCHAR[]")
            self.assertEqual(schema["train_positive_interaction_count"], "BIGINT")
            self.assertIn("region", columns)
            self.assertIn("region", ctx_schema)
            self.assertEqual(ctx_schema["elapsed_days"], "INTEGER")
            self.assertEqual(manifest["dataset_type"], "travel-recommendation-training")
            self.assertEqual(manifest["schema_version"], "2.0")
            self.assertEqual(manifest["contract_version"], "2.0")
            self.assertEqual(
                set(columns),
                {
                    "item_key", "region", "observed_in_splits", "train_observed_visit_type_codes",
                    "canonical_admin_sido_code", "canonical_admin_sgg_code",
                    "canonical_admin_sido_name", "canonical_admin_sgg_name",
                    "canonical_admin_location_status", "canonical_admin_provenance",
                    "canonical_admin_conflict_sources", "coordinate_validation_status",
                    "source_category_l1_code", "source_category_l2_code", "source_category_l3_code",
                    "train_positive_interaction_count",
                },
            )
            self.assertNotIn("POI_ID", columns)
            ctx_columns = set(ctx_schema)
            self.assertEqual(ctx_columns, {"trip_key", "region", "split", *(f"travel_style_{i}" for i in range(1, 9)), *(f"travel_motive_{i}" for i in range(1, 4)), "travel_status_destination", "companion_status", "companion_count", "start_month", "elapsed_days"})
            self.assertEqual(interaction_columns, {"trip_key", "item_key", "region", "split", "observed_positive", "repeat_visit_count"})
            raw_columns = {"TRAVEL_STYL_1", "TRAVEL_MOTIVE_1", "TRAVEL_STATUS_DESTINATION", "TRAVEL_STATUS_ACCOMPANY", "TRAVEL_COMPANIONS_NUM", "VISIT_AREA_TYPE_CODES", "SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC", "tl_popularity"}
            self.assertFalse(raw_columns & (ctx_columns | set(columns) | interaction_columns))
            self.assertTrue(all(row[3] in {"train", "validation"} for row in interactions))
            self.assertTrue(all(set(row[0]) <= {"train", "validation"} for row in observed_splits))
            self.assertEqual(len(items), 32)  # Master inventory plus observed non-Master items
            self.assertEqual(
                unseen_static, [("L9", "11110", [], 0)] * len(REGIONS)
            )  # train-unseen Master items retain static candidate features
            self.assertEqual(vl_only, [(None, "unavailable", ["validation"])] * len(REGIONS))
            self.assertEqual(len(interactions), 20)
            self.assertTrue(all(row[4] == 1 for row in interactions))
            self.assertTrue(all(k not in json.dumps(manifest) for k in ("RAW_TRIP", "RAW_TRAVELER", "POI1", temporary, "synthetic-run")))
            for entry in manifest["sgg_audit"]["by_region_split_cohort"].values():
                self.assertEqual(sum(entry["resolved_outcome_counts"].values()), entry["denominator"])
            self.assertIn("value_conflicts", manifest["sgg_audit"]["by_region_split_cohort"]["capital:TL:all_valid_visits"]["resolved_outcome_counts"])
            self.assertIn("master_filled", manifest["sgg_audit"]["by_region_split_cohort"]["capital:TL:tourism_core"]["resolved_outcome_counts"])
            self.assertIn("sgg_unavailable_location_presence_counts", manifest["sgg_audit"]["by_region_split_cohort"]["capital:TL:all_valid_visits"])
            audit = manifest["sgg_audit"]["by_region_split_cohort"]
            self.assertGreaterEqual(audit["capital:TL:tourism_core"]["resolved_outcome_counts"].get("master_filled", 0), 1)
            self.assertGreaterEqual(audit["capital:TL:non_tourism"]["resolved_outcome_counts"].get("value_conflicts", 0), 1)
            self.assertEqual(len({row[0] for row in interactions}), 8)  # trip keys are split/region scoped
            self.assertEqual(len({row[1] for row in interactions}), 16) # item keys are region-scoped
            first_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.parquet")}
            transform(inputs, masters, output, "synthetic-run")
            second_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.parquet")}
            self.assertEqual(first_hash, second_hash)
            import duckdb as _duckdb
            check = _duckdb.connect()
            before_counts = check.execute("SELECT item_key, train_positive_interaction_count FROM read_parquet(?) ORDER BY item_key", [str(output / "item_features.parquet")]).fetchall()
            check.close()
            validation_visit = inputs[("capital", "VL")] / "tn_visit_area_info.csv"
            with validation_visit.open("a", encoding="utf-8") as stream:
                stream.write("RAW_TRIP_VL,EXTRA,POI1,1,11110,street,,1,2\n")
            transform(inputs, masters, output, "synthetic-run")
            check = _duckdb.connect()
            after_counts = check.execute("SELECT item_key, train_positive_interaction_count FROM read_parquet(?) ORDER BY item_key", [str(output / "item_features.parquet")]).fetchall()
            check.close()
            self.assertEqual(before_counts, after_counts)

    def test_source_to_canonical_mapping_uses_internal_names(self) -> None:
        self.assertEqual(SOURCE_TO_CANONICAL_COLUMNS["TRAVEL_STYL_1"], "travel_style_1")
        self.assertEqual(SOURCE_TO_CANONICAL_COLUMNS["TRAVEL_STATUS_ACCOMPANY"], "companion_status")
        self.assertEqual(SOURCE_TO_CANONICAL_COLUMNS["ASORT_SDASDC"], "source_category_l3_code")
        self.assertEqual(SOURCE_TO_CANONICAL_COLUMNS["VISIT_AREA_TYPE_CD"], "train_observed_visit_type_codes")
        self.assertEqual(SOURCE_TO_CANONICAL_COLUMNS["SGG_CD"], "visit_sgg_code_evidence")
        self.assertFalse(set(SOURCE_TO_CANONICAL_COLUMNS.values()) & set(SOURCE_TO_CANONICAL_COLUMNS))

    def test_feature_allowlist_rejects_keys_labels_and_metadata(self) -> None:
        self.assertIn("train_positive_interaction_count", MODEL_FEATURE_ALLOWLIST)
        self.assertIn("region", MODEL_FEATURE_ALLOWLIST)
        validate_feature_allowlist({"region"})
        for bad in ("trip_key", "item_key", "split", "observed_positive", "repeat_visit_count", "POI_ID", "TRAVEL_START_YMD", "ROAD_NM_ADDR", "X_COORD"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_feature_allowlist({bad})

    def test_run_scoped_keys_and_exact_sgg_membership(self) -> None:
        self.assertEqual(surrogate_key("r1", "trip", "capital", "raw"),
                         surrogate_key("r1", "trip", "capital", "raw"))
        self.assertNotEqual(surrogate_key("r1", "trip", "capital", "raw"),
                            surrogate_key("r2", "trip", "capital", "raw"))
        self.assertEqual(strict_sgg("11110", {"11110"}), "11110")
        self.assertIsNone(strict_sgg("111100", {"11110"}))
        self.assertIsNone(strict_sgg("11111", {"11110"}))

    def test_sgg_audit_distinguishes_current_visit_from_poi_aggregate(self) -> None:
        master = {"p1": {"SGG_CD": "11110"}}
        outcome = _sgg_outcome(None, None, {"11110"}, "p1", master,
                               Counter({"p1": 1}), {"11110"})
        self.assertEqual(outcome[:2], ("poi_aggregate_filled", "11110"))
        direct = _sgg_outcome("11110", "11110", {"11110"}, "p1", master,
                              Counter({"p1": 1}), {"11110"})
        self.assertEqual(direct[:2], ("direct", "11110"))
        conflict = _sgg_outcome(None, None, {"11110", "11200"}, "p1", master,
                                Counter({"p1": 1}), {"11110", "11200"})
        self.assertEqual(conflict[:2], ("value_conflicts", None))

    def test_shared_item_sgg_conflict_policy(self) -> None:
        self.assertEqual(resolve_item_sgg({"11110"}, "11200"), ("value_conflicts", None))
        self.assertEqual(resolve_item_sgg({"11110"}, "11110"), ("direct", "11110"))
        self.assertEqual(resolve_item_sgg(set(), "11110"), ("master_filled", "11110"))
        self.assertEqual(resolve_item_sgg({"11110", "11200"}, "11110"), ("value_conflicts", None))

    def test_nullability_key_integrity_and_sgg_denominator(self) -> None:
        context = [{"trip_key": "t1", "region": "capital", "split": "train", "travel_style_1": None}]
        items = [{"item_key": "i1", "region": "capital", "observed_in_splits": ["train"],
                  "train_observed_visit_type_codes": [], "sgg_code": None, "train_positive_interaction_count": 0}]
        interactions = [{"trip_key": "t1", "item_key": "i1", "region": "capital", "split": "train",
                         "observed_positive": 1, "repeat_visit_count": 2}]
        validate_dataset_keys(context, items, interactions)
        validate_sgg_reconciliation({"direct": 1, "both_missing": 2}, 3)
        with self.assertRaisesRegex(ValueError, "foreign key"):
            validate_dataset_keys(context, items, [{**interactions[0], "item_key": "unknown"}])
        with self.assertRaisesRegex(ValueError, "split leakage"):
            validate_dataset_keys(context, items, [{**interactions[0], "split": "VL"}])
        with self.assertRaisesRegex(ValueError, "denominator"):
            validate_sgg_reconciliation({"direct": 1}, 2)

    def test_codebook_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root, bad_codebook=("jeju-islands", "VL"))
            with self.assertRaisesRegex(ValueError, "TC_CODEB VIS mismatch"):
                transform(inputs, masters, root / "out", "synthetic-run")

    def test_malformed_required_columns_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root, malformed_visit=True)
            with self.assertRaisesRegex(ValueError, "Required columns"):
                transform(inputs, masters, root / "out", "synthetic-run")

    def test_tl_item_sgg_aggregates_all_trips_and_nulls_conflicts(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root, multi_trip_sgg_conflict=True)
            output = root / "out"
            manifest = transform(inputs, masters, output, "synthetic-run")
            con = duckdb.connect()
            result = con.execute(
                    "SELECT item_key, canonical_admin_sgg_code FROM read_parquet(?) "
                    "WHERE region='capital'",
                [str(output / "item_features.parquet")],
            ).fetchall()
            con.close()
            sgg_by_key = dict(result)
            item_key = lambda poi: surrogate_key("synthetic-run", "item", "capital", poi)
            self.assertEqual(sgg_by_key[item_key("POI3")], "11110")
            self.assertEqual(sgg_by_key[item_key("POI6")], "11200")
            self.assertEqual(sgg_by_key[item_key("POI9")], "11110")
            self.assertEqual(sgg_by_key[item_key("POI10")], "11110")
            self.assertIsNone(sgg_by_key[item_key("POI11")])
            self.assertNotIn("synthetic-run", json.dumps(manifest))
            audit = manifest["sgg_audit"]["by_region_split_cohort"]["capital:TL:all_valid_visits"]
            self.assertEqual(audit["resolved_outcome_counts"].get("direct"), 2)
            self.assertEqual(audit["resolved_outcome_counts"].get("poi_aggregate_filled"), 1)
            self.assertEqual(audit["resolved_outcome_counts"].get("value_conflicts"), 7)
            self.assertEqual(audit["current_visit_strict_valid_count"], 8)
            self.assertEqual(sum(audit["poi_aggregate_event_state_counts"].values()), audit["denominator"])
            self.assertEqual(sum(audit["poi_aggregate_distinct_state_counts"].values()), audit["distinct_poi_denominator"])
            self.assertEqual(sum(audit["sgg_unavailable_poi_presence_counts"].values()), audit["sgg_unavailable_observation_count"])
            self.assertEqual(sum(audit["sgg_unavailable_master_join_state_counts"].values()), audit["sgg_unavailable_observation_count"])
            type_audit = manifest["sgg_audit"]["visit_type_reconciliation"]["capital:TL"]
            self.assertEqual(sum(type_audit["visit_type_classification_counts"].values(),), type_audit["all_valid_visits_denominator"])
            self.assertEqual(type_audit["visit_type_classification_counts"]["missing_visit_type"], 1)
            self.assertEqual(type_audit["visit_type_classification_counts"]["unsupported_visit_type"], 1)
            self.assertEqual(audit["sgg_unavailable_poi_presence_counts"]["missing"], 1)
            self.assertEqual(audit["sgg_unavailable_master_join_state_counts"]["not_applicable"], 1)

    def test_argparse_errors_do_not_echo_supplied_arguments(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(["--run-id", "safe-run", "--raw-id", "PRIVATE_SENTINEL"])
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("PRIVATE_SENTINEL", stderr.getvalue())
        self.assertNotIn("--raw-id", stderr.getvalue())

    def test_missing_region_master_binding_does_not_fallback_or_transform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, masters = create_fixture(root)
            environment = {
                f"{REGION_ENV_PREFIX[region]}_{split}": str(path)
                for (region, split), path in inputs.items()
            }
            environment.update({
                f"{REGION_ENV_PREFIX[region]}_OTHER": str(path.parent)
                for region, path in masters.items()
                if region != "west"
            })
            self.assertIn("CAPITAL_OTHER", environment)
            self.assertNotIn("WEST_OTHER", environment)

            output = root / "must-not-be-created"
            stderr = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), \
                 patch("scripts.recommendation.training_dataset.transform") as transform_mock, \
                 contextlib.redirect_stderr(stderr):
                result = main(["--run-id", "no-fallback", "--output-dir", str(output)])

            self.assertEqual(result, 2)
            transform_mock.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(
                stderr.getvalue(),
                "Training dataset transformation failed; diagnostic details are suppressed for privacy.\n",
            )
            self.assertNotIn(str(root), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
