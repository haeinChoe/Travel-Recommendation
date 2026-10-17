# Travel Recommendation Product Reference Analysis

> Last updated: 2026-10-12
>
> Related: #41

## 1. 목적

이 문서는 여행 추천 제품의 공개 사용자 경험을 조사해, Travel Recommendation의 추천 문제와 제품 요구사항을 결정하기 위한 참고 근거를 정리한다.

내부 추천 알고리즘이나 학습 방식을 추측하지 않는다. 공개 UI, 공식 제품 페이지, 공식 도움말에서 확인 가능한 입력·출력·상호작용만 비교한다.

AI Hub 제공 reference model/code는 이 문서의 제품 의사결정 근거로 사용하지 않는다.

## 2. 조사 질문

- 추천을 받기 전에 사용자가 어떤 정보를 제공하는가?
- 추천 단위는 POI, 숙소/식당, waypoint, itinerary 중 무엇인가?
- 첫 추천에 필요한 최소 입력은 무엇인가?
- 현재 여행의 목적지·기간·동행자·예산·취향 같은 trip context가 어떻게 사용되는가?
- 추천 결과를 사용자가 어떻게 선택, 저장, 제외, 일정화하는가?
- 추천 이후 탐색·지도·일정 작성과 어떻게 연결되는가?

## 3. 비교 요약

| Product | Recommendation unit | Explicit inputs/context | Cold-start UX | Feedback / next action | 우리 서비스에 주는 인사이트 |
| --- | --- | --- | --- | --- | --- |
| Tripadvisor AI | 호텔, 식당, Things to do, itinerary | 목적지, 날짜, 동행자 및 follow-up 조건 | 계정 없이도 계획 시작 가능 | 추천 저장, itinerary 편집·재배열·공유 | 현재 여행 context에서 선택지를 좁히고 추천한 뒤 일정으로 연결 |
| Mindtrip | 장소, 이벤트, 숙박/식당, itinerary | 좋아하는 것/싫어하는 것, 예산, 동행자, 기타 선호 | 명시적 preference를 대화로 받아 첫 추천 가능 | 저장, 공유, itinerary 편집·협업 | 장기 history보다 현재 여행의 명시적 선호를 강하게 활용하는 UX |
| Roadtrippers Autopilot | route waypoint / POI | 출발지, 목적지, 날짜, 차량, 동행자, 예산, 선호 장소 종류 | 몇 가지 질문 후 즉시 추천 | Add 또는 X(skip), 지도에서 계속 탐색 | context로 candidate space를 제한하고 선택/거절 feedback을 즉시 받는 패턴 |
| Google Maps | 주변 장소 / POI | 현재 위치·검색 맥락 | 현재 맥락으로 탐색 가능 | 저장, 평점, 리뷰 | 위치와 검색 맥락 중심의 로컬 discovery UX 참고 |
| 트리플 | 관광지·맛집·숙소 및 여행 일정 | 여행 일정/목적지, 취향, 현재 위치 등 | 장기 history 없이 여행 계획·추천 기능 진입 가능 | 장소 저장/일정 추가, 일정·동선 구성 | Top-K 장소 추천을 일정 작성의 입력 후보로 연결하는 국내 UX 참고 사례 |

## 4. 제품별 관찰

### 4.1 Tripadvisor AI

공식 AI Travel Assistant는 사용자가 목적지, 날짜, 동행자를 알려주면 추가 질문으로 조건을 좁히고 호텔·식당·할 일을 추천한다. 생성된 day-by-day itinerary는 저장 후 편집, 재배열, 공유할 수 있다.

- Source: https://www.tripadvisor.com/AIAssistant
- Trips: https://www.tripadvisor.com/Trips

관찰:

- 추천 요청의 시작점이 장기 history가 아니라 현재 여행의 조건이다.
- 추천 결과는 최종 산출물로 끝나지 않고 itinerary로 저장·편집할 수 있다.
- 추천과 일정 작성이 연결되지만 두 기능의 책임은 분리되어 있다.

### 4.2 Mindtrip

공식 FAQ는 추천을 개인화하려면 사용자가 대화에서 좋아하는 활동, 피하고 싶은 것, 예산, 동행자, 기타 선호를 알려주도록 안내한다. 장소와 이벤트 추천, itinerary 구성 및 수정, 저장·공유를 하나의 흐름으로 연결한다.

- Source: https://resources.mindtrip.ai/travelers/help/traveler-faqs

관찰:

- 명시적 preference와 trip context가 cold-start UX의 핵심이다.
- 사용자 identity 자체보다 현재 여행에서 제공한 정보가 제품적으로 중요한 입력이다.
- 추천 후보를 일정으로 가져가는 후속 행동이 자연스럽게 연결된다.

### 4.3 Roadtrippers Autopilot

Autopilot은 출발지/목적지에서 시작해 날짜, 차량, 동행자, 식사·숙박·활동 예산, 선호 장소 유형 등을 질문한다. 이후 route 주변의 waypoint를 추천하며 사용자는 Add 또는 X를 통해 추천을 채택하거나 건너뛸 수 있다.

- Source: https://support.roadtrippers.com/hc/en-us/articles/24995143275412-Using-Autopilot-to-Plan-a-Trip

관찰:

- trip context가 candidate generation을 강하게 제한한다.
- 추천 결과에 대한 Add/X는 향후 학습에 유용한 명시적 feedback 형태다.
- 추천 → 선택 → 지도/여정 편집 흐름이 명확하다.

### 4.4 Google Maps

Google Maps는 현재 위치와 검색 맥락을 중심으로 주변 장소를 탐색하는 대표적인 로컬 discovery UX를 제공한다.

- Source: https://support.google.com/maps/

관찰:

- 현재 위치와 검색 조건이 장소 탐색의 직접적인 제품 맥락으로 작동한다.
- 우리 서비스에는 위치·지역 기반 candidate scoping과 탐색 UX 관점만 참고한다.

### 4.5 트리플

트리플 App Store 설명은 AI 여행 일정, 관광지·맛집 추천, 장소 선택 후 동선/일정 구성, 현재 위치 기반 주변 관광지·맛집 추천을 주요 기능으로 설명한다. 버전 기록에서는 일정에 장소를 추가할 때 장소 설명, 평점, 리뷰, 저장 수를 바로 확인하는 탐색 경험도 확인된다.

- Source: https://apps.apple.com/kr/app/%ED%8A%B8%EB%A6%AC%ED%94%8C-%ED%95%AD%EA%B3%B5-%ED%98%B8%ED%85%94-%EC%B5%9C%EC%A0%80%EA%B0%80-%EC%98%88%EC%95%BD-%EC%97%AC%ED%96%89%EA%B3%84%ED%9A%8D/id1225499481

현재 App Store의 Mac/iPad listing에는 트리플 서비스가 2026-11-03 종료되고 NOL로 통합될 예정이라고 안내되어 있다. 따라서 트리플은 장기적인 경쟁 제품 상태라기보다, 국내 여행 계획 UX의 참고 사례로 사용한다.

관찰:

- 장소 추천과 일정 생성은 연결되지만 POI를 고르는 단계 자체가 독립적인 사용자 가치가 있다.
- 장소를 일정에 추가하는 행동은 추천 결과에 대한 명시적인 positive feedback으로 활용 가능하다.
- 위치, 평점, 리뷰, 저장 수 같은 contextual/social signal은 향후 product catalog가 갖춰진 뒤 실험 후보가 될 수 있다.

## 5. Adopt

### 5.1 Cold-start를 예외가 아니라 핵심 사용자 시나리오로 정의

사용자가 다음 정보만으로 추천을 받을 수 있어야 한다.

- 목적지/여행 지역
- 여행 기간 또는 날짜
- 동행자 맥락
- 사용자가 명시적으로 제공한 여행 취향


### 5.2 추천 문제를 current-trip contextual ranking으로 정의

제품 수준의 기본 흐름은 다음과 같이 둔다.

```text
traveler preference
+ trip context
+ eligible candidate POIs
  -> relevance scoring / ranking
  -> Top-K POIs
```

세부 prediction unit과 feature contract는 #41에서 확정한다.

### 5.3 제품 constraint로 candidate space를 먼저 제한

여행 지역, 서비스 가능한 POI, 명백한 여행 조건 등은 가능한 경우 ranking 전에 candidate eligibility로 처리한다.

모델이 전국의 모든 POI를 점수화한 뒤 제품 규칙으로 대부분 제거하는 구조를 기본값으로 두지 않는다.

### 5.4 추천과 일정 구성을 분리하되 연결 가능하게 설계

초기 추천 기능의 책임은 Top-K POI를 반환하는 데 둔다.

```text
Top-K POI recommendation
  -> user selects / saves
  -> future itinerary composition
```

자동 일정 생성이나 경로 최적화를 현재 추천 모델의 책임에 포함하지 않는다.

## 6. Experiment

### 6.2 Social / popularity signal

Product catalog가 갖춰지면 다음 값을 POI ranking feature 또는 사용자 UI signal로 실험할 수 있다.

- rating
- review count
- save count
- popularity

현재 AI Hub 학습 데이터에 동일한 서비스 신호가 존재한다고 가정하지 않는다.

### 6.3 Recommendation explanation

내부 model score를 그대로 보여주기보다 사용자가 이해할 수 있는 trip-context 기반 추천 이유를 제공하는 방식을 검토한다.

예:

- 가족 여행에 적합
- 선택한 여행 스타일과 관련
- 현재 여행 지역 내 후보

설명의 신뢰성과 실제 사용 feature의 일치가 확인된 경우에만 노출한다.

## 7. Reject / Defer

### 7.1 완전한 itinerary optimization

다음 문제는 현재 Top-K POI ranking과 별개로 둔다.

- 날짜별 자동 배치
- 이동 동선 최적화
- 운영시간/예약 가능성을 포함한 스케줄 최적화
- 항공·숙소·POI를 함께 최적화하는 패키지 생성

추천 품질 계약이 확정된 후 별도 제품 기능으로 검토한다.

### 7.2 채팅/LLM 인터페이스를 추천 모델과 결합

자연어 입력은 향후 preference extraction UX가 될 수 있지만, 추천 ranking 자체를 LLM 응답으로 대체하는 것은 현재 범위에서 제외한다.

### 7.3 특정 모델 계열의 선결정

유사 제품의 공개 UX만으로 내부 알고리즘을 추측하지 않는다.

CF, MF, Learning-to-Rank, Two-Tower 등은 제품 조사 결과가 아니라 데이터 계약과 오프라인 실험으로 선택한다.

## 8. #41에 대한 제품 수준 결론

현재 제품 방향은 다음과 같이 정리한다.

- Primary product output: ranked Top-K POIs
- Core request context: current trip context + explicit traveler preference
- Cold-start: core supported scenario
- Candidate space: product/trip constraints로 우선 제한
- Recommendation result: 사용자가 선택/저장할 수 있고 향후 itinerary 기능으로 연결 가능
- Model family: 계약 및 실험 이후 선택

아직 #41에서 결정해야 할 세부사항:

- traveler preference와 trip context의 정확한 feature 범위
- prediction unit의 최종 schema
- relevance/preference label
- unknown / pseudo-negative sampling 규칙
- split / cold-start cohort / evaluation protocol
