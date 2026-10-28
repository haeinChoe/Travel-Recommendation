# 추천 시스템 문서 읽기 순서

추천 문서는 모델 이름보다 **문제 → 데이터 의미 → 후보 자격 → 평가 → 모델 비교** 순서로 읽습니다.

## 처음 읽는 경우

1. [추천 문제 정의 v2 — 단일 기준](problem-definition-v2.md) — 최상위 질문, 현재 확정 사항, 작업 가설, 미결정을 확인합니다.
2. [추천 시스템 용어 사전](glossary.md) — user/traveler, trip/request, POI, observed visit, candidate eligibility/generation 등의 공통 의미를 확인합니다.
3. [추천 학습 데이터 계약](training-data-contract.md) — 기존 AI Hub 관측 단위, 데이터 의미, feature/label 근거를 확인합니다. v1 코호트와 세부 규칙이 v2 제품 후보 범위를 자동 확정하지 않습니다.
4. [표준 학습 데이터셋 스키마](training-dataset-schema.md) — Parquet 출력의 컬럼·타입·역할을 확인합니다. TL→train/VL→validation은 변환 출력 역할명이므로 모델 선택 split과 구분합니다.
5. [학습·평가 계약](model-training-evaluation-contract.md) — 여행별 학습 행·관측 라벨·후보 집합과, 지역 전체 후보를 점수화했던 실험의 비용 및 현재 보류 이유를 확인합니다.
6. [CatBoost ranking 실험 프로토콜](experiments/catboost-ranking-protocol.md) — YetiRank prototype 및 과거 실험 계획을 확인합니다. CatBoost의 최종 역할은 고정되지 않았습니다.
7. [제품 카탈로그와 후보 계약](poi-catalog-candidate-contract.md) — 실제 서비스에 표시할 장소 카탈로그와 AI Hub 방문 기록을 연결하는 규칙, 양쪽 식별자 차이를 확인합니다.
8. [다단계 POI 식별자 연결 실험 결과](experiments/poi-identity-matching-v2.md) — Stage 0과 Stage 5를 서로 다른 기준·분모로 확인합니다.
9. [추천 서비스 상호작용 로그 계약](service-interaction-log-contract.md) — 추천 요청·노출·클릭·저장·선택적 방문 확인·피드백의 최소 의미와 운영 후 장소 특징 갱신 구조를 확인합니다.

## 관련 실험 문서

- [후보 집합 타당성 실험](experiments/candidate-choice-feasibility.md)
- [여행 문맥 × POI 신호 타당성 실험](experiments/context-poi-signal-feasibility.md)
- [Canonical administrative location (I2)](experiments/canonical-admin-location.md)
- [연구·실험 문서 템플릿](experiment-document-template.md)

## 현재 해석 원칙

- 문제 정의와 결정 우선순위는 [problem-definition-v2.md](problem-definition-v2.md)가 정합니다. 전문 문서는 그 정의를 덮어쓰지 않습니다.
- 관측 방문은 baseline용 암묵적 양성 후보이지 만족이나 추천 노출을 뜻하지 않습니다. 미관측은 unknown입니다.
- sampled-unobserved의 학습 label 0은 비교용 pseudo-negative이며 관측된 불호가 아닙니다.
- 원시 ID는 join, grouping, split 확인, 후보 식별에만 사용하고 model feature로 넣지 않습니다.
- 행동 파생 feature와 sampling 통계는 TL 내부 모델 선택 시 inner-train에서만 계산합니다.
- 추천 자격(candidate eligibility)은 제품상 추천 대상이 될 수 있는지를 정하고, 후보 생성(candidate generation)은 요청별 점수화 대상을 줄이는 선택적 단계입니다.
- 후보 coverage와 모델의 ranking metric을 분리합니다. validation positive를 후보에 사후 주입하지 않습니다.
- 공식 VL은 모델과 후보·입력 특징을 최종 확정하기 전에는 사용하지 않으며, 마지막 성능 확인에만 사용합니다.
- TourAPI는 제품/서빙용 카탈로그이며 AI Hub 오프라인 평가 universe와 같은 것으로 보지 않습니다.

세부 결정의 근거는 [#41](https://github.com/haeinChoe/Travel-Recommendation/issues/41), [#66](https://github.com/haeinChoe/Travel-Recommendation/issues/66), [#69](https://github.com/haeinChoe/Travel-Recommendation/issues/69), [#82](https://github.com/haeinChoe/Travel-Recommendation/issues/82), [#94](https://github.com/haeinChoe/Travel-Recommendation/issues/94), [#95](https://github.com/haeinChoe/Travel-Recommendation/issues/95), [#96](https://github.com/haeinChoe/Travel-Recommendation/issues/96), [#97](https://github.com/haeinChoe/Travel-Recommendation/issues/97), [#83](https://github.com/haeinChoe/Travel-Recommendation/issues/83)에 연결합니다.