# 추천 문제 정의 v2 — 단일 기준

> **여행자/여행 문맥 특징 + 장소 특징 + 관측 방문 기록으로 여행자-장소 적합도를 학습하고 Top-K를 추천할 수 있는가?**

2026-10-28 기준 프로젝트의 최상위 질문이다. 모델 이름, 데이터 변환 형식, 후보 구성 방법은 이 문제를 푸는 수단이며 문제 정의를 대신하지 않는다. 이 문서는 #94의 v2 판단을 저장소 문서의 단일 기준으로 옮기고, #41과 기존 전문 계약·실험 기록을 읽는 우선순위를 정한다.

## 한눈에 보는 문제

~~~
추천 요청의 여행자 특성 + 현재 여행 문맥
+
추천 대상이 될 수 있는 장소(POI)의 특징
+
학습 시 관측된 방문 기록
        ↓
여행자-장소 적합도 학습
        ↓
추천 자격이 있는 장소에 점수 부여
        ↓
Top-K 추천
~~~

### 예시 입력 → 출력

예시 요청 문맥은 “10월에 가족과 서울을 여행하며 문화·산책 장소를 찾는다”이고, 각 장소에는 서비스에서 재현 가능한 유형·지역 같은 정적 특징이 있다고 하자. 학습 단계에서는 과거 여행 문맥과 관측 방문 기록으로 이 조합의 적합도를 학습한다. 요청 시에는 추천 자격이 확인된 장소들에 점수를 매겨 **순위가 있는 Top-K 목록**을 반환한다. 아래 POI와 순서는 설명용이며 실제 실험 결과가 아니다.

~~~
요청 문맥 + POI 특징 + 과거 관측 방문 관계
        → 적합도 점수
        → [POI-A, POI-B, ...] (Top-K)
~~~

사용자의 장기 방문 이력이 없어도 현재 여행 문맥으로 추천을 요청할 수 있어야 한다. 방문은 초기 학습에 사용할 수 있는 관측 신호이지, 노출이나 만족을 확정적으로 관측했다는 뜻은 아니다.

## 데이터 원천의 역할

| 원천 | 맡는 역할 | 해석 경계 |
| --- | --- | --- |
| AI Hub 여행자·여행 로그 | 초기 여행 문맥과 관측 방문의 관계 학습, 개발용 오프라인 검증 | 미방문 장소의 노출이나 불호를 기록하지 않음 |
| AI Hub 방문지·POI Master | 학습 데이터의 장소 속성 및 정적 장소 inventory 근거 | Master의 모든 행이 제품상 추천 가능한 장소라는 뜻은 아님 |
| TourAPI KorService2 | 현재 제품/서빙용 장소 카탈로그와 contentid 식별자 제공 (#66) | AI Hub의 (region, POI_ID)와 다른 식별 체계 |
| AI Hub ↔ TourAPI 식별자 브리지 | 서로 다른 식별자의 연결 및 신호 전달 가능성 검증 (#69) | 일부 매칭 결과를 전체 카탈로그 coverage나 추천 자격으로 일반화하지 않음 |
| 우리 서비스 요청·행동 로그 | 실제 요청, 노출, 클릭, 저장 등 서비스 신호 수집 (#96) | 방문 확인과 명시적 feedback은 선택 기능이며 자동으로 가정하지 않음 |

#69의 Stage 5 보고서는 전체 관측 양성 97,640건 중 26,454건(27.09%)을 연결했고, 제품 권역 조건이 적용된 적격 TourAPI 후보 19,051개 중 2,753개(14.45%)에 AI Hub 방문 신호를 연결했다. 이는 해당 실험의 분모·정책에서 얻은 브리지 결과다. #69의 Stage 5 성과를 과거 #4의 기준 수치로 대체하지 않는다. 브리지 결과는 오프라인 학습을 위해 매 방문을 TourAPI와 연결해야 한다는 뜻도 아니고, 연결되지 않은 장소가 없다는 뜻도 아니다. 자세한 Stage 0/Stage 5 정의와 역사적 기준선은 [POI 카탈로그 계약](poi-catalog-candidate-contract.md) 및 [#69 실험 보고서](experiments/poi-identity-matching-v2.md)를 따른다.

## 추천 시점과 학습 시점

추천 요청 시점에 사용할 수 있는 값과 학습 이후에만 계산되는 값은 구분한다.

| 값의 종류 | 예시 | v2 해석 |
| --- | --- | --- |
| 요청 시점 문맥 | 목적 지역, 여행 시기·기간, 동반자, 사용자가 제공한 여행 스타일·동기 | 실제 제품 요청에서 알 수 있고 동의된 값만 입력 후보로 둔다 |
| 정적 장소 속성 | 유형, 행정 구역, 카탈로그 분류 | 해당 카탈로그에서 일관된 의미와 coverage로 공급되는지 확인한다 |
| 과거 행동 집계 | 장소 방문 수, 계절별·문맥별 방문자 분포 | 학습·모델 선택 중에는 inner-train 자료로만 계산해 inner-validation에 적용한다 |
| 방문 후 feedback | 만족도, 재방문·추천 의향 | 현재 요청의 입력으로 쓰지 않는다. 별도 수집이 필요하며 과거 집계나 대안 relevance label로 쓸지는 검증 후 결정한다 |
| offline-only / 미정 | 서비스에서 같은 의미로 만들 경로가 확인되지 않은 값 | 온라인 기본 feature로 승격하지 않고 보류 또는 별도 검증한다 |

방문 후 생성된 값은 현재 여행 요청의 입력 특성이 아니다. 다만 과거 이벤트의 명시적 feedback을 장소 수준 과거 통계 또는 대안 relevance 신호로 평가할 수는 있다. 두 사용법은 서로 다른 계약이다. #95는 장소 표현과 학습-서빙 재현 가능성을 분류하고, #96은 서비스의 요청·노출·행동 로그 의미를 설계한다.

새 장소처럼 과거 행동이 없는 POI도 정적 장소 속성으로 표현할 수 있어야 한다. 방문 이력 기반 통계가 없는 상태 자체를 보존하며, 과거 관측이 없다는 이유만으로 장소를 추천 불가 또는 부정적으로 단정하지 않는다.

## 추천 자격, 후보 생성, 순위화

세 단계는 서로 다른 질문에 답한다.

1. **추천 자격(candidate eligibility):** 제품 범위와 카탈로그 정책에 따라 어떤 장소가 추천 대상이 될 수 있는가?
2. **후보 생성(candidate generation):** 한 요청에서 큰 추천 대상 집합 중 어떤 장소를 추려 점수화할 것인가?
3. **적합도 점수화·순위화(ranking):** 요청 문맥과 장소 특징이 주어졌을 때 장소를 어떤 순서로 보여줄 것인가?

추천 자격과 요청별 후보 축소를 같은 단계로 취급하지 않는다. 추천 자격을 만족하는 장소 수와 점수화 비용이 감당 가능하면 바로 점수화할 수 있다. 규모나 latency가 실제 제약으로 확인될 때만 후보 생성/검색 계층을 추가한다. #82의 수도권 감사에서 사용한 3,052,797개 inventory는 당시 선택된 후보/feature 정책 아래의 감사 범위이며 제품이 추천해야 할 장소 수로 확정된 값이 아니다.

CatBoost는 적합도 학습의 모델 후보 중 하나다. 지금은 이를 full-catalog 검색기나 고정된 reranker로 정하지 않는다. Two-Tower, ANN, LLM 등도 필요와 평가 근거가 확인되기 전에는 프로젝트 계약에 넣지 않는다.

## 라벨·평가·누수 경계

- 관측된 방문은 첫 baseline에서 사용할 수 있는 **암묵적 양성(implicit positive)** 후보다. 이는 방문/상호작용 관측이지 확정적인 만족·선호가 아니다.
- 방문 기록이 없는 장소는 **미관측(unknown)**이다. 노출이 기록되지 않은 AI Hub에서 미방문을 자동 음성으로 읽지 않는다.
- sampled-unobserved를 학습 비교용 label=0으로 만들더라도 관측된 불호나 노출 후 거절을 뜻하지 않는다.

> **v1 구현상의 라벨 경계 — 방문했지만 tourism_core에서 제외된 장소:** 기존 v1에서는 관광 코호트(`tourism_core`)에 속한 방문만 양성(label=1)으로 삼았다. 따라서 여행자가 실제로 방문한 식당·카페·쇼핑·숙박 등 비핵심 유형은 **방문 기록이 존재하지만 v1의 양성 집합에 포함되지 않는 사례**다. 이는 방문 기록 자체가 없는 `unobserved`와 구분해야 한다.
>
> 현행 음성 표본 추출이 같은 여행의 해당 **관측 비핵심 방문 장소**를 후보에서 별도로 제외하지 않는다면 학습 비교용 `label=0`으로 뽑힐 **가능성이 있다**. 이는 확인된 음성 반응이 아니며, 실제 방문과 비교 라벨이 충돌할 위험이 있다. 이 문서만으로 현재 표본 추출기의 실제 동작이나 충돌 빈도를 확정하지 않는다. **#95 후속 검증 및 #94의 v2 제품 범위·코호트·음성 표본 계약에서 코드 기준으로 확인하고 정책을 결정한다.**
- 여행자·여행·장소의 원시 ID는 조인, 중복 제거, 후보 식별, split/group 확인에만 쓴다. 모델 입력 feature로 넣지 않는다.
- cold-user 문제의 TL 모델 선택은 (region, TRAVELER_ID) 단위 group split을 기본으로 하고, 여행별 문맥으로 ranking group을 만든다.
- 장소 인기도와 방문자 문맥 프로필처럼 행동에서 파생하는 값은 inner-train에서만 집계한다. inner-validation positive를 후보에 사후 주입하지 않는다.
- 후보 coverage와 모델의 ranking metric을 따로 보고한다. 후보에 들어오지 못한 positive는 후보 누락/coverage 문제이지 순위 모델 점수의 증거가 아니다.
- 표준 dataset schema의 TL → train, VL → validation은 출력 파일 역할명이다. 이는 모델 선택 시 TL 내부 inner-train/inner-validation 분할이나 공식 VL 사용 허가를 뜻하지 않는다. 공식 VL은 configuration 잠금 후 #83에서 사용하는 최종 holdout이다.

평가 지표의 최종 우선순위·K와 relevance 계약은 아직 잠기지 않았다. 기존 #41/#82 계약과 수치는 당시 실험 정의·이력으로 보존하며 v2 후보 자격이나 최종 모델 결정을 대신하지 않는다.

## 현재 POI 표현 진단

현재 강한 근거는 장소 표현력과 후보 정책을 더 검증해야 한다는 점이다. 아래 수치는 수도권 TL 및 #82에서 선택한 후보/feature 조건의 진단이지, 모든 장소 feature가 부족하다는 증명이나 CatBoost 자체의 실패를 뜻하지 않는다.

| #82 감사 항목 | 관측값 | 의미 |
| --- | ---: | --- |
| prior policy 기준 candidate inventory | 3,052,797 | 당시 감사 분모이며 최종 제품 범위가 아님 |
| I3=0 및 I4 비어 있음 | 3,051,813 (99.9678%) | 해당 inventory에서 기존 행동 feature가 거의 구별 신호를 주지 못함 |
| 정규화된 item feature tuple | 729종 | 현재 구성 feature가 만드는 고유 표현 수 |
| inner-validation positive의 후보 포함 | 568 / 883 (64.33%) | 기존 후보 정책에서의 coverage 진단; 모델 ranking metric 아님 |

#94에는 동일 tuple 중복 진단(3,052,303개, 99.9838%; 최대 동일 tuple 110,255개)도 기록돼 있다. 이 값들과 사용 조건은 [#82 상태](https://github.com/haeinChoe/Travel-Recommendation/issues/82) 및 [#94 결정](https://github.com/haeinChoe/Travel-Recommendation/issues/94)의 분모와 함께 읽는다. 우선 후속 작업은 #95의 POI Rich Feature v1 표현력/coverage 검증이다.

## 현재 상태와 미결정 사항

| 구분 | 현재 내용 |
| --- | --- |
| **확정된 상위 정의** | 여행자·현재 여행 문맥과 장소 특징, 관측 방문 기록으로 적합도를 학습하고 Top-K를 제안하는 문제; cold-user 지원; raw ID는 key 전용; 공식 VL은 최종 holdout |
| **작업 가설·초기 실험 신호** | 관측 방문을 baseline implicit positive로 검토; 기존 수도권 POI feature tuple은 표현력이 낮다는 근거; 실제 서비스 로그가 AI Hub 집계를 보완할 수 있음 |
| **미결정** | 추천 대상 제품 범위(음식·쇼핑·숙박 포함 여부); 기존 tourism_core 양성 코호트의 v2 유지 여부; AI Hub offline candidate eligibility와 exact POI_ID 결합 한계; #95 feature 채택 및 serving parity; #96 수집 세부 계약; 후보 생성 필요성; 최종 model/objective/primary metric |
| **v1 이력·대체된 해석** | AI Hub Master 전체를 지역 필터 후 direct-score하는 구조, fixed CatBoost 역할, 과거 VL exploratory 계획은 v2의 canonical 문제 정의가 아니다. 연결된 전문 문서의 과거 결과·스키마는 기록으로 보존한다 |

제품 범위와 후보 자격은 문서 작성만으로 결정하지 않는다. 후보 단계의 필요성은 자격이 정리된 뒤 실제 규모와 비용을 보고 판단한다.

## 읽기 순서와 근거

1. 이 문서 — 최상위 문제와 현재 상태
2. [추천 용어 사전](glossary.md) — user/traveler, trip/request, POI, label, candidate 등의 공통 의미
3. [추천 학습 데이터 계약](training-data-contract.md) 및 [학습 데이터셋 스키마](training-dataset-schema.md) — 기존 feature/label 근거와 변환 파일의 기술 스키마; v2 적용 여부는 위 상태표 확인
4. [학습·평가 계약](model-training-evaluation-contract.md)과 [CatBoost 실험 프로토콜](experiments/catboost-ranking-protocol.md) — #41/#82 v1 모델 및 실험 이력
5. [제품 카탈로그와 후보 계약](poi-catalog-candidate-contract.md) 및 [#69 매칭 보고서](experiments/poi-identity-matching-v2.md) — TourAPI 제품 카탈로그와 개선된 identity bridge 결과
6. #94 문제·후속 작업 결정, #95 POI 표현력 검증, #96 서비스 로그 설계, #83 최종 VL 평가

참조 결정: [#41](https://github.com/haeinChoe/Travel-Recommendation/issues/41), [#66](https://github.com/haeinChoe/Travel-Recommendation/issues/66), [#69](https://github.com/haeinChoe/Travel-Recommendation/issues/69), [#82](https://github.com/haeinChoe/Travel-Recommendation/issues/82), [#94](https://github.com/haeinChoe/Travel-Recommendation/issues/94), [#95](https://github.com/haeinChoe/Travel-Recommendation/issues/95), [#96](https://github.com/haeinChoe/Travel-Recommendation/issues/96), [#97](https://github.com/haeinChoe/Travel-Recommendation/issues/97), [#83](https://github.com/haeinChoe/Travel-Recommendation/issues/83).
