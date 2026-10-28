# 문서 안내

이 문서는 저장소 문서를 어떤 순서로 읽어야 하는지 안내합니다. 먼저 추천 문제와 현재 결정 상태를 확인한 뒤 제품 요구사항, 데이터 계약, 실험 근거로 내려갑니다.

## 처음 읽는 경우

1. [추천 문제 정의 v2 — 단일 기준](recommendation/problem-definition-v2.md) — 프로젝트의 최상위 질문, 현재 확정·임시·미결정을 확인합니다.
2. [Travel Recommendation PRD](PRD.md) — 사용자 경험과 제품 방향을 확인합니다.
3. [추천 시스템 문서 읽기 순서](recommendation/README.md) — 전문 계약과 실험 기록의 역할을 확인합니다.
4. [추천 시스템 용어 사전](recommendation/glossary.md) — user/traveler, POI, 상호작용, 후보 단계 등 공통 용어를 확인합니다.
5. [사람 중심 문서 작성 가이드](documentation-style-guide.md) — 문서와 PR의 표현·구조 원칙을 확인합니다.

## 작업 지침

- [../AGENTS.md](../AGENTS.md) — 저장소 전체에 적용되는 에이전트 작업 원칙
- [agent-workflow.md](agent-workflow.md) — Issue, 권한, 브랜치, 커밋, PR 절차
- [documentation-style-guide.md](documentation-style-guide.md) — 사람 중심 문서 작성 원칙
- [recommendation/experiment-document-template.md](recommendation/experiment-document-template.md) — 추천 연구·실험 문서 기본 구조
- [data/aihub-workflow.md](data/aihub-workflow.md) — AI Hub 데이터 접근, 전처리, 분석 및 결과 공유 절차
- [data/data-science-agent.md](data/data-science-agent.md) — 반복적인 실제 데이터 분석을 위한 데이터 사이언티스트 역할과 권한 계약

## 데이터 문서

- [data/travel-log-2023/README.md](data/travel-log-2023/README.md) — 2023 국내 여행로그 네 권역 데이터 설명과 권역별 차이
- [data/aihub-71776-capital-schema.md](data/aihub-71776-capital-schema.md) — 수도권 스키마 및 EDA 관련 컬럼 요약
- [data/eda-travel-log-2023.md](data/eda-travel-log-2023.md) — 2023 국내 여행로그 EDA 계획과 안전한 집계 보고서

## 추천 시스템 문서

현재 문제 정의와 우선순위는 [recommendation/problem-definition-v2.md](recommendation/problem-definition-v2.md)를 먼저 읽습니다. 아래 전문 문서들은 해당 기준의 근거, 기존 기술 스키마 또는 실험 이력을 설명합니다.

- [recommendation/README.md](recommendation/README.md) — 추천 문서의 상세 읽기 순서와 현재 해석 원칙
- [recommendation/training-data-contract.md](recommendation/training-data-contract.md) — AI Hub 학습 데이터·관측 단위·기존 feature/label 계약
- [recommendation/training-dataset-schema.md](recommendation/training-dataset-schema.md) — 변환기 출력 Parquet의 컬럼과 타입 계약
- [recommendation/model-training-evaluation-contract.md](recommendation/model-training-evaluation-contract.md) — #41/#82의 모델·후보·평가 실험 계약과 이력
- [recommendation/experiments/catboost-ranking-protocol.md](recommendation/experiments/catboost-ranking-protocol.md) — CatBoost v1 탐색 계획 및 현재 보류 상태
- [recommendation/poi-catalog-candidate-contract.md](recommendation/poi-catalog-candidate-contract.md) — TourAPI 서비스 카탈로그와 POI 식별 브리지
- [recommendation/experiments/poi-identity-matching-v2.md](recommendation/experiments/poi-identity-matching-v2.md) — #69 Stage 5 매칭 개선의 범위와 결과

## 운영·도구 문서

- [herdr-mcp-bridge.md](herdr-mcp-bridge.md) — Herdr를 사용하는 세션을 위한 MCP 브리지와 sandbox 문제 진단

## 문서 변경 원칙

새로운 데이터·아키텍처 결정은 관련 Issue와 근거에 연결합니다. 문서를 수정할 때 다음을 확인합니다.

- 현재 상태와 결론을 문서 상단에서 찾을 수 있는가
- 확인된 사실, 해석, 결정, 미결정을 구분했는가
- 문제 정의 문서와 전문 문서의 역할이 분명한가
- 기존 기술적 의미와 실험 이력을 보존했는가
- 상대 링크와 읽기 순서가 일치하는가