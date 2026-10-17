from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from scripts.recommendation.tourapi_snapshot_adapter import (
    TourApiFieldMap,
    SourceObservationFieldMap,
    adapt_tourapi_snapshot,
    collect_tourapi_snapshot,
    fetch_current_legal_region_codes,
    read_source_observations_csv,
    read_tourapi_snapshot_csv,
)
from scripts.recommendation.poi_catalog_policy import load_poi_catalog_policy


FIELDS = TourApiFieldMap(
    content_id="provider_id",
    content_type_id="provider_type",
    title="provider_title",
    region_codes=("provider_area",),
    district_codes=("provider_district",),
    address="provider_address",
    classification_codes=(),
    modified_time=None,
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
                    address=None,
                    classification_codes=(),
                    modified_time=None,
                ),
            )
        self.assertEqual(snapshot.records[0].content_id, "0012")
        self.assertEqual(snapshot.records[0].region_codes, frozenset({"11"}))
        self.assertNotIn("PRIVATE", repr(snapshot))

    def test_adapter_does_not_infer_provider_activity_status(self) -> None:
        snapshot = adapt_tourapi_snapshot(
            [{
                "provider_id": "0012", "provider_type": " 12 ", "provider_title": "Place",
                "provider_area": " 11 ", "provider_district": "11110", "provider_address": "Road 1",
                "provider_state": "unreviewed",
            }],
            snapshot_version="synthetic-v1",
            fields=FIELDS,
        )
        item = snapshot.records[0]
        self.assertEqual(item.content_id, "0012")
        self.assertEqual(item.content_type_id, " 12 ")
        self.assertEqual(item.region_codes, frozenset({"11"}))

    def test_v44_adapter_maps_legal_codes_taxonomy_and_modified_time(self) -> None:
        snapshot = adapt_tourapi_snapshot(
            [{"contentid": "001", "contenttypeid": "12", "title": "Place",
              "addr1": "Road", "lDongRegnCd": "11", "lDongSignguCd": "11110",
              "lclsSystm1": "A", "lclsSystm2": "A01", "lclsSystm3": "A0101",
              "modifiedtime": "20261017093000"}],
            snapshot_version="synthetic-v1",
            fields=TourApiFieldMap(),
            retrieved_at="2026-10-18T00:00:00Z",
            request_config_hash="sha256:test",
        )
        item = snapshot.records[0]
        self.assertEqual(item.region_codes, frozenset({"11"}))
        self.assertEqual(item.district_codes, frozenset({"11110"}))
        self.assertEqual(item.classification_codes, ("A", "A01", "A0101"))
        self.assertEqual(item.modified_time, "20261017093000")
        self.assertEqual(snapshot.retrieved_at, "2026-10-18T00:00:00Z")
        self.assertEqual(snapshot.request_config_hash, "sha256:test")

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

    def test_read_only_collector_uses_v44_filters_and_safe_deduplication(self) -> None:
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"response": {
                    "header": {"resultCode": "0000"},
                    "body": {"totalCount": 1, "items": {"item": {
                        "contentid": "001", "contenttypeid": "12", "title": "Place",
                        "lDongRegnCd": "11", "lDongSignguCd": "11110",
                    }}}
                }}).encode()

        def opener(request, timeout):
            calls.append((request, timeout))
            return Response()

        rows, config = collect_tourapi_snapshot(
            region_codes=("11",), content_type_ids=("12",), page_size=5,
            service_key="synthetic%2Fcredential", opener=opener, sleep=lambda _seconds: None,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contentid"], "001")
        self.assertEqual(config["manual_version"], "4.4")
        self.assertEqual(config["region_codes"], ("11",))
        self.assertEqual(len(calls), 1)
        params = parse_qs(urlparse(calls[0][0].full_url).query)
        self.assertEqual(params["lDongRegnCd"], ["11"])
        self.assertEqual(params["contentTypeId"], ["12"])
        self.assertNotIn("areaCode", params)
        self.assertNotIn("sigunguCode", params)
        self.assertEqual(params["serviceKey"], ["synthetic/credential"])

    def test_read_only_collector_accepts_empty_items_only_for_zero_results(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"response": {
                    "header": {"resultCode": "0000"},
                    "body": {"totalCount": 0, "items": ""},
                }}).encode()

        rows, _config = collect_tourapi_snapshot(
            region_codes=("11",), content_type_ids=("12",),
            service_key="synthetic-key", opener=lambda *_a, **_k: Response(),
        )
        self.assertEqual(rows, [])

    def test_read_only_collector_retries_transient_transport_failure(self) -> None:
        attempts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"response": {
                    "header": {"resultCode": "0000"},
                    "body": {"totalCount": 0, "items": {"item": []}},
                }}).encode()

        def opener(_request, timeout):
            attempts.append(timeout)
            if len(attempts) == 1:
                raise URLError("private transport diagnostic")
            return Response()

        rows, _config = collect_tourapi_snapshot(
            region_codes=("11",), content_type_ids=("12",),
            service_key="synthetic-key", opener=opener, sleep=lambda _seconds: None,
        )
        self.assertEqual(rows, [])
        self.assertEqual(attempts, [45, 45])

    def test_legal_code_loader_returns_only_region_codes(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"response": {
                    "header": {"resultCode": "0000"},
                    "body": {"totalCount": 2, "items": {"item": [
                        {"lDongRegnCd": "11", "lDongRegnNm": "서울특별시"},
                        {"lDongRegnCd": "50", "lDongRegnNm": "제주특별자치도"},
                    ]}}
                }}).encode()

        requests = []

        def opener(request, timeout):
            requests.append(request)
            return Response()

        codes = fetch_current_legal_region_codes(service_key="synthetic-key", opener=opener)
        self.assertEqual(codes, ("11", "50"))
        self.assertEqual(len(requests), 1)
        params = parse_qs(urlparse(requests[0].full_url).query)
        self.assertEqual(params["lDongListYn"], ["Y"])
        self.assertEqual(params["pageNo"], ["1"])

    def test_legal_code_loader_paginates_full_list(self) -> None:
        calls = []

        class Response:
            def __init__(self, page):
                self.page = page

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                rows = ([{"lDongRegnCd": "11"}] * 1000 if self.page == 1
                        else [{"lDongRegnCd": "50"}])
                return json.dumps({"response": {
                    "header": {"resultCode": "0000"},
                    "body": {"totalCount": 1001, "items": {"item": rows}},
                }}).encode()

        def opener(request, timeout):
            calls.append(request)
            page = int(parse_qs(urlparse(request.full_url).query)["pageNo"][0])
            return Response(page)

        self.assertEqual(
            fetch_current_legal_region_codes(service_key="synthetic-key", opener=opener),
            ("11", "50"),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [parse_qs(urlparse(request.full_url).query)["pageNo"][0] for request in calls],
            ["1", "2"],
        )

    def test_v1_policy_has_full_disjoint_legal_region_partition(self) -> None:
        policy_path = Path(__file__).resolve().parents[1] / "config/recommendation/poi-catalog-policy-v1.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        region_map = policy["product_region_to_ldong_regn_cd"]
        flattened = [code for codes in region_map.values() for code in codes]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), {
            "11", "12", "26", "27", "28", "30", "31", "36110", "41",
            "43", "44", "47", "48", "50", "51", "52",
        })
        self.assertEqual(set(policy["supported_content_type_ids"]), {"12", "14", "28"})
        loaded = load_poi_catalog_policy(policy_path)
        self.assertEqual(loaded.version, "poi-catalog-candidate-v1")
        self.assertEqual(loaded.product_region_to_ldong_regn_cd["jeju-islands"], frozenset({"50"}))

    def test_v1_policy_fails_closed_if_live_codes_are_not_in_the_current_crosswalk(self) -> None:
        from scripts.recommendation.poi_catalog_policy import (
            EXPECTED_REGION_CODES, validate_live_region_codes,
        )

        policy = load_poi_catalog_policy()
        self.assertEqual(len(EXPECTED_REGION_CODES), 16)
        self.assertIn("36110", EXPECTED_REGION_CODES)
        self.assertNotIn("36", EXPECTED_REGION_CODES)
        validate_live_region_codes(set(EXPECTED_REGION_CODES), policy)
        with self.assertRaisesRegex(ValueError, "differ from the versioned policy"):
            validate_live_region_codes(set(EXPECTED_REGION_CODES) | {"99"}, policy)


if __name__ == "__main__":
    unittest.main()
