# Travel Recommendation PRD

>
> Last updated: 2026-10-20

## 문서 상태와 한눈에 보는 결론

**이 문서가 답하려는 질문:** 사용자가 어떤 정보를 제공하고, 서비스가 어떤 여행지를 어떤 단위로 추천하며, 오프라인 실험과 실제 서비스의 데이터 경계를 어떻게 나눌 것인가?

**현재 상태:** 제품 수준의 추천 흐름과 POI 식별자 경계는 정리되었다. Issue #41에서 오프라인 학습·평가의 세부 계약을 확정하는 중이다.

**한눈에 보는 결론:**

- 추천 결과의 기본 단위는 **순위가 매겨진 Top-K POI**다.
- 사용자는 현재 여행 문맥과 명시적 선호만으로 추천을 받을 수 있어야 한다.
- 오프라인 학습·평가는 AI Hub의 원래 POI 식별자를 사용한다.
- 제품 서비스용 POI 카탈로그는 TourAPI `contentid`를 사용한다.
- AI Hub와 TourAPI 사이의 **식별자 연결**은 별도 문제이며, 오프라인 모델 비교의 선행조건이 아니다.

**아직 결정되지 않은 것:** 예측 단위, 서비스 시점 입력 특성 허용 목록, 학습 목표 신호, 데이터 분할, 콜드 스타트 평가 집단, 음성 표본 규칙.

**다음 행동:** Issue #41에서 `model-training-evaluation-contract.md`를 작성해 위 미결정 사항을 확정한다.

## 1. Product Overview

Travel Recommendation은 기존 TravelMate 프로젝트를 기반으로 여행지 탐색, 개인화 추천, 리뷰 및 커뮤니티 기능을 현대적인 풀스택 구조로 재설계하는 프로젝트다.

이번 리뉴얼의 목적은 단순한 프레임워크 교체가 아니다. 기존 기능을 보존하되 서비스 경계와 데이터 흐름을 다시 설계하고, 기존의 단순 user-based collaborative filtering 중심 추천 시스템을 재현 가능한 실험과 오프라인 평가를 기반으로 단계적으로 고도화한다.

초기 기술 방향은 다음과 같다.

- Web: Next.js + TypeScript
- API: NestJS + TypeScript
- Recommendation: Python
- Product DB: PostgreSQL 후보
- Experiment tracking: MLflow 후보
- Hyperparameter optimization: 필요 시 Optuna

세부 라이브러리와 인프라는 본 PRD에서 고정하지 않으며, 별도 아키텍처/기술 결정 이슈에서 검증 후 확정한다.

---

## 2. Background

기존 TravelMate는 다음 기능을 제공했다.

- Kakao 기반 사용자 인증
- 여행 지역 선택
- 여행 기간 입력
- 여행 스타일/동반자 등 취향 입력
- 관광지 추천
- 관광지 상세 조회 및 리뷰
- 커뮤니티 게시글/댓글/좋아요
- 마이페이지

기존 추천 흐름은 대략 다음과 같다.

```text
사용자 취향 입력
  -> Spring Backend에 Preference 저장
  -> FastAPI 추천 서버 호출
  -> 추천 서버가 DB/CSV 데이터를 읽어 유사도 계산
  -> 추천 contentId 목록 반환
  -> Backend가 TourSpot 엔티티로 변환
  -> Client에 추천 결과 반환
```

이 구조는 MVP로서는 동작하지만 다음 문제가 있다.

1. 추천 요청 시점에 DB 조회, DataFrame 생성, CSV 로딩, 유사도 계산이 반복되어 online serving 비용이 크다.
2. API 서비스와 추천 서비스가 동일한 운영 DB 스키마에 직접 결합되어 있다.
3. 추천 품질을 객관적으로 비교하는 공통 evaluation protocol이 없다.
4. 기존 hybrid 추천은 collaborative score와 content score의 스케일 차이를 충분히 보정하지 않는다.
5. 사용자 행동 데이터가 주로 Preference/Visited 수준으로 축약되어 있어 원본 AI Hub 여행로그의 정보를 충분히 활용하지 못한다.
6. 모델 버전, 데이터셋 버전, 실험 파라미터 및 결과를 재현할 수 있는 실험 관리 체계가 없다.

---

## 3. Product Vision

사용자가 이번 여행의 상황과 명시적으로 제공한 취향을 입력하면, 서비스가 현재 여행 맥락에서 추천 가능한 관광지를 관련성 순으로 랭킹해 Top-K로 제공하는 구조를 만든다.

장기적으로는 다음과 같은 경험을 지원할 수 있어야 한다.

> "부모님과 10월에 제주를 가는데 너무 많이 걷지 않고 조용한 장소 위주로 추천해줘"

자연어 해석 기능을 사용하더라도 추천 후보와 랭킹은 검증 가능한 데이터 계약과 추천 모델을 기반으로 수행하는 것을 기본 방향으로 한다.

현재 item identity는 **오프라인 실험과 product serving을 분리**한다.

- 오프라인 학습·평가: AI Hub native POI identity `(region, nonblank POI_ID)`
- 제품 서비스용 카탈로그: TourAPI KorService2의 `(tourapi-korservice2, contentid)`
- AI Hub ↔ TourAPI: 별도의 식별자 연결 문제

Issue #4 / PR #64의 실제 데이터 검증에서 현재 식별자 연결만으로는 오프라인 관측 양성 커버리지를 신뢰성 있게 평가하기 어렵다고 판단했다. 따라서 TourAPI 식별자 연결을 오프라인 추천 실험의 선행조건으로 두지 않는다. TourAPI는 제품 서비스용 카탈로그 v1 원천으로 유지한다.

---

## 4. Goals

### 4.1 Product Goals

- 기존 TravelMate의 주요 사용자 플로우를 현대적인 UX/API 구조로 재구축한다.
- 사용자 취향, 여행 맥락, 행동 이력을 이용한 개인화 여행지 추천을 제공한다.
- 추천 결과에서 실제 존재하는 canonical 관광지만 반환한다.
- 추천 결과에 대한 사용자의 반응을 추후 학습/평가에 사용할 수 있도록 interaction logging 구조를 마련한다.

### 4.2 Engineering Goals

- Next.js와 NestJS 기반 TypeScript 풀스택 아키텍처를 경험하고 재설계한다.
- Web/API/Recommendation 간 책임과 데이터 소유권을 명확히 한다.
- 추천 모델의 offline training/evaluation과 online serving을 분리한다.
- 동일한 데이터셋과 지표로 여러 추천 모델을 비교할 수 있도록 한다.
- 모델/데이터/실험 결과의 재현 가능성을 확보한다.

### 4.3 Recommendation Goals

추천의 제품 목표는 **현재 여행 맥락에서 고려 가능한 POI를 관련성 순으로 랭킹해 Top-K로 제공하는 것**이다.

- 현재 여행 맥락과 명시적 사용자 취향을 핵심 요청 입력으로 둔다.
- 장기 사용자 history가 없는 콜드 스타트 사용자를 핵심 시나리오로 지원한다.
- 지역·서비스 가능 범위 같은 명백한 제품 조건은 가능한 경우 랭킹 전에 후보 자격으로 적용한다.
- 특정 모델 계열을 제품 요구사항처럼 선결정하지 않는다.
- Popularity baseline과 기존 CF feasibility 결과를 공통 비교 근거로 사용하고, 후속 모델은 #41의 학습·평가 계약을 확정한 뒤 선택한다.
- 오프라인 실험은 AI Hub native POI identity에서 수행하며, TourAPI 서비스용 식별자와의 식별자 연결를 모델 비교의 필수 조건으로 두지 않는다.

후속 후보에는 feature-based ranking, Learning-to-Rank, feature-aware factorization, Two-Tower 등이 포함될 수 있으나 구현 순서를 PRD에서 고정하지 않는다.

LLM은 향후 preference extraction 또는 recommendation explanation의 인터페이스 후보로 검토할 수 있으나, 검증 가능한 candidate/ranking 파이프라인을 대체하는 것을 기본 방향으로 두지 않는다.

---

## 5. Non-Goals

초기 버전에서는 다음을 목표로 하지 않는다.

- 추천 시스템을 전부 TypeScript로 구현
- LLM 하나로 전체 추천 파이프라인 대체
- 처음부터 GNN, Transformer, generative recommender 등 복잡한 모델 도입
- 대규모 분산 학습 시스템 구축
- 수백만~수천만 아이템 규모를 전제로 한 과도한 ANN 인프라 구축
- 실시간 online learning
- 완전한 여행 일정 자동 생성

현재 데이터와 서비스 규모에 필요한 복잡도만 도입한다.

---

## 6. Target Users

### 6.1 여행 추천 사용자

여행 지역과 기간은 정했지만 어떤 장소를 방문할지 결정하지 못한 사용자.

주요 니즈:

- 내 취향에 맞는 장소를 빠르게 찾고 싶다.
- 동반자나 여행 시기 등 이번 여행의 맥락이 반영되길 원한다.
- 너무 많은 후보보다 신뢰할 만한 상위 추천을 원한다.

### 6.2 여행지 탐색 사용자

개인화 추천을 사용하지 않더라도 지역/테마별 관광지를 탐색하고 상세 정보와 리뷰를 보고 싶은 사용자.

### 6.3 서비스 운영/개발 관점

추천 모델을 개발하고 비교하는 개발자가 다음을 확인할 수 있어야 한다.

- 어떤 데이터 버전으로 학습했는가
- 어떤 모델/파라미터인가
- 어떤 평가 프로토콜을 사용했는가
- baseline보다 실제로 좋아졌는가
- online latency가 서비스 가능한 범위인가

---

## 7. Core User Journeys

### 7.1 개인화 추천

```text
로그인 또는 추천 진입
 -> 여행 지역 선택
 -> 여행 기간 입력
 -> 여행 스타일/동반자 등 현재 여행의 취향·맥락 입력
 -> 추천 요청
 -> 현재 여행에 적합한 Top-K 관광지 조회
 -> 관광지 상세 확인
 -> 저장/선택/방문 등 상호작용
 -> 향후 일정 구성 기능과 연결 가능
```

### 7.2 관광지 탐색

```text
지역 또는 테마 선택
 -> 관광지 목록
 -> 상세 정보
 -> 리뷰 조회/작성
```

### 7.3 커뮤니티

```text
게시글 목록
 -> 게시글 상세
 -> 글 작성
 -> 댓글/좋아요
```

### 7.4 마이페이지

```text
내 정보
 -> 좋아요한 관광지/게시글
 -> 과거 추천 결과
 -> 작성한 게시글
```

---

## 8. Functional Requirements

### FR-1 Authentication

- 사용자는 소셜 로그인을 통해 인증할 수 있다.
- 인증 방식은 기존 Kakao OAuth 경험을 우선 보존하되 구현 방식은 재설계한다.
- Web과 API의 인증 책임 및 token/cookie 전략은 별도 기술 결정으로 확정한다.

### FR-2 User Travel Preference

사용자는 장기 행동 이력이 없어도 이번 여행에 필요한 정보를 명시적으로 입력해 추천을 요청할 수 있어야 한다.

초기 핵심 입력 후보:

- 여행 지역 / 목적지
- 여행 시작·종료일 또는 기간
- 여행 스타일 등 명시적 취향
- 동반자 유형 / 인원 등 현재 여행 맥락

연령대·성별 같은 demographic feature는 핵심 요청 입력으로 두지 않는다. 향후 성능 기여, 공정성, 개인정보 최소수집 및 동의 필요성을 별도로 검증한 경우에만 실험 후보로 다룬다.

### FR-3 Tour Spot Catalog

- Product / serving 관광지 카탈로그 v1은 TourAPI KorService2를 사용한다.
- 서비스 기준 식별자는 `(tourapi-korservice2, contentid)`다.
- v1 추천 가능 유형과 request-time eligibility는 [POI catalog / candidate contract](recommendation/poi-catalog-candidate-contract.md)를 따른다.
- Offline AI Hub 추천 실험의 item identity는 AI Hub native POI identity를 사용하며 TourAPI `contentid`와 동일하다고 가정하지 않는다.
- AI Hub ↔ TourAPI 식별자 연결는 별도 identity 문제이며, 공식 식별자 연결 정보·검증된 좌표 호환성·신뢰 가능한 외부 장소 식별자 같은 새 근거 없이는 heuristic 식별자 연결를 확대하지 않는다.

### FR-4 Recommendation

- 사용자는 현재 여행 맥락과 명시적으로 제공한 취향을 기반으로 Top-K 관광지를 추천받을 수 있다.
- 장기 사용자 history 없이도 핵심 추천 플로우를 사용할 수 있어야 한다.
- 여행 지역, 서비스 가능한 POI 등 명백한 product constraint는 가능한 경우 ranking 이전 후보 자격에 반영한다.
- 추천의 primary product output은 순위가 매겨진 Top-K POI이며, 자동 일정 생성·동선 최적화는 별도 제품 기능으로 취급한다.
- 추천된 POI는 사용자가 저장하거나 선택할 수 있고, 향후 itinerary 기능의 입력으로 연결할 수 있어야 한다.
- 이미 방문한 아이템 처리 방식은 evaluation 및 product rule에서 명시한다.
- 추천 API는 최소한 다음 정보를 반환할 수 있어야 한다.

```text
itemId
rank
score (외부 노출 여부는 별도 결정)
reason/features (선택)
modelVersion (내부 추적용)
```

### FR-5 Reviews

- 관광지 리뷰 목록을 조회할 수 있다.
- 인증 사용자는 리뷰를 작성/수정/삭제할 수 있다.

### FR-6 Community

- 게시글 목록 및 상세 조회
- 게시글 작성/수정/삭제
- 댓글 작성/삭제
- 좋아요

초기 MVP 범위에서 추천 시스템 개발보다 우선순위가 낮을 수 있으며, 기존 기능 복원 이슈에서 단계별 범위를 재조정한다.

### FR-7 Interaction Logging

향후 추천 학습과 성능 분석을 위해 다음 이벤트를 저장할 수 있는 구조를 마련한다.

후보 이벤트:

- RECOMMENDATION_IMPRESSION
- VIEW
- CLICK
- LIKE
- SAVE
- REVIEW
- VISIT

추천 노출 로그는 최소한 다음을 연결할 수 있어야 한다.

```text
userId
itemId
modelVersion
rank
score
context
occurredAt
```

실제 수집 이벤트와 보존 정책은 MVP 범위에서 단계적으로 결정한다.

---

## 9. Recommendation Data Strategy

### 9.1 AI Hub Source Dataset

Offline 추천 연구는 기존 프로젝트에서 사용한 AI Hub 국내 여행로그를 기준으로 한다.

활용 후보:

- traveler profile
- travel style
- trip context
- companion
- visited location
- satisfaction
- activity
- spending

기존 프로젝트의 Preference/Visited로 축약하는 과정에서 버린 feature를 확인하되, 데이터셋에 존재한다는 이유만으로 serving feature로 사용하지 않는다. 추천 시점에 실제 제품이 받을 수 있는 정보만 모델 입력 후보로 허용한다.

### 9.2 오프라인 평가와 서비스 제공의 아이템 식별자 경계

Offline 추천 실험과 product serving은 서로 다른 item identity를 사용한다.

```text
Offline recommendation experiment
AI Hub native POI identity
(region, nonblank POI_ID)
 -> candidate universe
 -> training / validation
 -> ranking evaluation

Product / serving
TourAPI KorService2
(tourapi-korservice2, contentid)
 -> CandidateRequest
 -> eligibility
 -> 서비스 호환 ranking
 -> Top-K POIs

AI Hub ↔ TourAPI
 -> 별도 식별자 연결 문제
```

Issue #4 / PR #64에서 exact title/address, POI Master, global lookup, visit fallback, name normalization, fuzzy retrieval shadow, address normalization 및 token 관계를 진단했지만 신뢰 가능한 canonical bridge로 승격할 근거를 확보하지 못했다.

따라서:

- Offline model evaluation은 AI Hub native POI identity 안에서 수행한다.
- TourAPI catalog coverage를 AI Hub positive coverage와 동일한 것으로 해석하지 않는다.
- TourAPI `contentid` 식별자 연결를 offline model selection의 선행조건으로 두지 않는다.
- fuzzy/title/address heuristic 또는 token overlap만으로 `MATCHED`를 추가하지 않는다.
- serving 단계에서 사용할 모델·feature·item representation은 TourAPI 서비스용 식별자와 호환됨을 별도로 검증해야 한다.

상세 근거는 [POI catalog / candidate contract](recommendation/poi-catalog-candidate-contract.md)와 Issue #66의 실제 검증 후 적용 범위 수정을 따른다.

### 9.3 오프라인 추천 데이터셋

추천 모델은 애플리케이션 엔티티에 직접 의존하기보다 학습·평가에 적합한 offline dataset을 사용한다.

논리 구조:

```text
travelers
trip_contexts
poi_items
observed_interactions
optional_post_event_feedback
```

현재 offline item은 AI Hub native POI identity를 사용한다. 이 데이터셋을 TourAPI 서비스용 카탈로그의 canonical identity와 동일한 것으로 부르지 않는다.

실제 저장 형식과 feature schema는 #41의 model-training-evaluation contract에서 확정한다.

---

## 10. 추천 평가

추천 알고리즘 고도화의 전제는 공통 evaluation protocol이다.

### 10.1 Split

현재 baseline contract는 AI Hub source role을 보존해 **TL을 train, VL을 validation으로 사용하는 임시 규칙**을 둔다. 이는 TL/VL의 독립성, 공식 무작위화 또는 시간 순서를 보장한다는 뜻이 아니다.

#41에서는 다음을 비교해 model-development split을 확정한다.

- TL 내부 grouped split을 별도로 둘 필요가 있는지
- VL을 external / 콜드 스타트 generalization evaluation으로 보존할지
- traveler·trip·POI overlap과 leakage를 어떻게 통제할지
- 독립 test 역할을 어떤 승인된 데이터에서 확보할지

단순 random row split이나 temporal split을 이유만으로 자동 채택하지 않는다. 동일 `TRAVEL_ID`의 interaction과 feedback은 partition을 넘지 않게 유지한다.

독립 test source/protocol이 확정되기 전까지 test metric을 생성하지 않는다.

### 10.2 Initial Metrics

추천의 primary task는 Top-K ranking으로 두고 다음 지표를 공통 기준으로 검토한다.

- Precision@K
- Recall@K
- NDCG@K
- MRR
- recommendation coverage

rating/preference prediction을 학습 과정에서 사용할 경우 RMSE/MAE를 diagnostic으로 추가할 수 있으나, 회귀 오차만으로 추천 모델 우수성을 결론 내리지 않는다.

Observed visit은 implicit positive로 사용할 수 있지만, unvisited item은 자동 negative가 아니다. sampling이 필요한 모델은 sampling 규칙과 seed를 실험 계약에 명시한다.

### 10.3 Evaluation Requirements

- 모든 모델은 동일한 데이터 split을 사용한다.
- 데이터 leakage를 방지한다.
- 콜드 스타트 사용자/아이템을 별도로 분석한다.
- 추천 품질뿐 아니라 inference latency와 메모리 사용량도 함께 기록한다.

---

## 11. 추천 서비스 제공 원칙

기존처럼 요청 때마다 대규모 전처리와 similarity matrix를 재구축하지 않는다.

Offline 연구와 online serving의 identity 경계를 명시적으로 유지한다.

```text
Offline research
AI Hub native POI interactions
 -> preprocessing
 -> training
 -> evaluation
 -> experiment artifact / decision evidence

Online product
request
 -> traveler preference + trip context
 -> CandidateRequest
 -> TourAPI 서비스용 카탈로그 eligibility
 -> 서비스 호환 ranking
 -> Top-K TourAPI POIs
 -> save/select
 -> optional future itinerary flow
```

AI Hub native POI를 대상으로 학습한 실험 artifact를 TourAPI `contentid` serving artifact로 자동 간주하지 않는다. 실제 online model은 serving item identity와 feature availability가 호환되는지 별도 검증 후 연결한다.

아이템 규모가 수만 개 수준이라면 복잡한 vector DB/ANN을 필수 조건으로 두지 않는다. brute-force scoring의 실제 latency를 먼저 측정한 뒤 필요할 때 ANN을 도입한다.

---

## 12. System Architecture

```text
Browser
  |
  v
Next.js Web
  |
  v
NestJS API
  |\
  | +------> Product Database
  |
  +--------> Recommendation Service
                |
                +--> 서비스 호환 model / feature artifact
                +--> TourAPI candidate identity

Offline Recommendation Research
AI Hub native POI interactions
  -> preprocessing
  -> training
  -> evaluation
  -> experiment tracking
  -> research artifact / model decision

Product Catalog
TourAPI KorService2
  -> versioned serving snapshot
  -> request-time eligibility
  -> Top-K serving POIs

AI Hub POI ↔ TourAPI contentid
  -> 향후 필요 시 식별자 연결
  -> not required for offline model comparison
```

### Architecture Principle

- NestJS API는 product/domain orchestration을 담당한다.
- Python recommendation 영역은 학습·평가·추천 계산을 담당한다.
- recommendation service가 product DB의 내부 schema를 자유롭게 조회하는 구조는 지양한다.
- Offline research identity와 서비스용 카탈로그 identity를 암묵적으로 합치지 않는다.
- 데이터 전달 방식은 batch export, feature dataset, internal API 등 후보를 비교해 결정한다.

---

## 13. Initial Technology Direction

확정 사항:

- Next.js
- NestJS
- TypeScript for Web/API
- Python for Recommendation

검토 예정:

- PostgreSQL
- ORM: Prisma / Drizzle / TypeORM 비교
- Python dependency/package management
- MLflow 운영 방식
- model serving: FastAPI 또는 대안
- monorepo tooling
- shared contract validation 방식

기술 선택은 "많이 쓰인다"는 이유만으로 확정하지 않고, 프로젝트 요구와 학습 목적을 함께 고려한다.

---

## 14. Non-Functional Requirements

### NFR-1 Recommendation Latency

초기에는 절대 목표치를 임의로 고정하지 않는다. 기존 구현과 baseline을 측정한 뒤 목표를 설정한다.

측정 항목:

- p50 / p95 recommendation latency
- candidate retrieval time
- ranking time
- API end-to-end latency

### NFR-2 Reproducibility

모든 주요 추천 실험은 다음 정보를 추적할 수 있어야 한다.

- dataset version
- code git SHA
- model type
- hyperparameters
- metrics
- model artifact
- training duration

### NFR-3 Observability

운영 메모리 사용량 같은 내부 telemetry를 business API response에 포함하지 않는다.

향후 다음을 로그/메트릭으로 분리한다.

- latency
- error rate
- recommendation model version
- model load state

### NFR-4 Maintainability

- Web/API/Recommendation 경계를 명확히 유지한다.
- API controller에 persistence, mapping, external orchestration 책임이 집중되지 않게 한다.
- 추천 feature/experiment 코드를 serving 코드와 가능한 한 분리한다.

---

## 15. MVP Scope Proposal

### Phase 0 — Discovery & Recovery

- 기존 TravelMate 기능/API/DB 구조 복원
- 기존 추천 코드 및 데이터 흐름 분석
- AI Hub 데이터 재확보
- AI Hub ↔ TourAPI 식별자 연결 방식 타당성 검증 완료
- Offline AI Hub identity와 TourAPI 서비스용 식별자를 별도 책임으로 분리

### Phase 1 — Recommendation Baseline & Contract

- AI Hub native POI 기반 offline candidate/evaluation contract 확정
- popularity baseline 유지
- User-CF / Item-CF feasibility 결과 반영
- prediction unit, label, feature availability, split, 콜드 스타트 cohort, ranking metric 확정
- `model-training-evaluation-contract.md` 작성
- 후속 모델 후보를 동일한 계약에서 비교할 수 있는 실험 구조 마련

### Phase 2 — New Product Foundation

- Next.js 기본 앱 구조
- NestJS 기본 API 구조
- 핵심 domain/API contract 정의
- Product DB 재설계
- 인증 및 TourAPI integration 기본 구현

### Phase 3 — Personalized Ranking / Retrieval

- #41 계약에 맞는 feature-capable 모델 실험
- 필요 시 Learning-to-Rank, feature-aware factorization, Two-Tower 등 후보 비교
- baseline 대비 ranking / coverage / 콜드 스타트 trade-off 비교
- 서비스용 식별자와 특성 호환성가 검증된 online artifact/serving contract 정의
- NestJS와 recommendation service 연동

### Phase 4 — Feedback Loop

- recommendation impression logging
- click/like/save/visit interaction logging
- 실제 서비스 데이터 기반 평가 체계 준비

---

## 16. 성공 기준

초기 프로젝트 성공은 특정 모델을 구현했다는 사실만으로 판단하지 않는다.

다음 조건을 만족하는 것을 목표로 한다.

1. 기존 추천 파이프라인의 문제와 개선 이유를 설명할 수 있다.
2. 동일한 offline data/evaluation contract에서 서로 다른 추천 접근을 비교할 수 있다.
3. 선택한 후속 모델이 baseline 대비 ranking, coverage, 콜드 스타트에서 어떤 trade-off를 갖는지 수치로 설명할 수 있다.
4. 추천 serving이 요청마다 전체 데이터 전처리를 반복하지 않는다.
5. 데이터셋/코드/모델/metric을 특정 experiment run으로 재현할 수 있다.
6. Next.js/NestJS/Recommendation service 간 책임이 명확하다.
7. Offline AI Hub item identity와 TourAPI 서비스용 식별자의 책임이 명확히 분리되어 있다.
8. Product serving 결과는 TourAPI canonical identity를 사용하며, offline AI Hub ↔ TourAPI 식별자 연결를 암묵적으로 전제하지 않는다.

---

## 17. 미결정 질문

다음은 구현 전에 추가 논의가 필요한 항목이다.

### Product

- 커뮤니티 기능을 리뉴얼 MVP에 포함할 것인가, 후순위로 둘 것인가?
- 사용자가 추천을 요청할 때 필수로 입력해야 하는 정보는 어디까지인가?
- 추천 결과를 몇 개 보여줄 것인가?
- 추천 이유(explanation)를 초기부터 제공할 것인가?

### Data

- AI Hub 2022/2023 데이터의 정확한 라이선스 및 재배포 가능 범위는 무엇인가?
- 과거 AI Hub ↔ TourAPI mapping 결과를 복원할 수 있는가?
- 만족도/소비/활동 feature 중 실제 추천에 유효한 것은 무엇인가?
- 성별 등 demographic feature를 계속 사용할 필요가 있는가?

### Recommendation

제품 수준의 방향은 **현재 여행 맥락에서 후보 POI를 랭킹해 Top-K로 제공하는 것**으로 정리했다.

#41에서 남은 세부 계약:

- prediction unit을 어떤 schema로 고정할 것인가?
- traveler preference와 trip context 중 어떤 feature를 serving-time allowlist로 허용할 것인가?
- observed visit을 primary relevance로 유지할지, post-event preference signal을 어떤 보조 label로 사용할 것인가?
- unobserved item과 sampled pseudo-negative를 어떻게 구분할 것인가?
- TL 내부 model-development split과 공식 VL의 external/콜드 스타트 역할을 어떻게 나눌 것인가?
- user/item/context 콜드 스타트 cohort를 어떤 기준으로 정의할 것인가?
- offline 연구 결과를 서비스 호환 model/feature contract로 옮길 때 어떤 parity 검증이 필요한가?

AI Hub ↔ TourAPI 식별자 연결 자체는 #41의 model selection 선행조건으로 두지 않는다.

### Architecture

- monorepo를 사용할 것인가?
- PostgreSQL/ORM 조합은 무엇으로 할 것인가?
- Python recommendation service가 필요한 feature를 어떻게 공급받을 것인가?
- offline training job과 online serving 배포를 어떻게 분리할 것인가?

---

## 18. Related Initial Issues

- #1 기존 TravelMate 기능·API·서비스 계약 복원
- #2 리뉴얼 목표 아키텍처와 서비스 경계 정의
- #3 AI Hub 여행로그 원본 데이터와 과거 전처리 과정 복원
- #4 AI Hub 방문지와 TourAPI 관광지 매핑 전략 재설계
- #5 추천 시스템 오프라인 평가 프로토콜 정의
- #6 추천 baseline 구현: Popularity, Content-based, Matrix Factorization
- #7 Two-Tower 추천 모델 실험 설계
- #8 추천 실험 추적 환경 설계: MLflow 및 Optuna
- #9 Next.js 프론트엔드 마이그레이션 전략 수립
- #10 NestJS 백엔드 마이그레이션 전략 수립

---

## 19. 추천 제품 참고 자료

유사 여행 추천 제품의 공개 사용자 경험과 이번 프로젝트에 대한 Adopt / Experiment / Defer 판단은 다음 문서에서 관리한다.

- [Travel Recommendation Product Reference Analysis](recommendation/product-reference-analysis.md)
- Issue #41 — 여행 추천 제품·모델 계약 확정

제품 조사는 내부 알고리즘을 추측하기 위한 근거가 아니라, 사용자가 제공하는 입력과 서비스가 반환해야 하는 경험을 검증하기 위한 자료로 사용한다.

---

## 20. PRD Change Policy

이 문서는 제품 요구사항과 기술 방향의 기준을 정리한다. 요구사항과 기술 선택은 기존 시스템 분석, 데이터셋 스키마 확인, 추천 baseline 실험, 기술·아키텍처 결정의 근거가 추가될 때 갱신한다.

1. 기존 시스템 분석
2. 데이터셋 스키마 확인
3. recommendation baseline 실험
4. 기술/아키텍처 결정

특히 아직 검증되지 않은 기술 선택이나 모델을 제품 요구사항처럼 고정하지 않는다. 의사결정 근거와 실험 결과가 생길 때마다 PRD와 별도 architecture decision 문서를 함께 갱신한다.
