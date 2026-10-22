# 표준 학습 데이터셋 스키마 (Issue #73)

이 문서는 Issue #71 학습 계약을 적용해 생성하는 세 Parquet 파일의 타입, null 허용 여부, 원천 컬럼 매핑과 재현 명령을 정의한다. 승인된 2023년 4개 권역 데이터는 최종 검증에서 변환했다. 생성 산출물은 Git-ignore 상태로 보관하고 커밋하지 않았으며, 이 문서에는 개인정보 안전 집계만 기록한다. 기본 출력은 `data/processed/training-dataset/<run-id>/`이다.

## 목적과 결정

관측 양성은 한 여행에서 관측한 관광 핵심 POI이며 `observed_positive = 1`이다. 동일 여행-POI 반복 방문은 한 상호작용으로 합치고 `repeat_visit_count`는 진단값으로 둔다. TL만 방문 기반 아이템 특성과 `tl_popularity`를 만든다. VL은 관측 상호작용 및 분할 메타데이터에만 영향을 준다. 원시 식별자는 메모리에만 남고, 연결에는 실행 ID로 범위가 정해진 SHA-256 surrogate key를 사용한다.

`region`은 권역 스코프 메타데이터이자 계약에서 허용한 범주형 모델 입력이다. `split`, 키, 라벨, 방문 반복 진단값은 메타데이터/식별자다. 모델 입력은 아래 명시적 allowlist만 허용한다. 분할은 TL=학습, VL=검증이며, 방문하지 않은 POI는 음성으로 만들지 않는다.

## Parquet 컬럼 계약

Parquet 자체는 필드의 null 허용 제약을 일관되게 표현하지 않으므로, nullability는 생성 코드 검증과 이 계약을 통해 보장한다. 아래 `필수`는 null 불가, `허용`은 null 가능을 뜻한다.

### `trip_context.parquet`

| 컬럼 | 타입 | Null | 원천/파생 | 사용 |
|---|---|---|---|---|
| `trip_key` | string | 필수 | `TN_TRAVEL.TRAVEL_ID`의 run-scoped surrogate | 조인 키, 모델 제외 |
| `region` | string | 필수 | 입력 역할 바인딩 | 권역 범주형 모델 입력 및 스코프 메타데이터 |
| `split` | string | 필수 | TL/VL 입력 역할 | 메타데이터, 모델 제외 |
| `TRAVEL_STYL_1..8` | string | 허용 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_1..8`, 코드 `1..7` | 모델 입력 |
| `TRAVEL_MOTIVE_1..3` | string | 허용 | `TN_TRAVELLER_MASTER.TRAVEL_MOTIVE_1..3`, 코드 `1..10` | 모델 입력 |
| `TRAVEL_STATUS_DESTINATION` | string | 허용 | 동명 traveller master 컬럼 | 모델 입력 |
| `TRAVEL_STATUS_ACCOMPANY` | string | 허용 | 동명 traveller master 컬럼 | 모델 입력 |
| `TRAVEL_COMPANIONS_NUM` | int32 | 허용 | 동명 traveller master 컬럼, 0 이상 정수 | 모델 입력 |
| `month` | string | 허용 | `TN_TRAVEL.TRAVEL_START_YMD`에서 `01..12` 파생 | 모델 입력 |
| `elapsed_days` | int32 | 허용 | `TRAVEL_END_YMD - TRAVEL_START_YMD`, 음수/날짜 오류는 null | 모델 입력 |

### `item_features.parquet`

| 컬럼 | 타입 | Null | 원천/파생 | 사용 |
|---|---|---|---|---|
| `item_key` | string | 필수 | 권역 및 `POI_ID`의 run-scoped surrogate | 조인 키, 모델 제외 |
| `region` | string | 필수 | 입력 역할 바인딩 | 권역 범주형 모델 입력 및 스코프 메타데이터 |
| `split_presence` | list<string> | 필수 | 이 아이템이 나타난 interaction의 TL/VL 역할 | 메타데이터, 모델 제외 |
| `VISIT_AREA_TYPE_CODES` | list<string> | 필수(빈 목록 가능) | TL 방문의 정렬된 고유 `TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD` | 모델 입력 |
| `SGG_CD` | string | 허용 | TL 관광 핵심 방문 전체의 유일한 유효 값; 복수 방문값 또는 유효 Master 값과 다르면 null; 유효 방문값이 없을 때만 유일 POI master 보완 | 모델 입력 |
| `ASORT_LCLASDC` | string | 허용 | TL 상호작용에 연결된 유일 `TN_POI_MASTER` 행 | 모델 입력 |
| `ASORT_MLSFCDC` | string | 허용 | 동상 | 모델 입력 |
| `ASORT_SDASDC` | string | 허용 | 동상 | 모델 입력 |
| `tl_popularity` | int64 | 필수 | 권역 내 TL 관광 핵심의 고유 여행-POI 양성 수; VL 전혀 사용 안 함 | 모델 입력 |

VL-only 아이템은 테이블에 존재해 interaction 키가 온전하게 연결되지만 TL-derived 속성은 null/빈 목록, 인기도는 0이다. 이 행의 속성은 VL 내용으로 채우지 않는다. Master 속성도 TL에서 관측된 아이템에 대해서만 결합한다.

### `trip_item_interaction.parquet`

| 컬럼 | 타입 | Null | 원천/파생 | 사용 |
|---|---|---|---|---|
| `trip_key` | string | 필수 | 권역 및 `TRAVEL_ID` surrogate | 조인 키, 모델 제외 |
| `item_key` | string | 필수 | 권역 및 `POI_ID` surrogate | 조인 키, 모델 제외 |
| `region` | string | 필수 | 입력 역할 바인딩 | 메타데이터, 모델 제외 |
| `split` | string | 필수 | TL/VL 입력 역할 | 메타데이터, 모델 제외 |
| `observed_positive` | int32 | 필수 | #71 관측 방문 label, 항상 1 | label, 모델 입력 제외 |
| `repeat_visit_count` | int64 | 필수 | 중복 제거 전 여행-POI 이벤트 수 | 진단, 모델 입력 제외 |

## 명시적 모델 입력 allowlist

`trip_context`: `region`, 여행 스타일 8개, 여행 동기 3개, 목적지, 동반 형태, 동반 인원, `month`, `elapsed_days`.

`item_features`: `region`, `VISIT_AREA_TYPE_CODES`, `SGG_CD`, `ASORT_LCLASDC`, `ASORT_MLSFCDC`, `ASORT_SDASDC`, `tl_popularity`.

Issue #71 계약 §2.2에 따라 `region`은 권역 스코프 메타데이터이면서 요청/아이템의 범주형 모델 입력이다. 상호작용 행의 `region`과 모든 `split` 값은 메타데이터다. `trip_key`, `item_key`, 원시 ID, `split`, label, 방문 반복 수, 날짜, 주소, 좌표, 감사 진단 및 `split_presence`는 모델 입력에 포함하지 않는다. SGG 및 POI 분류는 추천 입력 후보일 뿐, 외부 카탈로그와의 category parity를 확정하지 않는다.

## SGG 감사와 재조정

코드 검증은 8개 입력의 `TC_CODEB`에서 `cd_a='VIS'`의 공식 17개 코드/라벨이 #71 계약과 맞는지 확인하고, 하나라도 불일치하면 생성을 중단한다. 각 region/split의 `TC_SGG.SGG_CD`에 정확히 포함된 값만 strict-valid다. 레거시 SggCrosswalk 호환 수치는 strict TC_SGG 수치와 별도로 기록한다.

`manifest.json`은 region/split/cohort(`all_valid_visits`, `tourism_core`, `non_tourism`)별 방문 상태, Master POI join 상태, Master SGG 상태, 상호 배타적 해결 결과 및 분모를 집계한다. `direct`는 현재 방문 행 자체가 strict-valid인 경우만 뜻한다. 현재 행에 값이 없지만 cohort 내 같은 POI의 유일한 유효 값으로 채운 경우는 `poi_aggregate_filled`, 유효 방문 값이 하나도 없고 유일 Master SGG로 채운 경우는 `master_filled`로 따로 센다. cohort 내 여러 유효 방문 값 또는 방문 집계와 유효 Master 값이 다르면 `value_conflicts`로 분류한다. cohort별 POI 유효 값 상태(유일/충돌/없음)도 행 단위와 고유 POI 단위로 각각 집계하며 두 분모를 재조정한다. item `SGG_CD`는 TL 관광 핵심 방문 전체에서 유효 값을 모아 한 번 결정하고 유효 값 충돌이면 null이다.

`all_valid_visits`는 방문 유형 분류에서 `tourism_core`, `non_tourism`, `missing_visit_type`, `unsupported_visit_type`로 나뉘며 네 집계 합은 all-valid 방문 분모와 일치해야 한다. SGG를 결정하지 못한 관측에는 POI ID 대신 POI 존재 건수와 Master join 상태(`unique`, `missing`, `ambiguous`, `not_applicable`)만 기록한다. 이 두 집계 합은 SGG-unavailable 분모와 일치한다. 주소 문자열/좌표는 기록하지 않고 도로명 주소, 지번 주소, 완전한 X/Y 쌍의 존재 건수만 남긴다. 감사는 ID, 원시 코드 값, 주소, 좌표, 입력 경로 또는 caller run ID를 내보내지 않는다. 실행 ID는 메모리에서만 surrogate key scope에 쓰인다.

### 승인 데이터 실행의 SGG 결과

아래 표는 2023년 4개 권역에서 TL과 VL을 권역별로 합산한 결과다. 원인별 비율은 각 코호트의 전체 유효 방문 수를 분모로 가중 계산했다. 위치 단서 비율은 SGG 미확보 방문만 분모로 사용하며, 세 신호는 서로 겹칠 수 있다. 표는 미확보 원인과 위치 단서 존재 여부를 설명하기 위한 집계이며, 위치 단서로 SGG를 생성하거나 보정하지 않는다.

원인별 최종 결과는 코호트 분모와 모두 재조정됐다. `master_missing`은 8개 권역·코호트 조합 모두 0건(0.00%)이다.

| 권역 | 코호트 | 유효 방문 분모 | 직접 유효 | POI 집계 보완 | Master 보완 | 미등록/사용 불가 | POI Master 미연결/모호 | 양쪽 모두 값 없음 | 유효값 충돌 | Master 값 결측 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 수도권 | `tourism_core` (관광 핵심) | 5,684 | 406 (7.14%) | 336 (5.91%) | 1,383 (24.33%) | 216 (3.80%) | 1,427 (25.11%) | 1,901 (33.44%) | 15 (0.26%) | 0 (0.00%) |
| 수도권 | `non_tourism` (비관광) | 18,470 | 5,452 (29.52%) | 143 (0.77%) | 2,724 (14.75%) | 592 (3.21%) | 5,902 (31.95%) | 3,587 (19.42%) | 70 (0.38%) | 0 (0.00%) |
| 서부권 | `tourism_core` (관광 핵심) | 8,817 | 550 (6.24%) | 407 (4.62%) | 1,555 (17.64%) | 791 (8.97%) | 1,784 (20.23%) | 3,690 (41.85%) | 40 (0.45%) | 0 (0.00%) |
| 서부권 | `non_tourism` (비관광) | 23,058 | 5,684 (24.65%) | 761 (3.30%) | 4,232 (18.35%) | 1,143 (4.96%) | 5,945 (25.78%) | 5,212 (22.60%) | 81 (0.35%) | 0 (0.00%) |
| 동부권 | `tourism_core` (관광 핵심) | 8,588 | 528 (6.15%) | 706 (8.22%) | 1,012 (11.78%) | 502 (5.85%) | 1,937 (22.55%) | 3,844 (44.76%) | 59 (0.69%) | 0 (0.00%) |
| 동부권 | `non_tourism` (비관광) | 24,342 | 5,864 (24.09%) | 979 (4.02%) | 3,846 (15.80%) | 1,266 (5.20%) | 6,538 (26.86%) | 5,624 (23.10%) | 225 (0.92%) | 0 (0.00%) |
| 제주권 | `tourism_core` (관광 핵심) | 13,354 | 743 (5.56%) | 959 (7.18%) | 1,396 (10.45%) | 642 (4.81%) | 2,372 (17.76%) | 7,193 (53.86%) | 49 (0.37%) | 0 (0.00%) |
| 제주권 | `non_tourism` (비관광) | 38,242 | 6,085 (15.91%) | 695 (1.82%) | 6,559 (17.15%) | 1,336 (3.49%) | 8,317 (21.75%) | 13,304 (34.79%) | 1,946 (5.09%) | 0 (0.00%) |

위치 단서 존재율은 SGG 미확보 방문 분모에 대한 값이다. 도로명 주소, 지번 주소, 완전 좌표쌍은 겹칠 수 있으므로 열 간 합계를 계산하지 않는다.

| 권역 | 코호트 | SGG 미확보 분모 | 도로명 주소 있음 | 지번 주소 있음 | 완전 좌표쌍 있음 |
|---|---|---:|---:|---:|---:|
| 수도권 | `tourism_core` (관광 핵심) | 3,559 | 2,411 (67.74%) | 3,531 (99.21%) | 3,365 (94.55%) |
| 수도권 | `non_tourism` (비관광) | 10,151 | 9,728 (95.83%) | 9,863 (97.16%) | 8,350 (82.26%) |
| 서부권 | `tourism_core` (관광 핵심) | 6,305 | 4,135 (65.58%) | 6,278 (99.57%) | 6,113 (96.95%) |
| 서부권 | `non_tourism` (비관광) | 12,381 | 11,865 (95.83%) | 12,106 (97.78%) | 10,564 (85.32%) |
| 동부권 | `tourism_core` (관광 핵심) | 6,342 | 3,669 (57.85%) | 6,310 (99.50%) | 6,195 (97.68%) |
| 동부권 | `non_tourism` (비관광) | 13,653 | 13,184 (96.56%) | 13,361 (97.86%) | 12,046 (88.23%) |
| 제주권 | `tourism_core` (관광 핵심) | 10,256 | 5,523 (53.85%) | 10,208 (99.53%) | 9,990 (97.41%) |
| 제주권 | `non_tourism` (비관광) | 24,903 | 23,985 (96.31%) | 24,581 (98.71%) | 22,937 (92.11%) |

**해석과 한계:** 관광 핵심 코호트에서도 권역별 유효 방문의 상당 부분에서 SGG를 확보하지 못했다. 비관광 방문에서는 도로명 주소 존재율이 더 높게 나타났지만, 이 집계는 주소·좌표와 SGG의 인과 관계나 실제 복원 가능성을 검증하지 않는다. 위치 신호는 감사용 존재 집계로만 사용했으며, 신규 SGG 생성이나 추천 순위·모델 성능 평가는 하지 않았다.

## 재현 명령

승인된 데이터 환경에서 8개 역할 변수(`CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, `JEJU_VL`)와 권역별 `*_OTHER`를 바인딩한다. 원시 경로는 셸 안에서만 유지한다.

```bash
uv run python scripts/recommendation/training_dataset.py \
  --run-id issue73-training-dataset-v1
```

같은 입력과 `run-id`는 같은 정렬·surrogate key·Parquet 행을 생성한다. `manifest.json`의 생성 시각은 실행마다 달라질 수 있다. 승인된 4개 권역 입력으로 최종 검증 실행을 완료했으며, 실제 Parquet 산출물은 Git-ignore 상태로 두고 커밋하지 않았다. 이 문서에 공유한 실제 데이터 결과는 위의 개인정보 안전 집계로 제한한다.
