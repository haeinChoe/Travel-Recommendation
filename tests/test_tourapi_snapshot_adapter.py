from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.recommendation.tourapi_snapshot_adapter import (
    TourApiFieldMap,
    SourceObservationFieldMap,
    adapt_tourapi_snapshot,
    read_source_observations_csv,
    read_tourapi_snapshot_csv,
)


FIELDS = TourApiFieldMap(
    content_id="provider_id",
    content_type_id="provider_type",
    title="provider_title",
    region_codes=("provider_area",),
    district_codes=("provider_district",),
    address="provider_address",
    status="provider_state",
)


class TourApiSnapshotAdapterTests(unittest.TestCase):
    def test_snapshot_csv_uses_explicit_column_mapping(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.csv"
            path.write_text(
                "provider_id,provider_type,provider_title,provider_area,ignored\n"
                "0012,12,Place,11,PRIVATE\n",
                encoding="utf-8",
            )
            snapshot = read_tourapi_snapshot_csv(
                path,
                snapshot_version="synthetic-v1",
                fields=TourApiFieldMap(
                    content_id="provider_id",
                    content_type_id="provider_type",
                    title="provider_title",
                    region_codes=("provider_area",),
                    district_codes=(),
                ),
            )
        self.assertEqual(snapshot.records[0].content_id, "0012")
        self.assertEqual(snapshot.records[0].region_codes, frozenset({"11"}))
        self.assertNotIn("PRIVATE", repr(snapshot))

    def test_adapter_uses_explicit_field_map_and_keeps_unknown_status_unknown(self) -> None:
        snapshot = adapt_tourapi_snapshot(
            [{
                "provider_id": "0012", "provider_type": " 12 ", "provider_title": "Place",
                "provider_area": " 11 ", "provider_district": "11110", "provider_address": "Road 1",
                "provider_state": "unreviewed",
            }],
            snapshot_version="synthetic-v1",
            fields=FIELDS,
            status_values={"open": "active", "closed": "inactive"},
        )
        item = snapshot.records[0]
        self.assertEqual(item.content_id, "0012")
        self.assertEqual(item.content_type_id, " 12 ")
        self.assertEqual(item.catalog_status, "unknown")
        self.assertEqual(item.region_codes, frozenset({"11"}))

    def test_status_mapping_requires_explicit_product_semantics(self) -> None:
        snapshot = adapt_tourapi_snapshot(
            [{"provider_id": "1", "provider_type": "12", "provider_title": "Place",
              "provider_area": "11", "provider_state": "Y"}],
            snapshot_version="synthetic-v1",
            fields=FIELDS,
        )
        self.assertEqual(snapshot.records[0].catalog_status, "unknown")

    def test_normalized_status_mapping_collisions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "collide after normalization"):
            adapt_tourapi_snapshot(
                [{"provider_id": "1", "provider_type": "12", "provider_title": "Place",
                  "provider_area": "11", "provider_state": "y"}],
                snapshot_version="synthetic-v1",
                fields=FIELDS,
                status_values={"Y": "active", " y ": "inactive"},
            )

    def test_duplicate_provider_ids_are_rejected(self) -> None:
        row = {"provider_id": "1", "provider_type": "12", "provider_title": "Place", "provider_area": "11"}
        with self.assertRaisesRegex(ValueError, "duplicate provider content IDs"):
            adapt_tourapi_snapshot([row, row], snapshot_version="v1", fields=FIELDS)

    def test_missing_mapped_field_fails_without_printing_row_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing or non-string required field") as raised:
            adapt_tourapi_snapshot(
                [{"provider_id": "private-id"}], snapshot_version="v1", fields=FIELDS
            )
        self.assertNotIn("private-id", str(raised.exception))

    def test_local_source_adapter_reads_only_explicit_columns(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "observations.csv"
            path.write_text(
                "trip_id,poi_id,poi_name,region,private_column\ntrip-1,poi-1,Place,synthetic-region,SECRET\n",
                encoding="utf-8",
            )
            observations = read_source_observations_csv(
                path,
                fields=SourceObservationFieldMap(
                    request_id="trip_id", source_item_id="poi_id", region="region", name="poi_name"
                ),
            )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].request_id, "trip-1")
        self.assertEqual(observations[0].name, "Place")
        self.assertNotIn("SECRET", repr(observations))

    def test_source_adapter_requires_an_explicit_region_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "source region"):
            read_source_observations_csv(
                "unused.csv",
                fields=SourceObservationFieldMap(request_id="trip", source_item_id="poi"),
            )


if __name__ == "__main__":
    unittest.main()
