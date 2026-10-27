from __future__ import annotations

import json
import unittest
from typing import Any, Mapping

from scripts.recommendation.serving_benchmark import (
    Candidate,
    ConversationalLlmAdapter,
    JevAdapter,
    RankingResult,
    benchmark_backend,
    generate_synthetic_requests,
    hit_rate_at_k,
    ndcg_at_k,
    parse_llm_ranking,
    random_quality_baseline,
)


class FakeTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers),
                "timeout_s": timeout_s,
            }
        )
        return self.response


class ServingBenchmarkTest(unittest.TestCase):
    def test_synthetic_fixture_is_deterministic_and_has_positive_relevance(self) -> None:
        first = generate_synthetic_requests(count=3, candidates_per_request=5, seed=7)
        second = generate_synthetic_requests(count=3, candidates_per_request=5, seed=7)

        self.assertEqual(first, second)
        for request in first:
            self.assertGreater(max(request.relevance.values()), 0)
            self.assertEqual(len(request.candidates), 5)

    def test_jev_adapter_ranks_by_probability_and_sends_choice_contract(self) -> None:
        request = generate_synthetic_requests(count=1, candidates_per_request=3, seed=2)[0]
        ids = [candidate.candidate_id for candidate in request.candidates]
        transport = FakeTransport(
            {
                "answers": {
                    "recommendation": {
                        "choice": ids[1],
                        "probabilities": {
                            ids[0]: 0.1,
                            ids[1]: 0.7,
                            ids[2]: 0.2,
                        },
                    }
                },
                "usage": {"input_tokens": 100, "output_tokens": 0},
            }
        )
        adapter = JevAdapter(
            base_url="http://jev.test",
            model="jev-test",
            api_key="secret",
            transport=transport,
        )

        result = adapter.rank(request)

        self.assertEqual(result.ranked_candidate_ids, (ids[1], ids[2], ids[0]))
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 0)
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://jev.test/v1/systemone")
        question = call["payload"]["questions"]["recommendation"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), set(ids))
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret")

    def test_jev_adapter_rejects_partial_probability_distribution(self) -> None:
        request = generate_synthetic_requests(count=1, candidates_per_request=3, seed=3)[0]
        ids = [candidate.candidate_id for candidate in request.candidates]
        transport = FakeTransport(
            {
                "answers": {
                    "recommendation": {
                        "choice": ids[0],
                        "probabilities": {ids[0]: 1.0},
                    }
                }
            }
        )
        adapter = JevAdapter(
            base_url="http://jev.test",
            model="jev-test",
            transport=transport,
        )

        with self.assertRaisesRegex(ValueError, "cover every candidate"):
            adapter.rank(request)

    def test_llm_parser_requires_exact_candidate_permutation(self) -> None:
        candidates = (
            Candidate("a", "A", ("nature",), "A"),
            Candidate("b", "B", ("food",), "B"),
        )

        self.assertEqual(
            parse_llm_ranking('{"ranking":["b","a"]}', candidates),
            ("b", "a"),
        )

        invalid_payloads = (
            '{"ranking":["a"]}',
            '{"ranking":["a","a"]}',
            '{"ranking":["a","c"]}',
            '{"ranking":["a","b"],"note":"extra"}',
            '```json\n{"ranking":["a","b"]}\n```',
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_llm_ranking(payload, candidates)

    def test_conversational_llm_adapter_uses_openai_compatible_contract(self) -> None:
        request = generate_synthetic_requests(count=1, candidates_per_request=3, seed=4)[0]
        ids = [candidate.candidate_id for candidate in request.candidates]
        transport = FakeTransport(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"ranking": [ids[2], ids[0], ids[1]]}
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 210, "completion_tokens": 25},
            }
        )
        adapter = ConversationalLlmAdapter(
            base_url="http://llm.test/v1",
            model="chat-test",
            transport=transport,
        )

        result = adapter.rank(request)

        self.assertEqual(result.ranked_candidate_ids, (ids[2], ids[0], ids[1]))
        self.assertEqual(result.input_tokens, 210)
        self.assertEqual(result.output_tokens, 25)
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://llm.test/v1/chat/completions")
        self.assertEqual(call["payload"]["temperature"], 0)

    def test_quality_metrics_reward_better_order(self) -> None:
        relevance = {"a": 2, "b": 1, "c": 0}
        best = ndcg_at_k(("a", "b", "c"), relevance, 3)
        worse = ndcg_at_k(("c", "b", "a"), relevance, 3)

        self.assertAlmostEqual(best, 1.0)
        self.assertLess(worse, best)
        self.assertEqual(hit_rate_at_k(("c", "b", "a"), relevance, 1), 0.0)
        self.assertEqual(hit_rate_at_k(("c", "b", "a"), relevance, 2), 1.0)

    def test_benchmark_aggregates_success_and_failure(self) -> None:
        requests = generate_synthetic_requests(count=2, candidates_per_request=3, seed=5)

        class Adapter:
            def rank(self, request):
                if request.request_id.endswith("0001"):
                    raise ValueError("synthetic failure")
                ordered = tuple(
                    candidate.candidate_id for candidate in request.candidates
                )
                return RankingResult(
                    backend="fake",
                    request_id=request.request_id,
                    ranked_candidate_ids=ordered,
                    latency_ms=10.0,
                )

        report = benchmark_backend(
            adapter=Adapter(),
            requests=requests,
            concurrency=2,
            k=2,
        )

        self.assertEqual(report["backend"], "fake")
        self.assertEqual(report["requests"], 2)
        self.assertEqual(report["successes"], 1)
        self.assertEqual(report["failures"], 1)
        self.assertEqual(report["success_rate"], 0.5)
        self.assertEqual(report["latency_ms"]["p50"], 10.0)
        self.assertEqual(report["failure_samples"][0]["error_type"], "ValueError")
        self.assertEqual(
            report["quality_failure_aware"]["mrr"],
            report["quality_success_only"]["mrr"] / 2,
        )

    def test_random_quality_baseline_is_deterministic(self) -> None:
        requests = generate_synthetic_requests(count=4, candidates_per_request=5, seed=11)
        first = random_quality_baseline(requests, seed=99, k=3)
        second = random_quality_baseline(requests, seed=99, k=3)

        self.assertEqual(first, second)
        self.assertIn("ndcg@3", first)
        self.assertIn("hit_rate@3", first)
        self.assertIn("mrr", first)


if __name__ == "__main__":
    unittest.main()
