#!/usr/bin/env python3
"""Serving benchmark for JEV-style decisions vs conversational LLM ranking.

The default fixture is a small public sequential-recommendation benchmark derived
from Amazon Reviews 2023. The original synthetic theme fixture remains available
for smoke testing. Both backends always receive the same request and candidates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from scripts.recommendation.hf_amazon_benchmark import prepare_hf_amazon_fixture


THEMES = (
    "nature",
    "quiet",
    "food",
    "history",
    "art",
    "activity",
    "nightlife",
    "family",
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    name: str
    themes: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class RecommendationRequest:
    request_id: str
    preference_text: str
    preferred_themes: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    relevance: Mapping[str, int]


@dataclass(frozen=True)
class RankingResult:
    backend: str
    request_id: str
    ranked_candidate_ids: tuple[str, ...]
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class JsonTransport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> Mapping[str, Any]: ...


def http_json_transport(
    *,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_s: float,
) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {message[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc

    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("HTTP response must be a JSON object")
    return parsed


class JevAdapter:
    """Adapter for TypeSafe-compatible POST /v1/systemone Choice decisions."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: JsonTransport = http_json_transport,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.transport = transport

    def rank(self, request: RecommendationRequest) -> RankingResult:
        criteria = {
            candidate.candidate_id: _candidate_text(candidate)
            for candidate in request.candidates
        }
        payload = {
            "model": self.model,
            "state": {
                "traveler_request": request.preference_text,
            },
            "questions": {
                "recommendation": {
                    "type": "choice",
                    "instructions": (
                        "Choose the destination that best matches the traveler's request. "
                        "Use the candidate descriptions in criteria."
                    ),
                    "criteria": criteria,
                }
            },
        }
        headers = _auth_headers(self.api_key)
        started = time.perf_counter()
        response = self.transport(
            url=_endpoint_url(self.base_url, "/v1/systemone"),
            payload=payload,
            headers=headers,
            timeout_s=self.timeout_s,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        answers = _require_mapping(response, "answers")
        answer = _require_mapping(answers, "recommendation")
        probabilities = _require_mapping(answer, "probabilities")

        expected = {candidate.candidate_id for candidate in request.candidates}
        seen = set(probabilities)
        if seen != expected:
            missing = sorted(expected - seen)
            extra = sorted(seen - expected)
            raise ValueError(
                f"JEV probabilities must cover every candidate exactly; "
                f"missing={missing}, extra={extra}"
            )

        numeric_probs: dict[str, float] = {}
        for candidate_id, value in probabilities.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"JEV probability for {candidate_id} is not numeric")
            probability = float(value)
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"JEV probability for {candidate_id} is outside [0, 1]")
            numeric_probs[str(candidate_id)] = probability

        ranked = tuple(
            sorted(numeric_probs, key=lambda cid: (-numeric_probs[cid], cid))
        )
        usage = response.get("usage")
        input_tokens, output_tokens = _parse_usage(usage)
        return RankingResult(
            backend="jev",
            request_id=request.request_id,
            ranked_candidate_ids=ranked,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class ConversationalLlmAdapter:
    """Adapter for an OpenAI-compatible POST /v1/chat/completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: JsonTransport = http_json_transport,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.transport = transport

    def rank(self, request: RecommendationRequest) -> RankingResult:
        candidate_lines = "\n".join(
            f"- {candidate.candidate_id}: {_candidate_text(candidate)}"
            for candidate in request.candidates
        )
        prompt = (
            "Rank every candidate from best to worst for this traveler.\n"
            f"Traveler request: {request.preference_text}\n"
            "Candidates:\n"
            f"{candidate_lines}\n\n"
            'Return JSON only in this exact shape: {"ranking":["id1","id2",...]}. '
            "Include every candidate exactly once and do not add commentary."
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a ranking component in a recommendation benchmark. "
                        "Follow the requested JSON contract exactly."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = _auth_headers(self.api_key)
        started = time.perf_counter()
        response = self.transport(
            url=_endpoint_url(self.base_url, "/v1/chat/completions"),
            payload=payload,
            headers=headers,
            timeout_s=self.timeout_s,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Chat completion must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError("Chat completion choice must be an object")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("Chat completion choice.message must be an object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Chat completion message.content must be a string")

        ranked = parse_llm_ranking(content, request.candidates)
        usage = response.get("usage")
        input_tokens, output_tokens = _parse_usage(usage)
        return RankingResult(
            backend="conversational_llm",
            request_id=request.request_id,
            ranked_candidate_ids=ranked,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def parse_llm_ranking(
    content: str,
    candidates: Sequence[Candidate],
) -> tuple[str, ...]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response is not strict JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"ranking"}:
        raise ValueError("LLM response must contain only the 'ranking' field")
    ranking = parsed["ranking"]
    if not isinstance(ranking, list) or not all(isinstance(x, str) for x in ranking):
        raise ValueError("'ranking' must be a list of candidate-id strings")

    expected = [candidate.candidate_id for candidate in candidates]
    if len(ranking) != len(expected):
        raise ValueError("LLM ranking length does not match candidate count")
    if len(set(ranking)) != len(ranking):
        raise ValueError("LLM ranking contains duplicate candidate ids")
    if set(ranking) != set(expected):
        missing = sorted(set(expected) - set(ranking))
        extra = sorted(set(ranking) - set(expected))
        raise ValueError(
            f"LLM ranking must contain every candidate exactly; missing={missing}, extra={extra}"
        )
    return tuple(ranking)


def generate_synthetic_requests(
    *,
    count: int,
    candidates_per_request: int,
    seed: int,
) -> list[RecommendationRequest]:
    if count <= 0:
        raise ValueError("count must be positive")
    if not 2 <= candidates_per_request <= 255:
        raise ValueError("candidates_per_request must be between 2 and 255")

    rng = random.Random(seed)
    requests: list[RecommendationRequest] = []
    for request_index in range(count):
        preferred = tuple(sorted(rng.sample(THEMES, 2)))
        preference_text = (
            f"I want a trip focused on {preferred[0]} and {preferred[1]}. "
            "Prefer places that strongly match those interests."
        )
        candidates: list[Candidate] = []
        relevance: dict[str, int] = {}

        for candidate_index in range(candidates_per_request):
            themes = tuple(sorted(rng.sample(THEMES, 2)))
            candidate_id = f"r{request_index:04d}-c{candidate_index:03d}"
            candidate = Candidate(
                candidate_id=candidate_id,
                name=f"Synthetic Place {candidate_index + 1}",
                themes=themes,
                description=f"A place known for {themes[0]} and {themes[1]}.",
            )
            candidates.append(candidate)
            relevance[candidate_id] = len(set(preferred) & set(themes))

        if max(relevance.values()) == 0:
            first = candidates[0]
            forced = Candidate(
                candidate_id=first.candidate_id,
                name=first.name,
                themes=preferred,
                description=f"A place known for {preferred[0]} and {preferred[1]}.",
            )
            candidates[0] = forced
            relevance[forced.candidate_id] = 2

        requests.append(
            RecommendationRequest(
                request_id=f"synthetic-{request_index:04d}",
                preference_text=preference_text,
                preferred_themes=preferred,
                candidates=tuple(candidates),
                relevance=relevance,
            )
        )
    return requests


def ndcg_at_k(
    ranked_candidate_ids: Sequence[str],
    relevance: Mapping[str, int],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    dcg = _dcg([relevance.get(cid, 0) for cid in ranked_candidate_ids[:k]])
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    return 0.0 if idcg == 0.0 else dcg / idcg


def hit_rate_at_k(
    ranked_candidate_ids: Sequence[str],
    relevance: Mapping[str, int],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return float(any(relevance.get(cid, 0) > 0 for cid in ranked_candidate_ids[:k]))


def reciprocal_rank(
    ranked_candidate_ids: Sequence[str],
    relevance: Mapping[str, int],
) -> float:
    for index, candidate_id in enumerate(ranked_candidate_ids, start=1):
        if relevance.get(candidate_id, 0) > 0:
            return 1.0 / index
    return 0.0


def _dcg(relevances: Sequence[int]) -> float:
    total = 0.0
    for index, rel in enumerate(relevances):
        gain = (2**rel) - 1
        total += gain / math.log2(index + 2)
    return total


def benchmark_backend(
    *,
    adapter: Any,
    requests: Sequence[RecommendationRequest],
    concurrency: int,
    k: int,
) -> dict[str, Any]:
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if not requests:
        raise ValueError("requests must not be empty")

    started = time.perf_counter()
    successes: list[tuple[RecommendationRequest, RankingResult]] = []
    failures: list[dict[str, str]] = []

    def invoke(req: RecommendationRequest) -> tuple[RecommendationRequest, RankingResult]:
        return req, adapter.rank(req)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {executor.submit(invoke, req): req for req in requests}
        for future in as_completed(future_map):
            req = future_map[future]
            try:
                successes.append(future.result())
            except Exception as exc:
                failures.append(
                    {
                        "request_id": req.request_id,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:300],
                    }
                )

    elapsed_s = time.perf_counter() - started
    latencies = [result.latency_ms for _, result in successes]
    ndcgs = [
        ndcg_at_k(result.ranked_candidate_ids, req.relevance, k)
        for req, result in successes
    ]
    hits = [
        hit_rate_at_k(result.ranked_candidate_ids, req.relevance, k)
        for req, result in successes
    ]
    reciprocal_ranks = [
        reciprocal_rank(result.ranked_candidate_ids, req.relevance)
        for req, result in successes
    ]
    input_tokens = [
        result.input_tokens for _, result in successes if result.input_tokens is not None
    ]
    output_tokens = [
        result.output_tokens for _, result in successes if result.output_tokens is not None
    ]

    backend_name = getattr(adapter, "__class__", type(adapter)).__name__
    if successes:
        backend_name = successes[0][1].backend

    return {
        "backend": backend_name,
        "requests": len(requests),
        "successes": len(successes),
        "failures": len(failures),
        "success_rate": len(successes) / len(requests),
        "elapsed_s": elapsed_s,
        "throughput_requests_per_s": len(successes) / elapsed_s if elapsed_s > 0 else None,
        "latency_ms": {
            "p50": _percentile(latencies, 50) if latencies else None,
            "p95": _percentile(latencies, 95) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        f"ndcg@{k}": statistics.fmean(ndcgs) if ndcgs else None,
        f"hit_rate@{k}": statistics.fmean(hits) if hits else None,
        "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else None,
        "usage": {
            "input_tokens_total": sum(input_tokens) if input_tokens else None,
            "output_tokens_total": sum(output_tokens) if output_tokens else None,
        },
        "failure_samples": failures[:10],
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (percentile / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _endpoint_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    if normalized_base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{normalized_base}{path}"


def _candidate_text(candidate: Candidate) -> str:
    parts = [candidate.name]
    if candidate.description:
        parts.append(candidate.description)
    if candidate.themes:
        parts.append(f"Themes: {', '.join(candidate.themes)}")
    return ". ".join(parts) + "."


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {} if not api_key else {"Authorization": f"Bearer {api_key}"}


def _require_mapping(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Expected '{key}' to be a JSON object")
    return value


def _parse_usage(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return None, None
    input_value = value.get("input_tokens", value.get("prompt_tokens"))
    output_value = value.get("output_tokens", value.get("completion_tokens"))
    return _optional_nonnegative_int(input_value), _optional_nonnegative_int(output_value)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _read_optional_secret(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if value is None:
        raise RuntimeError(f"Required API key environment variable is missing: {env_name}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare JEV typed-decision serving with conversational LLM ranking."
    )
    parser.add_argument(
        "--fixture-source",
        choices=("hf-amazon-llm", "synthetic"),
        default="hf-amazon-llm",
        help="Benchmark fixture source. Hugging Face sequential recommendation is the default.",
    )
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument(
        "--candidates",
        type=int,
        default=8,
        help="Synthetic fixture only; the Hugging Face benchmark has 10 fixed candidates.",
    )
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--history-size", type=int, default=8)
    parser.add_argument("--description-chars", type=int, default=320)
    parser.add_argument(
        "--hf-cache-dir",
        default="results/issue-90/hf-amazon-llm",
        help="Git-ignored directory used for the three downloaded parquet files.",
    )
    parser.add_argument("--hf-revision", default="main")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=60.0)

    parser.add_argument("--jev-base-url", default="http://localhost:8790")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument("--jev-api-key-env")

    parser.add_argument("--llm-base-url", default="http://localhost:8000/v1")
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--llm-api-key-env")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fixture_source == "synthetic":
        requests = generate_synthetic_requests(
            count=args.requests,
            candidates_per_request=args.candidates,
            seed=args.seed,
        )
        fixture_metadata: dict[str, Any] = {
            "source": "synthetic-theme-overlap",
            "requests": args.requests,
            "candidates_per_request": args.candidates,
            "seed": args.seed,
        }
    else:
        cases, fixture_metadata = prepare_hf_amazon_fixture(
            cache_dir=Path(args.hf_cache_dir),
            request_count=args.requests,
            seed=args.seed,
            history_size=args.history_size,
            description_chars=args.description_chars,
            revision=args.hf_revision,
        )
        requests = []
        for case in cases:
            candidates = tuple(
                Candidate(
                    candidate_id=str(candidate["candidate_id"]),
                    name=str(candidate["name"]),
                    themes=(),
                    description=str(candidate["description"]),
                )
                for candidate in case["candidates"]
            )
            ground_truth = str(case["ground_truth_candidate_id"])
            requests.append(
                RecommendationRequest(
                    request_id=str(case["request_id"]),
                    preference_text=str(case["preference_text"]),
                    preferred_themes=(),
                    candidates=candidates,
                    relevance={
                        candidate.candidate_id: int(candidate.candidate_id == ground_truth)
                        for candidate in candidates
                    },
                )
            )
        fixture_metadata["seed"] = args.seed

    jev = JevAdapter(
        base_url=args.jev_base_url,
        model=args.jev_model,
        api_key=_read_optional_secret(args.jev_api_key_env),
        timeout_s=args.timeout_s,
    )
    llm = ConversationalLlmAdapter(
        base_url=args.llm_base_url,
        model=args.llm_model,
        api_key=_read_optional_secret(args.llm_api_key_env),
        timeout_s=args.timeout_s,
    )

    report = {
        "benchmark": "jev-vs-conversational-llm-serving",
        "fixture": {
            **fixture_metadata,
            "k": args.k,
            "concurrency": args.concurrency,
        },
        "results": [
            benchmark_backend(
                adapter=jev,
                requests=requests,
                concurrency=args.concurrency,
                k=args.k,
            ),
            benchmark_backend(
                adapter=llm,
                requests=requests,
                concurrency=args.concurrency,
                k=args.k,
            ),
        ],
        "limitations": [
            "The default fixture is an Amazon sequential-recommendation benchmark, not travel-domain ground truth.",
            "The 24-request default is a small serving comparison, not a statistically definitive recommender evaluation.",
            "Backends may use different hardware, batching, quantization, and network paths.",
            "Token counts are reported only when the endpoint returns usage metadata.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
