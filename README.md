# Travel Recommendation

기존 TravelMate 프로젝트를 현대적인 풀스택 아키텍처와 검증 가능한 추천 시스템으로 재설계하는 프로젝트입니다.

## Documents

- [PRD (Draft)](docs/PRD.md)

## Goals

- 기존 TravelMate의 핵심 기능과 도메인을 보존하면서 구조를 재설계합니다.
- 웹과 API는 TypeScript 기반으로 재구축합니다.
  - Web: Next.js
  - API: NestJS
- 추천 엔진은 Python 생태계를 유지하고 API 서비스와 명확히 분리합니다.
- 추천 품질을 감에 의존하지 않고 공통 데이터셋과 오프라인 평가 지표로 비교합니다.
- 기존 user-based collaborative filtering 구현을 baseline으로 삼고, Matrix Factorization과 Two-Tower 등으로 단계적으로 고도화합니다.
- 학습과 실험 결과를 재현할 수 있도록 데이터셋 버전, 파라미터, 지표, 모델 아티팩트를 추적합니다.

## Planned Architecture

```text
Client
  |
  v
Next.js (TypeScript)
  |
  v
NestJS API (TypeScript)
  |\
  | +--> Product DB
  |
  +----> Recommendation Service (Python)
             |
             +--> Offline training / evaluation
             +--> Model artifacts / experiment tracking
```

추천 서비스가 애플리케이션 DB 스키마에 직접 결합되는 기존 구조는 재검토합니다. 데이터 소유권과 서비스 계약을 먼저 정의한 뒤 구현합니다.

## Recommendation Roadmap

1. 기존 추천 코드와 데이터 파이프라인 복원
2. AI Hub 국내 여행로그 데이터와 TourAPI 매핑 과정 재구성
3. 공통 평가 데이터셋 및 시간 기반 train/validation/test split 정의
4. Popularity baseline
5. Content-based baseline
6. Matrix Factorization baseline
7. Two-Tower retrieval 실험
8. 후보 생성과 ranking 분리 검토
9. interaction / recommendation impression logging 설계
10. 필요 시 sequential recommendation, graph recommendation, LLM augmentation 비교

### Initial Offline Metrics

- Recall@K
- NDCG@K
- HitRate@K

정확한 지표와 K 값은 데이터 분포와 제품 요구를 확인한 뒤 결정합니다.

## Data Sources

기존 프로젝트에서 사용했던 것으로 추정되는 주요 소스:

- AI Hub 국내 여행로그 데이터
  - 여행객 특성
  - 여행 스타일
  - 방문 이력
  - 만족도 및 활동 정보
- 한국관광공사 TourAPI
  - 관광지 contentId
  - 지역/카테고리
  - 관광지 메타데이터

과거 전처리 과정에서 AI Hub 방문지와 TourAPI 관광지를 매핑했던 흔적을 먼저 복원합니다.

## Experiment Management

추천 모델 실험은 Python에서 진행합니다.

초기 후보:

- PyTorch / scikit-learn
- MLflow: experiment tracking, metrics, artifacts
- Optuna: 필요 시 hyperparameter optimization

자동 튜닝보다 먼저 동일 데이터와 동일 평가 조건에서 baseline 간 차이를 확인하는 것을 우선합니다.

## Repository Direction

초기 구조 후보:

```text
apps/
  web/                 # Next.js
  api/                 # NestJS
recommendation/        # Python training / evaluation / serving
packages/
  contracts/           # shared API schemas/types when appropriate
docs/
  architecture/
  migration/
```

현재 단계에서는 런타임과 패키지 구성을 서둘러 생성하지 않고, 기존 시스템 분석과 아키텍처 결정부터 이슈로 관리합니다.

## Migration Principle

이 프로젝트는 기존 코드를 단순 변환하는 작업이 아닙니다.

- 기존 동작을 먼저 이해하고 계약을 문서화합니다.
- 서비스 경계를 다시 정의합니다.
- 추천 알고리즘의 성능은 baseline과 실험으로 증명합니다.
- 필요한 복잡도만 도입합니다.
