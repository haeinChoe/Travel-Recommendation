# Travel Recommendation PRD

>
> Last updated: 2026-10-28

## 문서 상태와 한눈에 보는 결론

**이 문서가 답하려는 질문:** 어떤 여행 문맥과 장소 정보를 바탕으로 추천 적합도를 학습하고 Top-K 장소를 제안할 것인가?

**현재 기준:** 프로젝트의 최상위 문제와 결정 우선순위는 [추천 문제 정의 v2](recommendation/problem-definition-v2.md) 및 #94를 따른다. 이 PRD는 제품 방향을 설명하며 세부 후보·feature·모델 계약을 새로 확정하지 않는다.

> **여행자/여행 문맥 특징 + 장소 특징 + 관측 방문 기록으로 여행자-장소 적합도를 학습하고 Top-K를 추천할 수 있는가?**

- 장기 사용자 방문 이력이 없어도 현재 여행 문맥으로 추천받을 수 있어야 한다.
- 관측 방문은 초기 implicit-positive 학습 후보이며, 미관측 장소의 노출·불호를 뜻하지 않는다.
- AI Hub POI Master 전체를 제품상 추천 목록으로 보지 않는다. 추천 자격과 요청별 후보 생성은 구분한다.
- TourAPI KorService2는 제품/서빙용 POI 카탈로그다. AI Hub와 TourAPI 식별자 브리지는 별도 문제다.
- CatBoost는 모델 후보 중 하나다. 후보 생성은 실제 규모·비용 문제가 확인될 때만 검토한다.
- 공식 VL은 최종 configuration 잠금 전까지 사용하지 않으며, #83의 최종 holdout으로 둔다.

**아직 결정되지 않은 것:** 추천 POI의 제품 범위, 기존 tourism_core 양성 코호트의 v2 적용 여부, AI Hub offline candidate eligibility, #95 feature 채택과 serving parity, #96 로그의 세부 계약, 후보 생성 필요성, 최종 모델/objective/primary metric.

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

사용자가 현재 여행 상황과 명시적으로 제공한 취향을 입력하면, 서비스는 추천 자격을 갖춘 장소 중에서 여행자와 장소 사이의 적합도를 평가해 Top-K를 제안한다. 장기 사용자 방문 이력 없이도 작동하는 cold-user 흐름을 지원한다.

> "부모님과 10월에 제주를 가는데 너무 많이 걷지 않고 조용한 장소 위주로 추천해줘"

자연어 입력을 추가하더라도 후보 자격, feature와 ranking은 검증 가능한 계약에 따라야 한다. 제품 범위와 어떤 장소를 추천할지는 별도 결정이며 AI Hub Master 모든 행이 추천 대상이라는 뜻은 아니다.

Offline 학습·평가와 product serving의 장소 식별자 경계는 유지한다.

- Offline 학습·평가: AI Hub native (region, POI_ID)
- Product/serving catalog: TourAPI KorService2 (tourapi-korservice2, contentid)
- AI Hub ↔ TourAPI: 별도 identity bridge

#69의 Stage 5는 전체 관측 양성 97,640건 중 26,454건(27.09%)을 연결했고, 권역 조건이 적용된 적격 TourAPI 후보 19,051개 중 2,753개(14.45%)에 시드를 제공했다. 이는 해당 보고서의 분모와 매칭 정책을 가진 개선 결과다. #4의 과거 기준값은 역사 기록으로 보존하며 최신 Stage 5 성과를 대체하지 않는다. 상세 내용은 [POI catalog contract](recommendation/poi-catalog-candidate-contract.md)와 [#69 v2 보고서](recommendation/experiments/poi-identity-matching-v2.md)를 따른다.

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

추천 제품의 상위 문제는 여행자·현재 여행 문맥과 장소 특징, 관측 방문 기록을 이용해 적합도를 학습하고 Top-K 장소를 제안하는 것이다. 단순한 입력·출력 계약은 [추천 문제 정의 v2](recommendation/problem-definition-v2.md)를 따른다.

- 장기 사용자 history가 없는 cold-user 요청을 지원한다.
- 추천 자격(candidate eligibility)과 요청별 후보 생성(candidate generation)을 구분한다.
- 모델이 점수화할 장소는 제품 범위와 데이터 근거를 확인해 정한다. AI Hub POI Master 전체를 추천 가능하다고 가정하지 않는다.
- 요청 문맥과 정적·과거 장소 특징의 serving 재현 가능성을 검증한다.
- 특정 모델이나 검색 구조를 제품 요구사항처럼 먼저 고정하지 않는다. CatBoost는 후보 모델이다.
- 후보 집합 coverage와 순위 모델 성능을 별도로 평가한다.

후보가 적고 점수화 비용이 감당 가능하면 적합도 점수화로 진행할 수 있다. 후보 수나 latency가 실제 제약으로 확인될 때만 retrieval/candidate-generation 계층을 검토한다. Two-Tower, ANN, LLM은 필요성이 확인되기 전까지 보류한다.

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

- Product/serving 관광지 카탈로그 v1은 TourAPI KorService2를 사용하며 서비스 식별자는 (tourapi-korservice2, contentid)다.
- AI Hub의 (region, POI_ID)는 다른 식별자 공간이다.
- AI Hub ↔ TourAPI 연결은 별도 브리지 계약이다. #69의 Stage 5 개선 결과(26,454 / 97,640 관측 양성; 적격 카탈로그 2,753 / 19,051 시드)를 보존하고, #4의 구 기준 수치로 대체하지 않는다.
- 브리지 coverage는 전체 후보의 추천 자격이나 offline AI Hub 학습 eligibility를 결정하지 않는다.
- 어떤 유형을 제품이 추천할지는 아직 미결정이다. 상세 카탈로그 사실과 브리지 범위는 [POI catalog contract](recommendation/poi-catalog-candidate-contract.md)를 따른다.

### FR-4 Recommendation

- 사용자는 현재 여행의 문맥과 장소 특징을 이용한 적합도 점수에 따라 Top-K 추천을 받을 수 있어야 한다.
- 장기 사용자 history 없이도 핵심 요청 흐름을 지원한다.
- 추천 자격과 request별 candidate generation은 별도 계약으로 다룬다.
- 새 장소나 행동 이력이 희소한 장소도 정적 속성으로 표현할 수 있어야 한다.
- 특정 model/objective, candidate universe 또는 reranker 역할을 미리 고정하지 않는다.
- 추천 결과는 저장/선택 등의 후속 행동과 연결할 수 있다. 이미 방문한 장소를 어떻게 처리할지는 제품·평가 규칙에서 별도 결정한다.
- 추천 API는 최소한 다음 반환 정보를 제공할 수 있어야 한다. 제품 요구사항이 축소된 것으로 오해하지 않도록 v1에서 정의한 필수·선택·내부 추적 항목을 유지한다.

```text
itemId           장소 식별자 (필수)
rank             추천 순위 (필수)
score            추천 점수 (외부 노출 여부는 별도 결정)
reason/features  추천 이유·특징 (선택)
modelVersion     모델 버전 (내부 추적용, 외부 노출 여부는 별도 결정)
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

#96에서 서비스 상호작용 로그의 의미와 최소 수집 신호를 설계한다. AI Hub는 출시 전 초기 학습 데이터이고, 실제 서비스 로그는 운영 이후 장소 행동 feature와 평가 신호를 점차 보완할 수 있다.

- 요청 문맥과 추천 노출(impression)을 구분해 연결한다.
- 상세 조회/클릭, 저장, 제품에 존재할 때 일정 추가를 기록 후보로 둔다.
- 실제 방문 확인과 명시적 feedback은 선택 기능이다.
- 노출되지 않은 장소와 노출 후 선택하지 않은 장소는 다른 상태다. 후자도 자동으로 불호를 뜻하지 않는다.
- GPS 자동 방문 추정은 기본 요구사항이 아니다.
- 정확한 DB schema, 보존 기간, 동의 정책과 구현 기술은 후속 구현 이슈에서 정한다.

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

Offline 추천 실험과 product serving은 구분된 item identity와 후보 계약을 사용한다.

~~~
Offline recommendation research
AI Hub native (region, POI_ID)
 -> 학습·개발용 offline candidate/evaluation
 -> 적합도 모델과 ranking 진단

Product / serving
TourAPI KorService2 (tourapi-korservice2, contentid)
 -> product catalog
 -> 제품 범위에 맞춘 추천 자격
 -> 적합도 점수화와 Top-K

AI Hub ↔ TourAPI
 -> #69에서 검증·개선한 별도 식별자 브리지
~~~

#69 Stage 5 보고서 결과는 전체 관측 양성 97,640건 중 26,454건(27.09%) matched, 권역이 제한된 적격 catalog 19,051개 중 2,753개(14.45%)에 seed가 연결된 것이다. #4의 과거 수치는 과거 snapshot/scope를 가진 baseline으로 역사 문서에 보존한다. 최신 Stage 5 결과를 과거 baseline 수치로 덮지 않으며, 두 결과의 분모·시점·scope를 섞어 비교하지 않는다.

- AI Hub 학습 관측치 자격은 TourAPI 매칭 여부와 별개로 판단한다.
- TourAPI 카탈로그 coverage를 AI Hub 관측 양성 coverage와 같다고 해석하지 않는다.
- identity bridge가 연결하지 않은 장소는 UNMATCHED 또는 현재 정책으로 identity를 확정하지 못한 상태이지, 장소가 없다는 증거가 아니다.
- 매칭된 seed subset은 신호 전달 실험에 쓸 수 있으나 전체 카탈로그 feature parity를 보증하지 않는다.

상세한 버전별 분모·매칭 정책·한계는 [POI catalog contract](recommendation/poi-catalog-candidate-contract.md)와 [#69 v2 matching report](recommendation/experiments/poi-identity-matching-v2.md)를 따른다.

### 9.3 오프라인 추천 데이터셋

추천 모델은 앱의 product entity에 직접 의존하기보다 학습·평가 목적의 별도 데이터셋을 사용한다.

~~~text
trip/request context
POI attributes
observed visit interactions
optional post-visit feedback
~~~

실제 Parquet 출력 형식과 field contract는 [standard training dataset schema](recommendation/training-dataset-schema.md)를 따른다. 그 문서에서 TL→train/VL→validation이라고 부르는 것은 변환 출력의 source-role 이름이다. 이는 모델 선택에서 공식 VL을 tuning에 쓰도록 허용하는 뜻이 아니다.

온라인 feature의 serving parity와 v2 label/candidate 적용 여부는 상위 [추천 문제 정의 v2](recommendation/problem-definition-v2.md) 및 후속 #95/#96에서 확인한다.

## 10. 추천 평가

오프라인 평가는 현재 문제와 후보 정책을 진단하기 위한 개발 근거다. 평가 결과를 product satisfaction이나 실제 노출 성과와 동일시하지 않는다. 세부 프로토콜과 이력은 [추천 문제 정의 v2](recommendation/problem-definition-v2.md)와 연결된 전문 문서를 따른다.

### 10.1 Split과 holdout

- TL은 개발 데이터다. cold-user 모델 선택은 TL 내부의 (region, TRAVELER_ID) group split으로 inner-train과 inner-validation을 나눈다.
- 동일 여행자의 여행은 inner split 경계를 넘지 않는다. 행동 집계와 sampling 통계는 inner-train에서만 계산한다.
- 공식 VL은 configuration 잠금 전까지 tuning에 사용하지 않는 최종 holdout이다. #83에서만 잠금된 후보·feature·model을 평가한다.
- 데이터 변환 schema에서 TL→train, VL→validation이라고 명명하는 것은 출력 역할이다. 위의 모델 선택 split과 구분한다.
- 독립적인 추가 test source/protocol은 아직 결정되지 않았다. 이 이름을 공식 VL과 혼동하지 않는다.

### 10.2 Labels와 metrics

- 관측 방문은 baseline용 implicit-positive 후보이며 만족/선호를 확정하지 않는다.
- 미관측 item은 unknown이다. sampled-unobserved의 label 0은 학습 비교용이지 observed dislike가 아니다.
- 후보 coverage 및 누락 positive 진단을 ranking metric과 별도로 기록한다.
- NDCG@K, Recall@K, MRR@K, HitRate@K는 기존 비교 지표 후보다. primary metric과 K의 최종 선택은 미결정이다.
- 추천 지표는 offline observed visit retrieval/ranking만 평가하고 클릭·저장·만족도를 직접 측정하지 않는다.

### 10.3 평가 요구사항

- 모델 비교는 같은 후보, split, label, feature 범위와 metric 설정을 사용한다.
- 요청 이후 또는 inner-validation/VL에서 파생한 정보가 feature에 들어가지 않게 한다.
- 사용자 cold-start와 item cold-start의 평가 집단과 분모를 따로 설명한다.
- latency 및 memory는 실제 범위와 후보 정책이 정해진 뒤 측정한다.

## 11. 추천 서비스 제공 원칙

Offline 연구와 online serving은 데이터 원천, 식별자, 시점별 feature와 실제 제품 후보 범위를 구분한다.

~~~
서비스 요청 문맥
 -> 추천 자격을 만족하는 product catalog POI
 -> (필요가 확인되면 선택적 후보 생성)
 -> traveler-context ↔ POI 적합도 점수화
 -> Top-K TourAPI POIs
 -> impression / click / save / optional visit / feedback
~~~

AI Hub 기반 학습 결과를 TourAPI contentid serving 결과로 자동 간주하지 않는다. 각 feature가 요청 시점에 같은 의미로 공급되는지 확인하고, bridge 기반 신호는 매칭된 범위 안에서 해석한다.

추천 자격을 만족하는 item 수와 end-to-end latency가 직접 점수화를 감당할 수 있으면 retrieval 계층은 필요하지 않을 수 있다. 규모·비용이 실제 제약으로 확인될 때만 candidate generation을 검토한다. ANN이나 vector database는 사전 요구사항이 아니다.

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
  -> not required for 오프라인 모델 comparison
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
- AI Hub ↔ TourAPI 식별자 연결 방식의 타당성 검증 완료
- Offline AI Hub identity와 TourAPI 서비스용 식별자를 별도 책임으로 분리

### Phase 1 — Recommendation Problem & Evidence

- #97의 단일 추천 문제 정의를 우선 적용한다.
- #95 POI Rich Feature와 #96 서비스 로그 계약으로 입력 신호와 feature 출처를 검증한다.
- 제품 범위와 추천 자격을 정한 뒤 간단한 적합도 모델로 다시 평가한다.
- #82의 기존 full-catalog direct-scoring search는 v2 후보 정책 전까지 보류한다.
- 공식 VL은 최종 configuration을 잠근 뒤 #83에서 평가한다.

### Phase 2 — New Product Foundation

- Next.js 기본 앱 구조
- NestJS 기본 API 구조
- 핵심 domain/API contract 정의
- Product DB 재설계
- 인증 및 TourAPI integration 기본 구현

### Phase 3 — Personalized Ranking / Retrieval

- 확인된 문제·feature·candidate·split contract에서 모델 후보를 비교한다.
- 후보 수와 end-to-end latency가 요구를 넘는 경우에만 retrieval/candidate generation을 추가한다.
- offline AI Hub 평가와 TourAPI serving parity를 별도로 검증한다.
- 결과가 잠긴 뒤 #83에서 official VL을 최종 holdout으로 사용한다.

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
8. 제품 서비스 결과는 TourAPI 기준 식별자를 사용하며, 오프라인 AI Hub ↔ TourAPI 식별자 연결을 암묵적으로 전제하지 않는다.

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

이 항목의 현재 기준과 용어는 [추천 문제 정의 v2](recommendation/problem-definition-v2.md)에서 관리한다.

아직 제품 및 실험 근거가 필요한 결정:

- 추천 가능한 장소의 제품 범위: 관광·문화·체험·레저와 음식·쇼핑·숙박 포함 범위
- 기존 tourism_core 관측 양성 코호트의 v2 적용 여부
- AI Hub offline candidate eligibility와 Master/interaction의 identity·coverage 규칙
- #95에서 채택할 POI static/historical feature 및 서비스 재현 가능성
- #96 interaction log의 구현 범위와 feedback 신호
- direct scoring 비용이 후보 생성 계층을 요구하는지
- 최종 relevance contract, model/objective, primary ranking metric과 K
- 모델·feature·후보 configuration 잠금 시점과 #83 공식 VL 평가

#69의 TourAPI identity bridge 개선은 완료된 별도 근거다. 오프라인 학습 자격의 선행 조건이 아니며, 최신 수치는 [#69 report](recommendation/experiments/poi-identity-matching-v2.md)에 보존한다.

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
