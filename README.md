# Travel Recommendation

기존 TravelMate를 현대적인 풀스택 구조로 재설계하고, 여행 문맥과 장소 정보를 이용한 검증 가능한 추천 시스템을 만드는 프로젝트입니다.

## 추천 문제

**여행자/여행 문맥 특징 + 장소 특징 + 관측 방문 기록으로 여행자-장소 적합도를 학습하고 Top-K를 추천할 수 있는가?**

사용자의 장기 방문 이력이 없어도 현재 여행 요청의 문맥으로 추천받을 수 있어야 합니다. 제품 범위, 추천 가능한 장소, feature, label과 평가는 근거를 확인하며 순서대로 잠급니다. 모델과 검색 기술은 문제 정의가 아닙니다.

## 문서

- [추천 문제 정의 v2 — 단일 기준](docs/recommendation/problem-definition-v2.md)
- [저장소 문서 안내와 읽기 순서](docs/README.md)
- [제품 요구사항(PRD)](docs/PRD.md)
- [추천 시스템 문서 읽기 순서](docs/recommendation/README.md)
- [추천 시스템 용어 사전](docs/recommendation/glossary.md)
- [사람 중심 문서 작성 가이드](docs/documentation-style-guide.md)

## 현재 추천 작업 순서

1. #97에서 최상위 추천 문제와 문서 우선순위를 정리합니다.
2. #95에서 장소 표현력과 각 feature의 서비스 재현 가능성을 검증합니다.
3. #96에서 추천 요청·노출·행동 로그의 의미를 설계합니다.
4. 제품 범위와 추천 자격을 정한 뒤 간단한 적합도 모델로 다시 평가합니다.
5. 실제 후보 수와 점수화 비용이 크다고 확인되면 후보 생성 계층을 검토합니다.
6. configuration을 잠근 뒤 #83에서 공식 VL을 최종 holdout으로 평가합니다.

현재 #82의 full-catalog 탐색은 장소 표현력과 후보 정책이 정리되기 전까지 보류합니다. CatBoost는 모델 후보 중 하나이며, Two-Tower/ANN 등은 필요한 근거가 있을 때만 검토합니다. 음식·쇼핑·숙박의 포함 여부와 최종 모델은 아직 결정되지 않았습니다.

## 제품·기술 방향

- Web: Next.js + TypeScript
- API: NestJS + TypeScript
- 추천 학습·평가·서비스: Python
- Product DB: PostgreSQL 후보
- 실험 추적: MLflow 후보; 필요 시 Optuna 검토

현재 루트 Node 설정은 애플리케이션이 아니라 agent/tooling 회귀 테스트를 위한 최소 기반입니다. Next.js/NestJS 앱 구조는 별도 이슈에서 정합니다.

~~~text
Client
  → Next.js (TypeScript)
  → NestJS API (TypeScript)
       → Product DB
       → Recommendation Service (Python)
            → Offline training / evaluation
            → Model artifacts / experiment tracking
~~~

추천 서비스는 애플리케이션 DB 내부 schema에 직접 결합하지 않습니다. 데이터 소유권과 서비스 계약을 먼저 정의합니다.

## 데이터 원천

- **AI Hub 국내 여행로그:** 서비스 출시 전 초기 학습을 위한 여행 문맥과 관측 방문 기록입니다. 미방문 장소의 노출 또는 불호를 뜻하지 않습니다.
- **AI Hub POI Master:** 장소 속성 및 정적 inventory의 근거입니다. Master 전체가 자동으로 추천 대상이 되지는 않습니다.
- **한국관광공사 TourAPI KorService2:** 현재 제품/서빙용 POI 카탈로그이며 식별자는 contentid입니다.
- **AI Hub ↔ TourAPI 브리지:** #69에서 다단계 식별자 매칭 결과를 개선했습니다. Stage 5 결과는 그 실험의 분모와 정책으로 해석하며 #4의 과거 baseline으로 덮지 않습니다.

## 개발 원칙

- 기존 기능과 데이터 흐름을 먼저 이해하고 계약을 문서화합니다.
- 추천 품질은 같은 문제·후보·분할·평가 조건에서 비교합니다.
- offline AI Hub 결과와 TourAPI 서빙 호환성을 자동으로 동일시하지 않습니다.
- 필요한 복잡도만 도입하고, 모델·feature·실험 결과를 재현 가능하게 기록합니다.