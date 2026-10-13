# Recommendation domain review

Use this reference with the `travel-data-scientist` skill before actual-data analysis.

## Review matrix

| Area | Required question | Warning sign |
| --- | --- | --- |
| Product question | What decision or recommendation behavior are we trying to improve? | The analysis target is chosen because a column exists, not because it matches the product question. |
| Prediction time | What is known before the recommendation is shown? | Post-visit values appear in the feature set. |
| User/context/item | Which fields describe the traveler, the current trip/request, and the POI? | Stable profile, trip context, and item metadata are mixed without meaning. |
| Interaction | What observed action counts as evidence? | A visit, rating, recommendation intention, and exposure are treated as the same event. |
| Implicit feedback | What does an unobserved POI mean? | Unobserved is silently converted to negative/dislike. |
| Candidate/exposure | Which POIs could reasonably have appeared for this trip? | The evaluated item set changes between models or is undefined. |
| Task type | Is the question association, classification, retrieval, or ranking? | Ranking quality is inferred from a different task without qualification. |
| Baseline | What simple strategy must a model beat? | No popularity/region/category or equivalent baseline is included when those signals dominate. |
| Metric | Does the metric measure the requested behavior? | Accuracy is the only metric for a ranking question. |
| Split/cohort | Are compared results based on compatible observations? | Different complete-case cohorts are compared as incremental feature value. |
| Leakage | Can labels or future events leak into features or splits? | Same trip/event is split across train and validation, or feedback becomes input. |
| Generalization | Are cold-start, sparsity, long tail, and region bias visible? | Aggregate results hide a structurally weak cohort. |

## Current travel-log semantics

Use repository data contracts as the source of truth. At minimum:

- `TRAVELER_ID` identifies a traveler candidate within documented scope; do not assume cross-region identity beyond the contract.
- `TRAVEL_ID` identifies the trip context used to group visit events.
- `TN_VISIT_AREA_INFO` contains observed visits and visit-level information.
- `TN_POI_MASTER` supplies POI metadata when the documented candidate linkage is valid.
- `DGSTFN`, `REVISIT_INTENTION`, and `RCMDTN_INTENTION` are post-visit feedback.
- A nonblank `POI_ID` candidate is not automatically a globally canonical POI key.
- An observed visit can be an implicit positive; absence of a visit is not proof of dislike.

## Directness of evidence

Classify the relationship between an experiment and the product question:

- **direct** — the target and metric directly represent the requested behavior.
- **proxy** — the target is related but does not directly measure the behavior; state the gap.
- **mismatch** — the experiment answers a materially different question.

Examples:

| Product question | Experiment | Classification |
| --- | --- | --- |
| Which POIs should rank highest for a trip context? | Rank candidate POIs and evaluate observed positives with ranking metrics under a documented candidate protocol. | direct |
| Which visited POIs receive high satisfaction? | Predict `DGSTFN` from context and the already-visited POI. | proxy |
| Does travel context improve POI ranking? | Predict post-visit recommendation intention with 5-class accuracy only. | mismatch for a direct ranking claim |

A proxy experiment may still be useful. The handoff must state what it does not establish.

## Implicit-feedback checklist

Before constructing negatives or ranking evaluation, answer:

1. What constitutes an observed positive?
2. What items were plausibly available/exposed?
3. What does an unobserved item mean in this dataset?
4. Is negative sampling required? If yes, from which set and with which seed?
5. Could a sampled negative become a future or otherwise hidden positive?
6. Is the candidate definition fixed across compared models?
7. Are cold-start items/users separated or reported?

Never equate `unvisited = dislike` without an explicit, justified experimental assumption.

## Leakage checklist

Check all applicable paths:

- post-event feedback -> recommendation-time feature
- same `TRAVEL_ID` event rows across train/validation
- same user/item overlap that changes the intended generalization claim
- future popularity counts used in training
- validation/test catalog information unavailable at the simulated prediction time
- exact dates or identifiers acting as unintended memorization keys

## Metric selection

Use the metric that matches the question.

- classification: class-aware metrics appropriate to imbalance and ordinal/categorical semantics
- retrieval/ranking: candidate-set-aware Recall@K, Precision@K, HitRate@K, NDCG@K, or another justified ranking metric
- association: effect size plus support and replication; do not treat significance alone as usefulness

A metric name is not a substitute for a valid candidate, ground-truth, and split definition.

## Handoff template

```text
Analysis purpose:
Product question:
Data roles:
Code revision:

Problem type:
Prediction time:
Entities:
Target / ground truth:
Direct / proxy / mismatch:

Candidate / exposure assumption:
Negative semantics:
Split / cohort:
Leakage checks:
Baseline:
Metrics:

Validation executed:
Privacy-safe results:

Facts:
Interpretation / inference:
Unresolved limitations:
Next decision:
```

Do not include raw local paths, raw identifiers, row-level values, coordinates, free text, credentials, or secrets.
