# Travel Recommendation PRD (Draft)

> Status: Draft
> 
> Last updated: 2026-09-09

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

사용자가 여행 상황과 취향을 입력하면, 서비스가 최신 관광지 카탈로그와 사용자 선호/행동을 바탕으로 관련성이 높은 여행지를 빠르게 추천하고, 사용자의 실제 상호작용을 통해 추천 품질을 지속적으로 개선할 수 있는 구조를 만든다.

장기적으로는 다음과 같은 경험을 지원할 수 있어야 한다.

> "부모님과 10월에 제주를 가는데 너무 많이 걷지 않고 조용한 장소 위주로 추천해줘"

이때 자연어 해석 기능을 사용하더라도 실제 추천 후보 생성과 랭킹은 검증 가능한 추천 모델과 카탈로그 데이터를 기반으로 수행하는 것을 기본 방향으로 한다.

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

첫 단계에서는 최신 모델 자체보다 평가 가능한 baseline을 만드는 것을 우선한다.

비교 후보:

1. Popularity
2. Content-based
3. Matrix Factorization
4. Two-Tower retrieval

후속 후보:

- 별도 ranking model
- Sequential recommendation (예: SASRec 계열)
- Graph recommendation (예: LightGCN 계열)
- LLM 기반 preference extraction / recommendation explanation

후속 모델은 baseline 대비 개선을 확인할 수 있을 때만 도입한다.

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
로그인
 -> 여행 지역 선택
 -> 여행 기간 입력
 -> 여행 스타일/동반자 등 취향 입력
 -> 추천 요청
 -> 개인화된 Top-K 관광지 조회
 -> 관광지 상세 확인
 -> 좋아요/저장/방문 등 상호작용
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

사용자는 추천에 필요한 여행 정보를 입력할 수 있어야 한다.

초기 후보:

- 여행 지역
- 여행 시작/종료일
- 연령대
- 성별 (필요성과 활용 방식 재검토)
- 여행 스타일
- 동반자 유형/인원

개인정보 또는 민감할 수 있는 feature는 추천 성능 기여와 필요성을 검토한 뒤 최소화한다.

### FR-3 Tour Spot Catalog

- 관광지는 하나의 canonical ID로 식별되어야 한다.
- 최신 관광지 메타데이터는 한국관광공사 TourAPI를 주요 source로 검토한다.
- 지역, 카테고리/테마, 위치, 설명 등 추천 및 탐색에 필요한 메타데이터를 제공한다.

### FR-4 Recommendation

- 사용자는 현재 여행 맥락을 기반으로 Top-K 관광지를 추천받을 수 있다.
- 이미 방문한 아이템 처리 방식은 evaluation 및 product rule에서 명시한다.
- 신규 사용자에 대해서도 preference/content/popularity 기반 fallback을 제공한다.
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

### 9.1 Historical Dataset

기존 프로젝트에서 사용한 AI Hub 국내 여행로그 데이터를 재확보하고 원본 스키마를 분석한다.

활용 후보:

- traveler profile
- travel style
- trip context
- companion
- visited location
- satisfaction
- activity
- spending

기존 프로젝트의 Preference/Visited로 축약하는 과정에서 버린 feature를 확인한다.

### 9.2 Item Catalog Mapping

AI Hub 방문지와 TourAPI 관광지는 서로 다른 식별 체계를 사용하므로 entity resolution 과정이 필요하다.

매핑 후보:

1. exact name
2. name + address
3. geographic distance
4. fuzzy name matching
5. manual review fallback

각 매핑에는 가능하면 다음 정보를 남긴다.

```text
sourceVisitId
tourApiContentId
matchMethod
matchScore
```

### 9.3 Canonical Recommendation Dataset

추천 모델은 애플리케이션 엔티티에 직접 의존하기보다 학습/평가에 적합한 canonical dataset을 사용하도록 한다.

논리 구조:

```text
users
items
interactions
trip_context
```

실제 저장 형식은 데이터 분석 이후 결정한다.

---

## 10. Recommendation Evaluation

추천 알고리즘 고도화의 전제는 공통 evaluation protocol이다.

### 10.1 Split

가능하면 temporal split을 우선한다.

예:

```text
과거 interaction -> train
그 이후 interaction -> validation/test
```

사용자별 데이터 밀도와 여행 단위 구조를 검토한 뒤 정확한 split 규칙을 결정한다.

### 10.2 Initial Metrics

- Recall@K
- NDCG@K
- HitRate@K

필요하면 Precision@K, coverage, diversity 등을 후속 추가한다.

### 10.3 Evaluation Requirements

- 모든 모델은 동일한 데이터 split을 사용한다.
- 데이터 leakage를 방지한다.
- cold-start 사용자/아이템을 별도로 분석한다.
- 추천 품질뿐 아니라 inference latency와 메모리 사용량도 함께 기록한다.

---

## 11. Recommendation Serving Principles

기존처럼 요청 때마다 대규모 전처리와 similarity matrix를 재구축하지 않는다.

목표 구조:

```text
Offline
raw data
 -> preprocessing
 -> training
 -> embeddings/model artifact
 -> evaluation
 -> model version

Online
request
 -> user/context features
 -> candidate retrieval
 -> optional ranking
 -> filtering
 -> Top-K
```

아이템 규모가 수만 개 수준이라면 복잡한 vector DB/ANN을 필수 조건으로 두지 않는다. brute-force vector scoring의 실제 latency를 먼저 측정한 뒤 필요할 때 ANN을 도입한다.

---

## 12. System Architecture (Draft)

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
                +--> model/embedding artifact
                +--> recommendation runtime

Offline Recommendation Pipeline
AI Hub / Product interactions / TourAPI catalog
  -> preprocessing
  -> training
  -> evaluation
  -> experiment tracking
  -> versioned artifact
```

### Architecture Principle

- NestJS API는 product/domain orchestration을 담당한다.
- Python recommendation 영역은 학습/평가/추천 계산을 담당한다.
- recommendation service가 product DB의 내부 schema를 자유롭게 조회하는 구조는 지양한다.
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
- AI Hub ↔ TourAPI mapping 과정 복원

### Phase 1 — Recommendation Baseline

- canonical dataset 정의
- evaluation protocol 구현
- popularity baseline
- content-based baseline
- matrix factorization baseline
- MLflow 기반 결과 비교

### Phase 2 — New Product Foundation

- Next.js 기본 앱 구조
- NestJS 기본 API 구조
- 핵심 domain/API contract 정의
- Product DB 재설계
- 인증 및 TourAPI integration 기본 구현

### Phase 3 — Personalized Retrieval

- Two-Tower 실험
- baseline 대비 성능 비교
- online artifact/serving contract 정의
- NestJS와 recommendation service 연동

### Phase 4 — Feedback Loop

- recommendation impression logging
- click/like/save/visit interaction logging
- 실제 서비스 데이터 기반 평가 체계 준비

---

## 16. Success Criteria

초기 프로젝트 성공은 단순히 "Two-Tower를 구현했다"로 판단하지 않는다.

다음 조건을 만족하는 것을 목표로 한다.

1. 기존 추천 파이프라인의 문제와 개선 이유를 설명할 수 있다.
2. 동일 데이터/동일 protocol에서 최소 3개 baseline을 비교할 수 있다.
3. Two-Tower 또는 후속 모델이 baseline 대비 어떤 trade-off를 갖는지 수치로 설명할 수 있다.
4. 추천 serving이 요청마다 전체 데이터 전처리를 반복하지 않는다.
5. 데이터셋/코드/모델/metric을 특정 experiment run으로 재현할 수 있다.
6. Next.js/NestJS/Recommendation service 간 책임이 명확하다.
7. 추천 결과가 canonical TourSpot과 연결된다.

---

## 17. Open Questions

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

- 추천 target을 `next visited attraction`으로 정의할지, 여행 단위의 `set of preferred attractions`으로 정의할지?
- negative sampling을 어떻게 구성할 것인가?
- region filtering을 retrieval 이전에 적용할지 이후에 적용할지?
- Matrix Factorization baseline은 ALS/BPR 중 무엇을 우선할 것인가?
- Two-Tower의 user history representation을 초기에는 어떤 방식으로 구성할 것인가?

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

## 19. PRD Change Policy

이 문서는 초안이며, 다음 과정에서 계속 수정한다.

1. 기존 시스템 분석
2. 데이터셋 스키마 확인
3. recommendation baseline 실험
4. 기술/아키텍처 결정

특히 아직 검증되지 않은 기술 선택이나 모델을 제품 요구사항처럼 고정하지 않는다. 의사결정 근거와 실험 결과가 생길 때마다 PRD와 별도 architecture decision 문서를 함께 갱신한다.
