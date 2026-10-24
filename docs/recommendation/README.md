# 추천 시스템 문서 읽기 순서

추천 시스템 문서는 알고리즘 이름부터 읽기보다 **제품 문제 → 데이터 의미 → 후보 집합 → 평가 → 알고리즘 비교** 순서로 읽는 것을 권장한다.

## 처음 읽는 경우

1. [추천 시스템 용어 사전](glossary.md)
   이 저장소에서 사용하는 사용자, 여행 문맥, POI, 관측 단위(grain), 조인 키와 입력 특성, 순수 관광 코호트, 후보 집합, 노출, 관측 양성, 순위화 등의 의미를 확인한다.

2. [추천 학습 데이터 구성·포함 기준 및 Feature/Label 계약](training-data-contract.md)
   TourAPI 식별자 매칭 상태와 학습 데이터 자격의 독립성, 3단계 관측 단위(`visit_event_grain`, `trip_poi_grain`, `trip_request_grain`), 순수 관광 코호트(`tourism_core_cohort`) 분리 기준, 입력 특성·라벨 계약 및 4개 권역 코호트 퍼널 집계(Issue #17, #71)를 확인한다.

3. [표준 학습 데이터셋 스키마](training-dataset-schema.md)
   Issue #71 계약을 세 Parquet 출력과 재현 가능한 변환 CLI에 적용한 canonical 컬럼 사전(전체 컬럼의 한국어 설명·역할·원천·계산·타입·Null·split·모델링 주의점), TL/VL→train/validation 매핑, 버전 정책과 SGG 감사를 확인한다.

4. [후보 집합 타당성 실험](experiments/candidate-choice-feasibility.md)
   과거 여행로그만으로 평가 가능한 추천 후보를 어떻게 정의했으며 왜 현재 결론이 판정 보류인지 확인한다.

5. [여행 문맥 × POI 신호 타당성 실험](experiments/context-poi-signal-feasibility.md)
   여행 문맥이 POI 선택과 관련된 예측 신호를 제공하는지, 무엇까지 확인했고 무엇은 아직 추천 순위 품질로 해석할 수 없는지 확인한다.

6. [서비스 카탈로그 기반 후보 계약](poi-catalog-candidate-contract.md)
   한국관광공사 TourAPI KorService2 v4.4 서비스 카탈로그와 AI Hub 여행로그 간 POI 후보 집합 정의, 식별자 매칭 계약 및 위치 조건부 5단계 매칭 기준을 확인한다.

7. [POI 식별자 매칭 및 코호트 커버리지 실험](experiments/poi-identity-matching-v2.md)
   5대 비퍼지 다단계 식별자 매칭 파이프라인의 단계별 누적 성과와 관광 대상 코호트 분리 분석 결과를 확인한다.

## 새 연구·실험 문서를 작성할 때

- [사람 중심 문서 작성 가이드](../documentation-style-guide.md)
- [연구·실험 문서 템플릿](experiment-document-template.md)

## 현재 해석 원칙

- 방문 기록은 관측된 상호작용이지 자동으로 "선호"나 "노출"이 아니다.
- 미방문 장소는 별도 계약이 없으면 음성(negative)이 아니라 미관측 상태다.
- 추천 시점 이후의 만족도 같은 정보는 입력 특성으로 사용하지 않는다.
- 원시 식별자(`TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, `contentid`)는 조인·집계·후보 식별용 구분자(key)로는 사용할 수 있으나 기계학습 모델의 입력 특성(feature)으로는 사용하지 않는다.
- 학습 관측치 포함 자격은 TourAPI 식별자 매칭 여부(`MATCHED` 등)에 의존하지 않으며, 미매칭 TourAPI 후보 점수화에 필요한 카테고리 교차 매핑표(crosswalk)와 콜드 스타트 기본값(prior)은 후속 모델링 단계에서 별도로 확정한다.
- 후보 집합의 정의와 순위 모델의 평가는 분리해서 생각한다.
- 모델 복잡도보다 동일한 데이터·후보·평가 조건에서의 비교를 우선한다.

세부 결정은 각 실험 문서와 연결된 Issue를 기준으로 한다.
