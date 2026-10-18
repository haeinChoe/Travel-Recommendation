"""Compare visit-row vs TN_POI_MASTER metadata and regional vs global identity scope.

All raw identifiers and source fields remain in memory. Only aggregate JSON is written.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_popularity as shared
from analyze_poi_catalog_candidate_coverage import (
    REGIONS, ROLES, ROLE_ENV, _read_catalog, _source_rows, _verify_snapshot,
)
from poi_catalog_candidate_contract import (
    CatalogPoi, MatchResult, SourcePoi, eligibility_reason, match_source_item, normalize_text,
)
from poi_catalog_policy import load_poi_catalog_policy
from tourapi_snapshot_adapter import TourApiFieldMap, read_tourapi_snapshot_csv

FIELDS = ("POI_NM", "SGG_CD", "LOTNO_ADDR", "ROAD_NM_ADDR")
ARM_META = {"A": "visit", "B": "master", "C": "visit", "D": "master",
            "E": "master_first_visit_fallback"}
ARM_SCOPE = {"A": "source_region", "B": "source_region", "C": "global", "D": "global",
             "E": "global"}
CANONICAL_IDENTITY_ARM = "D"
FUZZY_TOP_N = 5
FUZZY_PREFILTER_LIMIT = 250
PARENTHETICAL_PATTERN = re.compile(
    r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|【[^【】]*】|〔[^〔〕]*〕|"
    r"〈[^〈〉]*〉|《[^《》]*》|「[^「」]*」|『[^『』]*』"
)
BRANCH_PATTERN = re.compile(r"(?:지점|본점|DT\s*점|점)\s*$", re.IGNORECASE)
FACILITY_SUBPOI_PATTERN = re.compile(r"(?:주차장|입구|관리소)")
NUMBER_TOKEN_PATTERN = re.compile(r"\d+")
LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z]+")


def _arm_e_sources(master_sources, visit_sources, poi_ids):
    """Choose metadata explicitly for Arm E and retain aggregateable provenance."""
    selected = {}
    provenance = {}
    for poi_id in poi_ids:
        if poi_id in master_sources:
            selected[poi_id] = master_sources[poi_id]
            provenance[poi_id] = "master"
        elif poi_id in visit_sources:
            selected[poi_id] = visit_sources[poi_id]
            provenance[poi_id] = "visit_fallback"
        else:
            provenance[poi_id] = "identity_source_missing"
    return selected, provenance


def _compare_master_visit_identity(region, positives, visit_sources, master_sources, global_index, policy):
    """Shadow-compare both metadata sources against the same global exact-match catalog."""
    admin = {key: frozenset(value) for key, value in policy.product_region_to_ldong_regn_cd.items()}
    comparisons = []
    for _trip, poi_id in positives:
        if poi_id not in visit_sources or poi_id not in master_sources:
            continue

        def resolve(signals):
            names = {normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])}
            by_id = {item.content_id: item for name in names for item in global_index.get(name, [])}
            return _resolve_one(poi_id, signals, region, list(by_id.values()), admin, global_scope=True)

        visit_result = resolve(visit_sources[poi_id])
        master_result = resolve(master_sources[poi_id])
        if visit_result.method == "source_signal_conflict":
            signal_class = "source_signal_conflict"
        elif len(visit_sources[poi_id]) == 1:
            signal_class = "single_metadata"
        else:
            signal_class = "other_visit_signal_outcome"
        comparisons.append((master_result, visit_result, signal_class))

    def summarize(rows):
        pair_counts = Counter()
        master_status = Counter()
        visit_status = Counter()
        both_same_contentid = 0
        both_different_contentid = 0
        for master_result, visit_result, _signal_class in rows:
            master_status[master_result.status] += 1
            visit_status[visit_result.status] += 1
            pair_counts[f"Master_{master_result.status}_visit_{visit_result.status}"] += 1
            if master_result.status == visit_result.status == "MATCHED":
                if master_result.canonical_item_id == visit_result.canonical_item_id:
                    both_same_contentid += 1
                else:
                    both_different_contentid += 1
        both_matched = both_same_contentid + both_different_contentid
        pair_counts["both_MATCHED_same_contentid"] = both_same_contentid
        pair_counts["both_MATCHED_different_contentid"] = both_different_contentid
        required_pairs = (
            "Master_MATCHED_visit_MATCHED",
            "Master_MATCHED_visit_AMBIGUOUS", "Master_MATCHED_visit_UNMATCHED",
            "Master_AMBIGUOUS_visit_MATCHED", "Master_UNMATCHED_visit_MATCHED",
            "Master_AMBIGUOUS_visit_AMBIGUOUS", "Master_UNMATCHED_visit_UNMATCHED",
            "Master_AMBIGUOUS_visit_UNMATCHED", "Master_UNMATCHED_visit_AMBIGUOUS",
        )
        return {
            "positive_count": len(rows),
            "master_status_counts": {key: master_status[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")},
            "visit_status_counts": {key: visit_status[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")},
            "status_pair_counts": {key: pair_counts[key] for key in required_pairs},
            "both_MATCHED": both_matched,
            "both_MATCHED_same_contentid": both_same_contentid,
            "both_MATCHED_different_contentid": both_different_contentid,
            "canonical_contentid_agreement_rate_among_both_MATCHED": _rate(both_same_contentid, both_matched),
            "status_pair_rates": _rate_map(
                {key: pair_counts[key] for key in required_pairs}, len(rows)),
            "master_status_rates": _rate_map(
                {key: master_status[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")}, len(rows)),
            "visit_status_rates": _rate_map(
                {key: visit_status[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")}, len(rows)),
        }

    by_signal_class = {}
    for signal_class in ("single_metadata", "source_signal_conflict", "other_visit_signal_outcome"):
        by_signal_class[signal_class] = summarize([
            row for row in comparisons if row[2] == signal_class
        ])
    return {
        "scope": "positives_with_same_region_visit_and_master_metadata",
        "matching": "global_snapshot_same_exact_rule_as_D",
        "canonical_promotion": False,
        "overall": summarize(comparisons),
        "by_visit_signal_class": by_signal_class,
    }


def _aggregate_shadow_validations(entries):
    def aggregate(rows):
        positive_count = sum(row["positive_count"] for row in rows)
        master_status = Counter()
        visit_status = Counter()
        pair_counts = Counter()
        same = 0
        different = 0
        for row in rows:
            master_status.update(row["master_status_counts"])
            visit_status.update(row["visit_status_counts"])
            pair_counts.update(row["status_pair_counts"])
            same += row["both_MATCHED_same_contentid"]
            different += row["both_MATCHED_different_contentid"]
        both = same + different
        return {
            "positive_count": positive_count,
            "master_status_counts": dict(master_status),
            "visit_status_counts": dict(visit_status),
            "status_pair_counts": dict(pair_counts),
            "both_MATCHED": both,
            "both_MATCHED_same_contentid": same,
            "both_MATCHED_different_contentid": different,
            "canonical_contentid_agreement_rate_among_both_MATCHED": _rate(same, both),
            "status_pair_rates": _rate_map(dict(pair_counts), positive_count),
            "master_status_rates": _rate_map(dict(master_status), positive_count),
            "visit_status_rates": _rate_map(dict(visit_status), positive_count),
        }

    classes = ("single_metadata", "source_signal_conflict", "other_visit_signal_outcome")
    return {
        "scope": "positives_with_same_region_visit_and_master_metadata",
        "matching": "global_snapshot_same_exact_rule_as_D",
        "canonical_promotion": False,
        "overall": aggregate([entry["overall"] for entry in entries]),
        "by_visit_signal_class": {
            key: aggregate([entry["by_visit_signal_class"][key] for entry in entries])
            for key in classes
        },
    }


def _normalize_name_n1(value: str) -> str:
    """Diagnostic-only punctuation-insensitive key; never used by the matcher."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = "".join(" " if unicodedata.category(char).startswith("P") else char
                         for char in normalized)
    return " ".join(normalized.split())


def _parenthetical_variants(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value or "")
    stripped = PARENTHETICAL_PATTERN.sub(" ", normalized)
    variants = {normalize_text(normalized)}
    stripped_key = normalize_text(stripped)
    if stripped_key:
        variants.add(stripped_key)
    return {variant for variant in variants if variant}


def _char_bigrams(value: str) -> set[str]:
    text = normalize_text(value)
    if len(text) < 2:
        return {text} if text else set()
    return {text[index:index + 2] for index in range(len(text) - 1)}


def _name_recovery_indexes(catalog: list[CatalogPoi]):
    n1_index: dict[str, list[CatalogPoi]] = defaultdict(list)
    titles: dict[str, list[CatalogPoi]] = defaultdict(list)
    grams: dict[str, set[str]] = defaultdict(set)
    for item in catalog:
        if not item.title:
            continue
        n1_key = _normalize_name_n1(item.title)
        if n1_key:
            n1_index[n1_key].append(item)
        n0_key = normalize_text(item.title)
        if n0_key:
            titles[n0_key].append(item)
            for gram in _char_bigrams(n0_key):
                grams[gram].add(n0_key)
    return n1_index, titles, grams


def _candidate_ids(items):
    return {item.content_id for item in items if item.content_id}


def _exact_address_category(signals, candidate_items):
    addresses = {normalize_text(value) for signal in signals for value in (signal[2], signal[3]) if value}
    if not addresses:
        return "source_address_missing"
    if any(normalize_text(item.address) in addresses for item in candidate_items if item.address):
        return "exact_address_match"
    if candidate_items and all(not item.address for item in candidate_items):
        return "candidate_address_missing"
    return "address_mismatch"


def _diagnose_name_miss(signals, global_index, n1_index, title_index, gram_index):
    names = {signal[0] for signal in signals if signal[0] and normalize_text(signal[0])}
    if any(global_index.get(normalize_text(name), []) for name in names):
        return None

    n1_items = {}
    for name in names:
        key = _normalize_name_n1(name)
        for item in n1_index.get(key, []):
            if item.content_id:
                n1_items[item.content_id] = item

    n2_items = dict(n1_items)
    for name in names:
        for variant in _parenthetical_variants(name):
            for item in n1_index.get(_normalize_name_n1(variant), []):
                if item.content_id:
                    n2_items[item.content_id] = item
    n2_incremental = {key: item for key, item in n2_items.items() if key not in n1_items}

    fuzzy_items = {}
    for name in names:
        query = normalize_text(name)
        overlap = Counter()
        for gram in _char_bigrams(query):
            overlap.update(gram_index.get(gram, ()))
        candidate_titles = [title for title, _count in sorted(
            overlap.items(), key=lambda pair: (-pair[1], pair[0])
        )[:FUZZY_PREFILTER_LIMIT]]
        ranked = sorted(
            ((difflib.SequenceMatcher(None, query, title, autojunk=False).ratio(), title)
             for title in candidate_titles if title != query),
            key=lambda pair: (-pair[0], pair[1]),
        )[:FUZZY_TOP_N]
        for _score, title in ranked:
            for item in title_index.get(title, []):
                if item.content_id:
                    fuzzy_items[item.content_id] = item

    source_text = " ".join(names)
    tags = set()
    if n1_items:
        tags.add("punctuation_difference_candidate")
    if n2_incremental:
        tags.add("parenthetical_candidate")
    if BRANCH_PATTERN.search(source_text):
        tags.add("branch_suffix_present")
    if FACILITY_SUBPOI_PATTERN.search(source_text):
        tags.add("facility_subpoi_suffix_present")
    if NUMBER_TOKEN_PATTERN.search(source_text):
        tags.add("numeric_token_present")
    if LATIN_TOKEN_PATTERN.search(source_text):
        tags.add("latin_token_present")
    if not tags:
        tags.add("other")

    return {
        "n1_ids": set(n1_items),
        "n2_ids": set(n2_items),
        "n2_incremental_ids": set(n2_incremental),
        "n4_ids": set(fuzzy_items),
        "n1_address_category": _exact_address_category(signals, list(n1_items.values())) if n1_items else None,
        "n2_address_category": _exact_address_category(signals, list(n2_incremental.values())) if n2_incremental else None,
        "tags": tags,
    }


def _name_recovery_for_units(region, sources, poi_ids, global_index, n1_index, title_index, gram_index,
                             diagnostic_cache=None):
    diagnostic_cache = diagnostic_cache if diagnostic_cache is not None else {}
    per_poi = {}
    for poi_id in set(poi_ids):
        signals = sources.get(poi_id)
        if signals is None:
            continue
        if poi_id not in diagnostic_cache:
            diagnostic_cache[poi_id] = _diagnose_name_miss(
                signals, global_index, n1_index, title_index, gram_index)
        diagnosed = diagnostic_cache[poi_id]
        if diagnosed is not None:
            per_poi[poi_id] = diagnosed

    def summarize(ids):
        n0_miss = len(ids)
        candidate_counts = {stage: Counter() for stage in ("N0", "N1", "N2", "N4")}
        n1_address = Counter()
        n2_address = Counter()
        tags = Counter()
        for poi_id in ids:
            result = per_poi.get(poi_id)
            if result is None:
                continue
            candidate_counts["N0"]["0"] += 1
            for stage, key in (("N1", "n1_ids"), ("N2", "n2_ids"), ("N4", "n4_ids")):
                count = len(result[key])
                candidate_counts[stage]["0" if count == 0 else "1" if count == 1 else "2+"] += 1
            if result["n1_ids"]:
                n1_address[result["n1_address_category"]] += 1
            if result["n2_incremental_ids"]:
                n2_address[result["n2_address_category"]] += 1
            tags.update(result["tags"])
        expected_tags = ("punctuation_difference_candidate", "parenthetical_candidate",
                         "branch_suffix_present", "facility_subpoi_suffix_present",
                         "numeric_token_present", "latin_token_present", "other")
        for bucket in ("1", "2+"):
            candidate_counts["N0"][bucket] = 0
        return {
            "global_exact_title_absent_N0": n0_miss,
            "candidate_buckets_by_stage": {
                stage: {key: counts[key] for key in ("0", "1", "2+")}
                for stage, counts in candidate_counts.items()
            },
            "candidate_bucket_rates_by_stage": {
                stage: _rate_map({key: counts[key] for key in ("0", "1", "2+")}, n0_miss)
                for stage, counts in candidate_counts.items()
            },
            "N1_recovered_candidate_address": {
                "counts": {key: n1_address[key] for key in (
                    "exact_address_match", "address_mismatch", "source_address_missing", "candidate_address_missing")},
                "rates_among_N1_recovered": _rate_map(dict(n1_address), sum(n1_address.values())),
                "denominator": sum(n1_address.values()),
            },
            "N2_incremental_candidate_address": {
                "counts": {key: n2_address[key] for key in (
                    "exact_address_match", "address_mismatch", "source_address_missing", "candidate_address_missing")},
                "rates_among_N2_incremental": _rate_map(dict(n2_address), sum(n2_address.values())),
                "denominator": sum(n2_address.values()),
            },
            "diagnostic_tags_overlapping": {key: tags[key] for key in expected_tags},
            "diagnostic_tag_rates_overlapping": _rate_map(
                {key: tags[key] for key in expected_tags}, n0_miss),
        }

    unique_ids = sorted(per_poi)
    positive_ids = [poi_id for poi_id in poi_ids if poi_id in per_poi]
    return {
        "region": region,
        "unique_source_poi": summarize(unique_ids),
        "observed_positive": summarize(positive_ids),
    }


def _aggregate_name_recovery(aggregates):
    n0_total = sum(row["global_exact_title_absent_N0"] for row in aggregates)
    buckets = {stage: Counter() for stage in ("N0", "N1", "N2", "N4")}
    n1_address, n2_address, tags = Counter(), Counter(), Counter()
    for row in aggregates:
        for stage in buckets:
            buckets[stage].update(row["candidate_buckets_by_stage"][stage])
        n1_address.update(row["N1_recovered_candidate_address"]["counts"])
        n2_address.update(row["N2_incremental_candidate_address"]["counts"])
        tags.update(row["diagnostic_tags_overlapping"])
    expected_tags = ("punctuation_difference_candidate", "parenthetical_candidate",
                     "branch_suffix_present", "facility_subpoi_suffix_present",
                     "numeric_token_present", "latin_token_present", "other")

    def address_summary(counts):
        denominator = sum(counts.values())
        return {
            "counts": dict(counts), "denominator": denominator,
            "rates_among_recovered": _rate_map(dict(counts), denominator),
        }

    return {
        "global_exact_title_absent_N0": n0_total,
        "candidate_buckets_by_stage": {
            stage: {key: buckets[stage][key] for key in ("0", "1", "2+")}
            for stage in buckets
        },
        "candidate_bucket_rates_by_stage": {
            stage: _rate_map({key: buckets[stage][key] for key in ("0", "1", "2+")}, n0_total)
            for stage in buckets
        },
        "N1_recovered_candidate_address": address_summary(n1_address),
        "N2_incremental_candidate_address": address_summary(n2_address),
        "diagnostic_tags_overlapping": {key: tags[key] for key in expected_tags},
        "diagnostic_tag_rates_overlapping": _rate_map(
            {key: tags[key] for key in expected_tags}, n0_total),
    }


def _normalize_address_a1(value: str) -> str:
    """Conservative diagnostic-only normalization; preserves all address tokens."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = "".join(" " if unicodedata.category(char).startswith("P") else char
                         for char in normalized)
    return " ".join(normalized.split())


def _address_relation_a2(source_address: str, catalog_address: str) -> str:
    source = _normalize_address_a1(source_address)
    catalog = _normalize_address_a1(catalog_address)
    if not source:
        return "source_address_missing"
    if not catalog:
        return "catalog_address_missing"
    if source == catalog:
        return "normalized_exact"
    source_tokens, catalog_tokens = set(source.split()), set(catalog.split())
    if source_tokens <= catalog_tokens:
        return "source_tokens_subset_of_catalog"
    if catalog_tokens <= source_tokens:
        return "catalog_tokens_subset_of_source"
    if source_tokens & catalog_tokens:
        return "partial_overlap"
    return "no_meaningful_overlap"


def _strongest_address_relation_a2(source_addresses, catalog_addresses):
    relations = [_address_relation_a2(source, catalog)
                 for source in source_addresses for catalog in catalog_addresses]
    if not source_addresses:
        return "source_address_missing"
    if not catalog_addresses or all(not _normalize_address_a1(address) for address in catalog_addresses):
        return "catalog_address_missing"
    priority = (
        "normalized_exact", "source_tokens_subset_of_catalog", "catalog_tokens_subset_of_source",
        "partial_overlap", "no_meaningful_overlap",
    )
    return next((relation for relation in priority if relation in relations), "catalog_address_missing")


def _address_resolution_shadow(region, sources, positives, global_index, admin_codes):
    """Describe why Arm D ambiguous positives remain unresolved; never alters identity."""
    buckets = ("0", "1", "2+")
    ambiguous = []
    for _trip_id, poi_id in positives:
        signals = sources.get(poi_id)
        if not signals:
            continue
        names = {normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])}
        candidates_by_id = {item.content_id: item for name in names
                            for item in global_index.get(name, [])}
        candidates = list(candidates_by_id.values())
        result = _resolve_one(poi_id, signals, region, candidates, admin_codes, global_scope=True)
        if result.status != "AMBIGUOUS":
            continue
        title_count = len(candidates)
        title_bucket = "0" if title_count == 0 else "1" if title_count == 1 else "2+"
        source_addresses = {normalize_text(value) for signal in signals for value in (signal[2], signal[3])
                            if normalize_text(value)}
        source_address_values = [value for signal in signals for value in (signal[2], signal[3])
                                 if _normalize_address_a1(value)]
        catalog_address_count = sum(bool(normalize_text(item.address)) for item in candidates)
        catalog_addresses = {normalize_text(item.address) for item in candidates if normalize_text(item.address)}
        exact_address_ids = {item.content_id for item in candidates
                             if normalize_text(item.address) and normalize_text(item.address) in source_addresses}
        address_bucket = ("0" if not exact_address_ids else "1" if len(exact_address_ids) == 1 else "2+")
        if not source_addresses:
            address_outcome = "source_address_missing"
        elif not catalog_addresses:
            address_outcome = "catalog_address_missing"
        elif not exact_address_ids:
            address_outcome = "address_mismatch"
        elif len(exact_address_ids) == 1:
            address_outcome = "one_exact_address_candidate"
        else:
            address_outcome = "multiple_exact_address_candidates"
        if len(signals) > 1:
            address_presence = "multiple_source_signals"
        else:
            _name, _sgg, lot, road = next(iter(signals))
            has_road, has_lot = bool(normalize_text(road)), bool(normalize_text(lot))
            address_presence = ("road_and_lot" if has_road and has_lot else "road_only" if has_road else
                                "lot_only" if has_lot else "none")
        catalog_address_presence = ("none" if not catalog_address_count else
                                    "all" if catalog_address_count == len(candidates) else "some")
        a1_source_keys = {_normalize_address_a1(value) for value in source_address_values}
        a1_catalog_by_id = {item.content_id: _normalize_address_a1(item.address) for item in candidates}
        a1_selected_ids = {content_id for content_id, address in a1_catalog_by_id.items()
                           if address and address in a1_source_keys}
        if title_bucket == "1":
            if not source_address_values:
                a1_outcome = "source_missing"
            elif not any(a1_catalog_by_id.values()):
                a1_outcome = "catalog_address_missing"
            elif a1_selected_ids:
                a1_outcome = "normalized_exact"
            else:
                a1_outcome = "still_mismatch"
            a1_source_missing = not source_address_values
            a1_selected_bucket = "0" if not a1_selected_ids else "1"
            a2_unresolved = a1_outcome != "normalized_exact"
        else:
            if len(a1_selected_ids) == 1:
                a1_outcome = "exactly_one_candidate_selected"
            elif len(a1_selected_ids) > 1:
                a1_outcome = "multiple_candidates_selected"
            else:
                a1_outcome = "no_candidate_selected"
            a1_source_missing = not source_address_values
            a1_selected_bucket = ("0" if not a1_selected_ids else "1" if len(a1_selected_ids) == 1 else "2+")
            a2_unresolved = a1_outcome != "exactly_one_candidate_selected"
        a2_relation = (_strongest_address_relation_a2(
            source_address_values, [item.address for item in candidates]) if a2_unresolved else None)
        ambiguous.append((title_bucket, result.method or "no_method", address_presence,
                          catalog_address_presence, address_bucket, address_outcome,
                          a1_outcome, a1_source_missing, a1_selected_bucket, a2_relation))

    def summarize(rows):
        methods = Counter(row[1] for row in rows)
        title_counts = Counter(row[0] for row in rows)
        address_presence = Counter(row[2] for row in rows)
        catalog_presence = Counter(row[3] for row in rows)
        address_buckets = Counter(row[4] for row in rows)
        outcomes = Counter(row[5] for row in rows)
        a1_outcomes = Counter((row[0], row[6]) for row in rows)
        a1_missing = Counter(row[0] for row in rows if row[7])
        a1_selected = Counter((row[0], row[8]) for row in rows)
        a2_relations = Counter(row[9] for row in rows if row[9])
        a2_denominator = sum(a2_relations.values())
        denominator = len(rows)
        return {
            "ambiguous_positive_count": denominator,
            "exact_title_candidate_counts_0_1_2plus": {key: title_counts[key] for key in buckets},
            "exact_title_candidate_rates": _rate_map({key: title_counts[key] for key in buckets}, denominator),
            "ambiguous_match_method_counts": dict(methods),
            "source_address_presence_counts": dict(address_presence),
            "catalog_candidate_address_presence_counts": dict(catalog_presence),
            "exact_address_candidate_counts_0_1_2plus": {key: address_buckets[key] for key in buckets},
            "address_resolution_outcome_counts": dict(outcomes),
            "address_resolution_outcome_rates": _rate_map(dict(outcomes), denominator),
            "A1_outcome_counts_by_exact_title_candidate_count": {
                bucket: {outcome: a1_outcomes[(bucket, outcome)] for outcome in (
                    ("normalized_exact", "still_mismatch", "source_missing", "catalog_address_missing")
                    if bucket == "1" else
                    ("exactly_one_candidate_selected", "multiple_candidates_selected", "no_candidate_selected"))}
                for bucket in ("1", "2+")
            },
            "A1_outcome_rates_by_exact_title_candidate_count": {
                bucket: _rate_map(
                    {outcome: a1_outcomes[(bucket, outcome)] for outcome in (
                        ("normalized_exact", "still_mismatch", "source_missing", "catalog_address_missing")
                        if bucket == "1" else
                        ("exactly_one_candidate_selected", "multiple_candidates_selected", "no_candidate_selected"))},
                    sum(1 for row in rows if row[0] == bucket))
                for bucket in ("1", "2+")
            },
            "A1_selected_candidate_counts_by_exact_title_candidate_count": {
                bucket: {selected: a1_selected[(bucket, selected)] for selected in ("0", "1", "2+")}
                for bucket in ("1", "2+")
            },
            "A1_selected_candidate_rates_by_exact_title_candidate_count": {
                bucket: _rate_map(
                    {selected: a1_selected[(bucket, selected)] for selected in ("0", "1", "2+")},
                    sum(1 for row in rows if row[0] == bucket))
                for bucket in ("1", "2+")
            },
            "A1_source_address_missing_by_exact_title_candidate_count": {
                bucket: a1_missing[bucket] for bucket in ("1", "2+")
            },
            "A2_denominator_unresolved_after_A1": a2_denominator,
            "A2_address_relationship_counts": {key: a2_relations[key] for key in (
                "normalized_exact", "source_tokens_subset_of_catalog", "catalog_tokens_subset_of_source",
                "partial_overlap", "no_meaningful_overlap", "source_address_missing", "catalog_address_missing")},
            "A2_address_relationship_rates": _rate_map(
                {key: a2_relations[key] for key in (
                    "normalized_exact", "source_tokens_subset_of_catalog", "catalog_tokens_subset_of_source",
                    "partial_overlap", "no_meaningful_overlap", "source_address_missing", "catalog_address_missing")},
                a2_denominator),
        }

    by_title_count = {}
    for bucket in buckets:
        by_title_count[bucket] = summarize([row for row in ambiguous if row[0] == bucket])
    return {"region": region, "overall": summarize(ambiguous), "by_exact_title_candidate_count": by_title_count}


def _aggregate_address_resolution_shadow(entries):
    grouped = defaultdict(list)
    for entry in entries:
        grouped["overall"].append(entry["overall"])
        for bucket, row in entry["by_exact_title_candidate_count"].items():
            grouped[bucket].append(row)

    def aggregate(rows):
        methods, source_address, catalog_address, address_buckets, outcomes = (
            Counter(), Counter(), Counter(), Counter(), Counter())
        a1_outcomes = {bucket: Counter() for bucket in ("1", "2+")}
        a1_selected = {bucket: Counter() for bucket in ("1", "2+")}
        a1_missing = Counter()
        a2_relations = Counter()
        for row in rows:
            methods.update(row["ambiguous_match_method_counts"])
            source_address.update(row["source_address_presence_counts"])
            catalog_address.update(row["catalog_candidate_address_presence_counts"])
            address_buckets.update(row["exact_address_candidate_counts_0_1_2plus"])
            outcomes.update(row["address_resolution_outcome_counts"])
            for bucket in ("1", "2+"):
                a1_outcomes[bucket].update(row["A1_outcome_counts_by_exact_title_candidate_count"][bucket])
                a1_selected[bucket].update(row["A1_selected_candidate_counts_by_exact_title_candidate_count"][bucket])
                a1_missing[bucket] += row["A1_source_address_missing_by_exact_title_candidate_count"][bucket]
            a2_relations.update(row["A2_address_relationship_counts"])
        denominator = sum(row["ambiguous_positive_count"] for row in rows)
        a2_denominator = sum(row["A2_denominator_unresolved_after_A1"] for row in rows)
        a2_keys = (
            "normalized_exact", "source_tokens_subset_of_catalog", "catalog_tokens_subset_of_source",
            "partial_overlap", "no_meaningful_overlap", "source_address_missing", "catalog_address_missing",
        )
        return {
            "ambiguous_positive_count": denominator,
            "ambiguous_match_method_counts": dict(methods),
            "source_address_presence_counts": dict(source_address),
            "catalog_candidate_address_presence_counts": dict(catalog_address),
            "exact_address_candidate_counts_0_1_2plus": {key: address_buckets[key] for key in ("0", "1", "2+")},
            "address_resolution_outcome_counts": dict(outcomes),
            "address_resolution_outcome_rates": _rate_map(dict(outcomes), denominator),
            "A1_outcome_counts_by_exact_title_candidate_count": {
                bucket: {outcome: a1_outcomes[bucket][outcome] for outcome in (
                    ("normalized_exact", "still_mismatch", "source_missing", "catalog_address_missing")
                    if bucket == "1" else
                    ("exactly_one_candidate_selected", "multiple_candidates_selected", "no_candidate_selected"))}
                for bucket in ("1", "2+")
            },
            "A1_outcome_rates_by_exact_title_candidate_count": {
                bucket: _rate_map(
                    {outcome: a1_outcomes[bucket][outcome] for outcome in (
                        ("normalized_exact", "still_mismatch", "source_missing", "catalog_address_missing")
                        if bucket == "1" else
                        ("exactly_one_candidate_selected", "multiple_candidates_selected", "no_candidate_selected"))},
                    sum(row["exact_title_candidate_counts_0_1_2plus"][bucket] for row in rows))
                for bucket in ("1", "2+")
            },
            "A1_selected_candidate_counts_by_exact_title_candidate_count": {
                bucket: {selected: a1_selected[bucket][selected] for selected in ("0", "1", "2+")}
                for bucket in ("1", "2+")
            },
            "A1_selected_candidate_rates_by_exact_title_candidate_count": {
                bucket: _rate_map(
                    {selected: a1_selected[bucket][selected] for selected in ("0", "1", "2+")},
                    sum(row["exact_title_candidate_counts_0_1_2plus"][bucket] for row in rows))
                for bucket in ("1", "2+")
            },
            "A1_source_address_missing_by_exact_title_candidate_count": dict(a1_missing),
            "A2_denominator_unresolved_after_A1": a2_denominator,
            "A2_address_relationship_counts": {key: a2_relations[key] for key in a2_keys},
            "A2_address_relationship_rates": _rate_map(
                {key: a2_relations[key] for key in a2_keys}, a2_denominator),
        }

    by_title = {key: aggregate(grouped[key]) for key in ("0", "1", "2+")}
    total = sum(by_title[key]["ambiguous_positive_count"] for key in ("0", "1", "2+"))
    return {
        "overall": aggregate(grouped["overall"]),
        "exact_title_candidate_counts_0_1_2plus": {
            key: by_title[key]["ambiguous_positive_count"] for key in ("0", "1", "2+")
        },
        "exact_title_candidate_rates": _rate_map(
            {key: by_title[key]["ambiguous_positive_count"] for key in ("0", "1", "2+")}, total),
        "by_exact_title_candidate_count": by_title,
    }


def _master_rows(root: Path) -> dict[str, set[tuple[str, str, str, str]]]:
    files = [p for p in shared.csv_files(root) if "POI_MASTER" in p.name.upper()]
    if len(files) != 1:
        raise ValueError("each region must contain exactly one TN_POI_MASTER CSV")
    grouped: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    for row in shared._rows(files, set(FIELDS) | {"POI_ID"}, set(FIELDS) | {"POI_ID"}):
        poi_id = (row.get("poi_id") or "").strip()
        if poi_id:
            grouped[poi_id].add(tuple(row.get(field.lower()) or "" for field in FIELDS))
    return dict(grouped)


def _catalog_index(catalog: list[CatalogPoi], policy):
    all_codes = frozenset(code for codes in policy.product_region_to_ldong_regn_cd.values()
                          for code in codes)
    regional: dict[tuple[str, str], list[CatalogPoi]] = defaultdict(list)
    global_index: dict[str, list[CatalogPoi]] = defaultdict(list)
    admin = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    for item in catalog:
        if item.title:
            global_index[normalize_text(item.title)].append(item)
            for region, codes in admin.items():
                if codes.intersection(item.region_codes):
                    regional[(region, normalize_text(item.title))].append(item)
    return regional, global_index, all_codes


def _resolve_one(poi_id: str, signals: set[tuple[str, str, str, str]], region: str,
                 candidate_items: list[CatalogPoi], admin_codes, global_scope=False) -> MatchResult:
    if len(signals) != 1:
        return MatchResult(poi_id, "AMBIGUOUS", None, "source_signal_conflict", len(signals))
    name, _sgg, lot, road = next(iter(signals))
    # SGG_CD remains diagnostic-only because its crosswalk is not verified.
    addresses = list(dict.fromkeys(value for value in (lot, road) if value)) or [""]
    matches = [match_source_item(
        SourcePoi(poi_id, region, name=name, address=address), candidate_items,
        source_region_to_admin_codes=admin_codes,
        global_identity_scope=global_scope,
    ) for address in addresses]
    exact = [result for result in matches if result.status == "MATCHED"]
    ambiguous = [result for result in matches if result.status == "AMBIGUOUS"]
    ids = {result.canonical_item_id for result in exact}
    if any(result.method in {"conflicting_exact_signals", "name_address"} for result in ambiguous) or len(ids) > 1:
        return MatchResult(poi_id, "AMBIGUOUS", None, "conflicting_source_address_signals", max(2, len(ids)))
    if exact:
        methods = {result.method for result in exact}
        return MatchResult(poi_id, "MATCHED", next(iter(ids)),
                           next(iter(methods)) if len(methods) == 1 else "name_address", 1)
    return matches[0]


def _master_visit_diagnostics(visits, masters):
    counts = Counter()
    ids = set(visits) | set(masters)
    for poi_id in ids:
        visit_rows = visits.get(poi_id, set())
        master_rows = masters.get(poi_id, set())
        counts["visit_poi_ids"] += bool(visit_rows)
        counts["master_missing"] += bool(visit_rows and not master_rows)
        counts["master_exists_stable"] += bool(master_rows and len(master_rows) == 1)
        counts["visit_internally_inconsistent"] += bool(len(visit_rows) > 1)
        if not visit_rows or not master_rows:
            continue
        # Aggregate any visit/master signal disagreements by field; no values escape.
        for index, label in enumerate(("name_differs", "sgg_differs", "lot_address_differs", "road_address_differs")):
            if any(v[index] != m[index] for v in visit_rows for m in master_rows):
                counts[label] += 1
        if len(visit_rows) > 1 and len(master_rows) == 1:
            counts["visit_conflict_stabilized_by_master"] += 1
    output = dict(counts)
    denominator = output.get("visit_poi_ids", 0)
    output["rates_per_visit_poi_id"] = {
        key: _rate(value, denominator) for key, value in sorted(output.items())
        if key != "visit_poi_ids"
    }
    stable_denominator = output.get("master_exists_stable", 0)
    field_keys = ("name_differs", "sgg_differs", "lot_address_differs", "road_address_differs")
    output["field_mismatch_rates_per_master_stable_poi"] = {
        key: _rate(output.get(key, 0), stable_denominator) for key in field_keys
    }
    conflict_denominator = output.get("visit_internally_inconsistent", 0)
    output["conflict_stabilization_rate"] = _rate(
        output.get("visit_conflict_stabilized_by_master", 0), conflict_denominator
    )
    return output


def _cross_region_master_diagnostic(source_poi_ids, positives, region, masters_by_region):
    """Classify same-region Master misses using other regional Masters, without resolving identity."""
    local = masters_by_region[region]
    def classify(poi_id):
        if poi_id in local:
            return None
        other = [(other_region, masters_by_region[other_region][poi_id])
                 for other_region in REGIONS if other_region != region
                 and poi_id in masters_by_region[other_region]]
        if not other:
            return "absent_from_all_masters"
        if len(other) == 1:
            return "found_in_one_other_master"
        metadata = {signal for _, signals in other for signal in signals}
        return ("found_in_multiple_masters_same_metadata" if len(metadata) == 1
                else "found_in_multiple_masters_conflicting_metadata")

    categories = ("absent_from_all_masters", "found_in_one_other_master",
                  "found_in_multiple_masters_same_metadata",
                  "found_in_multiple_masters_conflicting_metadata")
    source_missing = {poi_id for poi_id in source_poi_ids if poi_id not in local}
    positive_missing = [poi_id for _, poi_id in positives if poi_id not in local]
    source_counts = Counter(classify(poi_id) for poi_id in source_missing)
    positive_counts = Counter(classify(poi_id) for poi_id in positive_missing)
    return {
        "same_region_master_present_source_poi_count": len(set(source_poi_ids) - source_missing),
        "source_poi": {"missing_in_same_region_master": len(source_missing),
                       "categories": {key: source_counts[key] for key in categories},
                       "category_rates": _rate_map({key: source_counts[key] for key in categories}, len(source_missing))},
        "observed_positive": {"missing_in_same_region_master": len(positive_missing),
                              "categories": {key: positive_counts[key] for key in categories},
                              "category_rates": _rate_map({key: positive_counts[key] for key in categories}, len(positive_missing))},
    }


def _arm_counts(region, role, sources, positives, catalog, regional_index, global_index,
                all_codes, policy, arm, provenance_by_id=None):
    scope, metadata = ARM_SCOPE[arm], ARM_META[arm]
    admin = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    supported = frozenset(policy.supported_content_type_ids)
    matches = {}
    title_buckets = Counter()
    title_diag = Counter()
    for poi_id, signals in sources.items():
        if metadata == "master" and not signals:
            matches[poi_id] = MatchResult(poi_id, "UNMATCHED", None, "master_missing", 0)
            continue
        names = sorted({normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])})
        global_by_id = {item.content_id: item for name in names for item in global_index.get(name, [])}
        regional_by_id = {item.content_id: item for name in names
                          for item in regional_index.get((region, name), [])}
        global_candidates = list(global_by_id.values())
        regional_candidates = list(regional_by_id.values())
        lookup = global_candidates if scope == "global" else regional_candidates
        bucket = "0" if len(lookup) == 0 else "1" if len(lookup) == 1 else "2+"
        title_buckets[bucket] += 1
        if not regional_candidates:
            title_diag[{0: "global_exact_title_absent", 1: "exact_title_exists_outside_source_region_single"}.get(
                len(global_candidates), "exact_title_exists_outside_source_region_multiple")] += 1
        matches[poi_id] = _resolve_one(poi_id, signals, region, lookup, admin,
                                       global_scope=scope == "global")
    catalog_by_id = {item.content_id: item for item in catalog}
    eligible_ids = {item.content_id for item in catalog
                    if eligibility_reason(item, request_region=region,
                                          region_admin_codes=admin,
                                          supported_content_types=supported) == "eligible"
                    and item.content_id and item.title.strip()}
    positive_status = Counter()
    methods = Counter()
    contained = 0
    ineligible = Counter()
    positive_title_buckets = Counter()
    positive_global_diagnostic = Counter()
    identity_source_available = 0
    identity_source_missing = 0
    title_diagnostic_positive_denominator = 0
    provenance_positive = Counter()
    fallback_status = Counter()
    fallback_title_buckets = Counter()
    fallback_contained = 0
    fallback_eligibility = Counter()
    for _trip, poi_id in positives:
        provenance = (provenance_by_id or {}).get(poi_id)
        if arm == "E":
            provenance_positive[provenance or "identity_source_missing"] += 1
            source_available = provenance in {"master", "visit_fallback"}
        else:
            source_available = metadata != "master" or bool(sources.get(poi_id))
        if source_available:
            identity_source_available += 1
            title_diagnostic_positive_denominator += 1
        else:
            identity_source_missing += 1
        result = matches.get(poi_id, MatchResult(poi_id, "UNMATCHED", None, "master_missing", 0))
        signals = sources.get(poi_id, set())
        if not source_available:
            continue
        names = sorted({normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])})
        global_count = len({item.content_id for name in names for item in global_index.get(name, [])})
        regional_count = len({item.content_id for name in names
                              for item in regional_index.get((region, name), [])})
        selected_count = global_count if scope == "global" else regional_count
        title_bucket = "0" if selected_count == 0 else "1" if selected_count == 1 else "2+"
        positive_title_buckets[title_bucket] += 1
        if arm == "E" and provenance == "visit_fallback":
            fallback_title_buckets[title_bucket] += 1
        if regional_count == 0:
            positive_global_diagnostic["global_exact_title_absent" if global_count == 0 else
                                       "exact_title_exists_outside_source_region_single" if global_count == 1 else
                                       "exact_title_exists_outside_source_region_multiple"] += 1
        positive_status[result.status] += 1
        methods[result.method or "no_exact_signal"] += 1
        if arm == "E" and provenance == "visit_fallback":
            fallback_status[result.status] += 1
        if result.status == "MATCHED" and result.canonical_item_id:
            item = catalog_by_id[result.canonical_item_id]
            reason = eligibility_reason(item, request_region=region,
                                       region_admin_codes=admin,
                                       supported_content_types=supported)
            if not item.content_id or not item.title.strip():
                reason = "required_field_invalid"
            ineligible[reason] += 1
            if result.canonical_item_id in eligible_ids:
                contained += 1
                if arm == "E" and provenance == "visit_fallback":
                    fallback_contained += 1
            if arm == "E" and provenance == "visit_fallback":
                fallback_eligibility[reason] += 1
    total = len(positives)
    resolved = positive_status["MATCHED"]
    fallback_total = sum(fallback_status.values())
    fallback_resolved = fallback_status["MATCHED"]
    return {
        "arm": arm, "metadata": metadata, "identity_scope": scope,
        "all_positives": total, "MATCHED": positive_status["MATCHED"],
        "AMBIGUOUS": positive_status["AMBIGUOUS"], "UNMATCHED": positive_status["UNMATCHED"],
        "identity_resolution_rate": _rate(resolved, total),
        "identity_source_available": identity_source_available,
        "identity_source_missing": identity_source_missing,
        "identity_resolution_rate_all": _rate(resolved, total),
        "identity_resolution_rate_source_available": _rate(resolved, identity_source_available),
        "candidate_title_count_0_1_2plus_by_source_poi": dict(title_buckets),
        "candidate_title_count_source_poi_denominator": sum(title_buckets.values()),
        "candidate_title_count_0_1_2plus_by_positive": dict(positive_title_buckets),
        "candidate_title_count_positive_denominator": title_diagnostic_positive_denominator,
        "positives_with_identity_source": title_diagnostic_positive_denominator,
        "candidate_title_count_positive_rates": _rate_map(dict(positive_title_buckets), title_diagnostic_positive_denominator),
        "global_exact_title_diagnostic_by_positive": dict(positive_global_diagnostic),
        "global_exact_title_diagnostic_positive_denominator": title_diagnostic_positive_denominator,
        "global_exact_title_diagnostic_positive_rates": _rate_map(
            dict(positive_global_diagnostic), title_diagnostic_positive_denominator),
        "positive_match_methods": dict(methods), "identity_source_missing": identity_source_missing,
        "identity_metadata_source_by_positive": dict(provenance_positive),
        "identity_metadata_source_by_source_poi": dict(Counter(
            (provenance_by_id or {}).get(poi_id, "master") for poi_id in sources
        )) if arm == "E" else {},
        "visit_fallback_subset": ({
            "all_positives": fallback_total,
            "MATCHED": fallback_status["MATCHED"],
            "AMBIGUOUS": fallback_status["AMBIGUOUS"],
            "UNMATCHED": fallback_status["UNMATCHED"],
            "identity_resolution_rate": _rate(fallback_resolved, fallback_total),
            "exact_title_candidate_count_0_1_2plus": dict(fallback_title_buckets),
            "exact_title_candidate_denominator": sum(fallback_title_buckets.values()),
            "exact_title_candidate_rates": _rate_map(dict(fallback_title_buckets), sum(fallback_title_buckets.values())),
            "candidate_contained": fallback_contained,
            "matched_eligibility_reasons": dict(fallback_eligibility),
            "matched_eligibility_reason_rates": _rate_map(dict(fallback_eligibility), fallback_resolved),
        } if arm == "E" else {}),
        "positive_match_method_rates": _rate_map(
            dict(methods), identity_source_available if metadata == "master" else len(positives)),
        "candidate_contained": contained, "outside_candidate": resolved - contained,
        "end_to_end_coverage": _rate(contained, total),
        "conditional_coverage": _rate(contained, resolved),
        "matched_eligibility_reasons": dict(ineligible),
        "matched_eligibility_reason_rates": _rate_map(dict(ineligible), resolved),
        "global_exact_title_diagnostic_among_same_region_no_hit": dict(title_diag),
    }


def _rate(n, d):
    return {"count": n, "denominator": d, "percent": round(n * 100 / d, 2) if d else None}


def _rate_map(counts: dict[str, int], denominator: int) -> dict[str, dict[str, int | float | None]]:
    return {key: _rate(value, denominator) for key, value in sorted(counts.items())}


def run(specs, masters_by_region, snapshot_path, policy_path, output_path):
    policy = load_poi_catalog_policy(policy_path)
    metadata = json.loads(snapshot_path.with_suffix(snapshot_path.suffix + ".metadata.json").read_text(encoding="utf-8"))
    if metadata.get("provider") != "tourapi-korservice2" or metadata.get("manual_version") != "4.4":
        raise ValueError("fixed snapshot provider contract mismatch")
    expected_codes = set().union(*policy.product_region_to_ldong_regn_cd.values())
    request_config = metadata.get("request_config", {})
    if set(request_config.get("region_codes", [])) != expected_codes:
        raise ValueError("fixed snapshot legal-code universe differs from current policy")
    if set(metadata.get("supported_content_type_ids_v1", [])) != set(policy.supported_content_type_ids):
        raise ValueError("fixed snapshot supported content types differ from current policy")
    catalog = list(read_tourapi_snapshot_csv(
        snapshot_path, snapshot_version=str(metadata.get("snapshot_version", "")),
        fields=TourApiFieldMap(), retrieved_at=str(metadata.get("retrieved_at_utc", "")),
        request_config_hash=str(metadata.get("request_config", {}).get("request_config_hash", "")),
        policy_version=policy.version).records)
    snapshot_fields = ("contentid", "contenttypeid", "title", "addr1", "lDongRegnCd",
                       "lDongSignguCd", "lclsSystm1", "lclsSystm2", "lclsSystm3", "modifiedtime")
    with snapshot_path.open("r", encoding="utf-8-sig", newline="") as stream:
        canonical_rows = [{key: (row.get(key) or "") for key in snapshot_fields}
                          for row in csv.DictReader(stream)]
    canonical_rows.sort(key=lambda row: row["contentid"])
    snapshot_fingerprint = hashlib.sha256(json.dumps(
        canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    if snapshot_fingerprint != metadata.get("snapshot_sha256"):
        raise ValueError("fixed snapshot canonical content fingerprint mismatch")
    regional_index, global_index, all_codes = _catalog_index(catalog, policy)
    n1_index, n1_title_index, fuzzy_gram_index = _name_recovery_indexes(catalog)
    out = {"snapshot_item_count": len(catalog), "snapshot_coordinate_fields": [],
           "snapshot_policy_fingerprint_matches_current_config": metadata.get("policy_config_sha256") == policy.policy_sha256,
           "snapshot_policy_sha256": metadata.get("policy_config_sha256"),
           "snapshot_policy_fingerprint_note": "mismatch; current versioned policy applied after verifying canonical snapshot SHA-256, provider, legal-code universe, and supported types",
           "current_policy_sha256": policy.policy_sha256,
           "coordinate_diagnostic": "not_estimable_fixed_snapshot_has_no_mapx_mapy; coordinates_for_identity=false",
           "by_region_split_arm": [], "master_visit_metadata": {},
           "cross_region_master_lookup": [],
           "master_visit_identity_shadow_validation": [],
           "name_candidate_recovery_by_region_split_positive": [],
           "name_candidate_recovery_by_region_unique_source_poi": [],
           "address_resolution_shadow_by_region_split": [],
           "address_resolution_shadow_by_region_unique_source_poi": [],
           "weighted_TL_VL": {}, "methodology": "controlled_pipeline_comparison_not_causal_effect",
           "canonical_identity_arm": CANONICAL_IDENTITY_ARM,
           "manifest": {"dataset": "AI Hub Domestic Travel Log 2023", "splits": ["TL", "VL"],
                        "provider": metadata.get("provider"), "manual_version": metadata.get("manual_version"),
                        "snapshot_version": metadata.get("snapshot_version"),
                        "snapshot_sha256": metadata.get("snapshot_sha256"),
                        "retrieved_at_utc": metadata.get("retrieved_at_utc"),
                        "request_config_hash": metadata.get("request_config", {}).get("request_config_hash"),
                        "policy_sha256_applied": policy.policy_sha256,
                        "raw_rows_ids_paths_coordinates_emitted": False,
                        "coordinates_for_identity": False}}
    for region in REGIONS:
        visit_all: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
        master_all: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
        region_positive_ids = set()
        recovery_cache = {}
        for role in ROLES:
            spec = next(s for s in specs if s.region == region and s.role == role)
            visits, positives, _ = _source_rows(spec)
            master = masters_by_region[region]
            region_positive_ids.update(poi_id for _, poi_id in positives)
            out["cross_region_master_lookup"].append({
                "region": region, "split": role,
                **_cross_region_master_diagnostic(set(visits), positives, region, masters_by_region),
            })
            visit_master = {poi_id: master[poi_id] for poi_id in visits.keys() & master.keys()}
            out["master_visit_metadata"][f"{region}:{role}"] = _master_visit_diagnostics(visits, visit_master)
            shadow_validation = _compare_master_visit_identity(
                region, positives, visits, master, global_index, policy)
            out["master_visit_identity_shadow_validation"].append({
                "region": region, "split": role, **shadow_validation,
            })
            recovery = _name_recovery_for_units(
                region, master, [poi_id for _, poi_id in positives], global_index,
                n1_index, n1_title_index, fuzzy_gram_index, recovery_cache)
            out["name_candidate_recovery_by_region_split_positive"].append({
                "region": region, "split": role, **recovery["observed_positive"],
            })
            address_shadow = _address_resolution_shadow(
                region, master, positives, global_index,
                {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()})
            out["address_resolution_shadow_by_region_split"].append({
                "region": region, "split": role, **address_shadow,
            })
            for poi_id, signals in visits.items():
                visit_all[poi_id].update(signals)
            for poi_id, signals in visit_master.items():
                master_all[poi_id].update(signals)
            for arm in "ABCDE":
                provenance = None
                if ARM_META[arm] == "visit":
                    source_map = visits
                else:
                    positive_ids = {poi_id for _, poi_id in positives}
                    if arm == "E":
                        source_map, provenance = _arm_e_sources(master, visits, positive_ids)
                    else:
                        source_map = {poi_id: master[poi_id] for poi_id in positive_ids if poi_id in master}
                row = _arm_counts(region, role, source_map, positives, catalog,
                                  regional_index, global_index, all_codes, policy, arm, provenance)
                row["region"], row["split"] = region, role
                out["by_region_split_arm"].append(row)
        out["master_visit_metadata"][region + ":unique_poi_id"] = _master_visit_diagnostics(visit_all, master_all)
        unique_recovery = _name_recovery_for_units(
            region, masters_by_region[region], region_positive_ids, global_index,
            n1_index, n1_title_index, fuzzy_gram_index, recovery_cache)
        out["name_candidate_recovery_by_region_unique_source_poi"].append({
            "region": region, **unique_recovery["unique_source_poi"],
        })
        unique_address_shadow = _address_resolution_shadow(
            region, masters_by_region[region],
            [("", poi_id) for poi_id in sorted(region_positive_ids)], global_index,
            {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()})
        out["address_resolution_shadow_by_region_unique_source_poi"].append({
            "region": region, **unique_address_shadow,
        })
    for arm in "ABCDE":
        totals = Counter()
        for row in out["by_region_split_arm"]:
            if row["arm"] == arm:
                for key in ("all_positives", "MATCHED", "AMBIGUOUS", "UNMATCHED", "candidate_contained", "outside_candidate",
                            "identity_source_available", "identity_source_missing", "positives_with_identity_source"):
                    totals[key] += row[key]
                if arm == "E":
                    totals.setdefault("identity_metadata_source_by_positive", Counter()).update(
                        row["identity_metadata_source_by_positive"])
                    totals.setdefault("identity_metadata_source_by_source_poi", Counter()).update(
                        row["identity_metadata_source_by_source_poi"])
                    fallback = totals.setdefault("visit_fallback_subset", Counter())
                    subset = row["visit_fallback_subset"]
                    for key in ("all_positives", "MATCHED", "AMBIGUOUS", "UNMATCHED", "candidate_contained"):
                        fallback[key] += subset[key]
                    for key in ("exact_title_candidate_count_0_1_2plus", "matched_eligibility_reasons"):
                        fallback.setdefault(key, Counter()).update(subset[key])
        totals["identity_resolution_rate"] = _rate(totals["MATCHED"], totals["all_positives"])
        totals["identity_resolution_rate_all"] = _rate(totals["MATCHED"], totals["all_positives"])
        totals["identity_resolution_status_rates"] = _rate_map(
            {key: totals[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")},
            totals["all_positives"])
        totals["identity_resolution_rate_source_available"] = _rate(
            totals["MATCHED"], totals["identity_source_available"] or totals["all_positives"])
        totals["end_to_end_coverage"] = _rate(totals["candidate_contained"], totals["all_positives"])
        totals["conditional_coverage"] = _rate(totals["candidate_contained"], totals["MATCHED"])
        for metric in ("candidate_title_count_0_1_2plus_by_positive", "positive_match_methods",
                       "matched_eligibility_reasons", "global_exact_title_diagnostic_by_positive"):
            aggregate = Counter()
            for row in out["by_region_split_arm"]:
                if row["arm"] == arm:
                    aggregate.update(row.get(metric, {}))
            totals[metric] = dict(aggregate)
            denominator = (totals["positives_with_identity_source"] if metric in {
                "candidate_title_count_0_1_2plus_by_positive", "global_exact_title_diagnostic_by_positive",
            } else totals["identity_source_available"] if metric == "positive_match_methods" and ARM_META[arm] == "master" else
                          totals["all_positives"] if metric == "positive_match_methods" else
                          totals["MATCHED"] if metric == "matched_eligibility_reasons" else sum(aggregate.values()))
            rate_key = {
                "candidate_title_count_0_1_2plus_by_positive": "candidate_title_count_positive_rates",
                "positive_match_methods": "positive_match_method_rates",
                "matched_eligibility_reasons": "matched_eligibility_reason_rates",
                "global_exact_title_diagnostic_by_positive": "global_exact_title_diagnostic_positive_rates",
            }[metric]
            totals[rate_key] = _rate_map(dict(aggregate), denominator)
        totals["global_exact_title_diagnostic_positive_denominator"] = totals["positives_with_identity_source"]
        if arm == "E":
            provenance_positive = totals.pop("identity_metadata_source_by_positive")
            provenance_source_poi = totals.pop("identity_metadata_source_by_source_poi")
            totals["identity_metadata_source_by_positive"] = dict(provenance_positive)
            totals["identity_metadata_source_positive_rates"] = _rate_map(
                dict(provenance_positive), totals["all_positives"])
            totals["identity_metadata_source_by_source_poi"] = dict(provenance_source_poi)
            fallback = totals["visit_fallback_subset"]
            fallback_total = fallback["all_positives"]
            fallback_matched = fallback["MATCHED"]
            fallback["exact_title_candidate_denominator"] = sum(
                fallback["exact_title_candidate_count_0_1_2plus"].values())
            fallback["exact_title_candidate_rates"] = _rate_map(
                dict(fallback["exact_title_candidate_count_0_1_2plus"]),
                fallback["exact_title_candidate_denominator"])
            fallback["matched_eligibility_reason_rates"] = _rate_map(
                dict(fallback["matched_eligibility_reasons"]), fallback_matched)
            fallback["identity_resolution_rate"] = _rate(fallback_matched, fallback_total)
            fallback["candidate_contained_rate_all"] = _rate(
                fallback["candidate_contained"], fallback_total)
            fallback["conditional_coverage"] = _rate(
                fallback["candidate_contained"], fallback_matched)
            fallback["identity_metadata_source"] = "visit_fallback"
            fallback["identity_resolution_status_rates"] = _rate_map(
                {key: fallback[key] for key in ("MATCHED", "AMBIGUOUS", "UNMATCHED")}, fallback_total)
        out["weighted_TL_VL"][arm] = dict(totals)
    d, e = out["weighted_TL_VL"]["D"], out["weighted_TL_VL"]["E"]
    fallback = e["visit_fallback_subset"]
    out["D_to_E_comparison"] = {
        "D_MATCHED": d["MATCHED"], "E_MATCHED": e["MATCHED"],
        "MATCHED_increase": e["MATCHED"] - d["MATCHED"],
        "D_candidate_contained": d["candidate_contained"],
        "E_candidate_contained": e["candidate_contained"],
        "candidate_contained_increase": e["candidate_contained"] - d["candidate_contained"],
        "visit_fallback_subset_identity_resolution_rate": fallback["identity_resolution_rate"],
        "visit_fallback_matched_eligibility_reasons": fallback["matched_eligibility_reasons"],
        "canonical_identity_arm_remains": CANONICAL_IDENTITY_ARM,
        "promotion_decision": "not_promoted_fallback_quality_requires_review",
    }
    cross_weighted = {}
    for unit in ("source_poi", "observed_positive"):
        missing_total = Counter()
        categories_total = Counter()
        for row in out["cross_region_master_lookup"]:
            missing_total[unit] += row[unit]["missing_in_same_region_master"]
            categories_total.update(row[unit]["categories"])
        missing_count = missing_total[unit]
        cross_weighted[unit] = {
            "missing_in_same_region_master": missing_count,
            "categories": dict(categories_total),
            "category_rates": _rate_map(dict(categories_total), missing_count),
        }
    out["cross_region_master_lookup_weighted_TL_VL"] = cross_weighted
    out["master_visit_identity_shadow_validation_weighted_TL_VL"] = _aggregate_shadow_validations(
        out["master_visit_identity_shadow_validation"])
    out["name_candidate_recovery_weighted_TL_VL"] = {
        "unit": "observed_positive", **_aggregate_name_recovery(
            out["name_candidate_recovery_by_region_split_positive"]),
    }
    out["name_candidate_recovery_unique_source_poi"] = {
        "unit": "unique_(region,POI_ID)_among_observed_positive", **_aggregate_name_recovery(
            out["name_candidate_recovery_by_region_unique_source_poi"]),
    }
    out["address_resolution_shadow_weighted_TL_VL"] = {
        "arm": "D", "scope": "ambiguous_observed_positive_only",
        "canonical_matcher_unchanged": True,
        **_aggregate_address_resolution_shadow(out["address_resolution_shadow_by_region_split"]),
    }
    out["address_resolution_shadow_unique_source_poi"] = {
        "arm": "D", "scope": "ambiguous_unique_(region,POI_ID)_among_observed_positive",
        "canonical_matcher_unchanged": True,
        **_aggregate_address_resolution_shadow(out["address_resolution_shadow_by_region_unique_source_poi"]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path(__file__).resolve().parents[2] / "config/recommendation/poi-catalog-policy-v1.json")
    parser.add_argument("--master", action="append", default=[], metavar="REGION=PATH")
    parser.add_argument("--input", action="append", default=[], metavar="REGION:TL|VL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw_root = args.raw_root.resolve()
    specs = []
    parsed = {}
    for value in args.input:
        label, _, path = value.partition("="); region, _, role = label.partition(":")
        if region not in REGIONS or role not in ROLES or not path:
            raise ValueError("input role invalid")
        parsed[(region, role)] = path
    for region in REGIONS:
        for role in ROLES:
            value = parsed.get((region, role)) or os.environ.get(ROLE_ENV[(region, role)])
            if not value:
                raise ValueError("all eight TL/VL inputs are required")
            root = Path(value).resolve()
            if not shared.within(root, raw_root) or not root.is_dir():
                raise ValueError("TL/VL input failed safe validation")
            specs.append(shared.InputSpec(region, role, root))
    masters = {}
    parsed_masters = dict(value.split("=", 1) for value in args.master)
    for region in REGIONS:
        root = Path(parsed_masters[region]).resolve()
        if not shared.within(root, raw_root) or not root.is_dir():
            raise ValueError("master input failed safe validation")
        masters[region] = _master_rows(root)
    output = args.output
    if not output.is_absolute() or "results" not in output.parts:
        raise ValueError("output must be an absolute path under ignored results/")
    run(specs, masters, args.snapshot.resolve(), args.policy.resolve(), output)


if __name__ == "__main__":
    main()
