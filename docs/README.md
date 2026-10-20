# 문서 안내

이 문서는 저장소 문서를 **어떤 순서로 읽어야 하는지** 안내한다. 세부 실행 절차보다 먼저 제품과 추천 문제의 현재 상태를 이해하고, 필요한 경우 근거 문서와 재현 정보로 내려가는 것을 권장한다.

## 처음 읽는 경우

1. [PRD](PRD.md) — 제품 요구사항과 시스템 방향
2. [추천 시스템 문서 읽기 순서](recommendation/README.md) — 추천 문제, 데이터 의미, 후보 집합, 평가 문서를 읽는 순서
3. [추천 시스템 용어 사전](recommendation/glossary.md) — 이 프로젝트에서 반복해서 쓰는 추천 용어의 의미
4. [사람 중심 문서 작성 가이드](documentation-style-guide.md) — 새 문서와 PR을 작성할 때 적용할 표현·구조 원칙

## 작업 지침

- [../AGENTS.md](../AGENTS.md) — 저장소 전체에 적용되는 에이전트 작업 원칙
- [agent-workflow.md](agent-workflow.md) — Issue, 권한, 브랜치, 커밋, PR 절차
- [documentation-style-guide.md](documentation-style-guide.md) — 사람 중심 문서 작성 원칙
- [recommendation/experiment-document-template.md](recommendation/experiment-document-template.md) — 추천 연구·실험 문서 기본 구조
- [data/aihub-workflow.md](data/aihub-workflow.md) — AI Hub 데이터 접근, 전처리, 분석 및 결과 공유 절차
- [data/data-science-agent.md](data/data-science-agent.md) — 반복적인 실제 데이터 분석을 위한 데이터 사이언티스트 역할과 권한 계약

## 데이터 문서

- [data/travel-log-2023/README.md](data/travel-log-2023/README.md) — 2023 국내 여행로그 네 권역 데이터 설명서 Markdown 변환본과 권역별 차이
- [data/aihub-71776-capital-schema.md](data/aihub-71776-capital-schema.md) — 수도권 스키마 및 EDA 관련 컬럼 요약 참조
- [data/eda-travel-log-2023.md](data/eda-travel-log-2023.md) — 2023 국내 여행로그 4개 권역 EDA 계획과 안전한 집계 보고서 (Issue #12)

## 추천 시스템 문서

추천 관련 문서는 [recommendation/README.md](recommendation/README.md)의 읽기 순서를 먼저 확인한다.

- [recommendation/training-data-contract.md](recommendation/training-data-contract.md) — Legacy TravelMate와 AI Hub 2023 근거에 기반한 추천 학습 데이터 계약 (Issue #17)
- [recommendation/experiments/candidate-choice-feasibility.md](recommendation/experiments/candidate-choice-feasibility.md) — 후보 집합과 평가 가능성 검증
- [recommendation/experiments/context-poi-signal-feasibility.md](recommendation/experiments/context-poi-signal-feasibility.md) — 여행 문맥과 POI 사이의 예측 신호 검증 (Issue #45)
- [recommendation/poi-catalog-candidate-contract.md](recommendation/poi-catalog-candidate-contract.md) — 서비스 카탈로그(TourAPI KorService2 v4.4) 기반 POI 후보 생성 및 식별자 매칭 계약 (Issue #67, #69)
- [recommendation/experiments/poi-identity-matching-v2.md](recommendation/experiments/poi-identity-matching-v2.md) — 5대 비퍼지 다단계 POI 식별자 매칭 및 코호트 커버리지 실험 보고서 (Issue #69)

## 운영·도구 문서

- [herdr-mcp-bridge.md](herdr-mcp-bridge.md) — Herdr를 사용하는 세션을 위한 MCP 브리지와 sandbox 문제 진단

## 문서 변경 원칙

새로운 데이터·아키텍처 결정은 관련 Issue와 근거에 연결한다. 문서를 수정할 때는 다음을 함께 확인한다.

- 현재 상태와 결론을 문서 상단에서 찾을 수 있는가
- 처음 등장하는 전문 용어를 설명했는가
- 확인된 사실, 해석, 결정, 미결정을 구분했는가
- 기존 기술적 의미나 실험 결과를 문체 수정 과정에서 바꾸지 않았는가
- 관련 문서 링크와 읽는 순서를 함께 갱신했는가
