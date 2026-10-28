# 표준 학습 데이터셋 스키마

> **이 문서를 읽을 때:** 여기서는 여행 문맥, 장소 특징, 관측 방문 관계를 **세 개의 Parquet 파일로 저장하는 방식**을 설명한다. 데이터 변환기가 `TL` 파일을 `train`, `VL` 파일을 `validation`으로 부르는 것은 **출력 폴더의 역할 이름**이지, 개발자가 공식 VL로 모델을 반복 개선해도 된다는 뜻이 아니다. 모델을 고를 때는 TL 안에서 여행자별로 다시 나누고, VL은 최종 설정을 정한 뒤에만 평가한다. 또한 **Master에 존재하는 장소와 실제 추천할 자격이 있는 장소는 다르다.** 현재 추천 문제의 범위는 [기준 문서](problem-definition-v2.md)를 따른다.


## 목적과 현재 계약

이 문서는 추천 학습 변환기가 만드는 세 Parquet 파일의 기술 계약이다. AI Hub 원본의 컬럼과 분할 역할을 내부 모델용 컬럼에 대응시키고, **장소 위치는 하나의 원시 시군구 값 대신 출처·해석 상태를 포함한 표준 행정 위치 정보**로 바꿨다. `item_features`는 과거 방문된 장소뿐 아니라 정적 POI Master에서 고유하게 식별되는 장소까지 보관한다. 파일은 `trip_context.parquet`(여행 상황), `item_features.parquet`(장소 특징), `trip_item_interaction.parquet`(관측 방문 관계) 세 개다. **이렇게 저장한 모든 장소를 추천 후보로 사용하라는 뜻은 아니다.**

manifest는 `dataset_type=travel-recommendation-training`, `schema_version=2.0`, `contract_version=2.0`을 기록한다. 이번 버전은 기존 `sgg_code`를 canonical I2 필드로 대체하고, `item_features`를 TL/VL 상호작용에서 관측된 POI뿐 아니라 고유 AI Hub `TN_POI_MASTER` inventory로 확장한 breaking change다. 스키마 버전은 컬럼명·타입·필수성 변경을, 계약 버전은 값의 의미·원천·누수 방지 규칙 변경을 나타낸다.

`TL` 입력 역할은 내부 `train`, `VL`은 `validation`으로 변환한다. 입력 경로 환경변수와 원천 매핑에서는 AI Hub 역할 표기를 유지한다. `trip_key`와 `item_key`는 한 실행(run) 범위의 대체 키(surrogate key)다. 서로 다른 실행에서 같은 키가 같은 개체를 뜻한다고 보장하지 않으며 run 간 개체 식별에 사용하지 않는다. 별도 namespace 메타데이터는 두지 않는다.

Parquet null 제약은 변환 검증과 이 문서로 보장한다. “필수”는 null 불가이며, 빈 리스트는 허용될 수 있다. 원시 ID·개인정보는 출력에 저장하지 않는다. `observed_positive=1`은 방문이 관측된 암묵적 양성일 뿐 선호 점수나 노출을 뜻하지 않는다. 관측되지 않은 POI는 음성으로 처리하지 않는다.

## 컬럼 사전

아래 표의 각 행은 사람 기준으로 컬럼의 뜻, 원천, 계산, 타입, null, split 범위와 모델링 제한을 함께 정의한다. “입력” 역할이어도 반드시 allowlist에 있는 값만 사용한다.

### `trip_context.parquet`

| 표준 컬럼명 | 한국어 이름 | 한국어 설명 | 데이터 역할 | 원천 | 생성·계산 규칙 | 타입·허용값 | Null 정책 | train-validation 사용 범위 | 모델링 주의점 |
|---|---|---|---|---|---|---|---|---|---|
| `trip_key` | 여행 키 | 한 여행 행을 연결하는 실행 범위 대체 키 | 조인 키 | `TN_TRAVEL.TRAVEL_ID` (해시 후 원시값 폐기) | 실행 ID·권역·원천 ID로 SHA-256 앞 128비트 생성 | string, 32 hex | 필수 | 두 split | 입력·임베딩 금지; run 간 동일성 미보장 |
| `region` | 권역 | 여행이 속한 입력 권역 | 모델 입력·메타데이터 | 입력 바인딩 | 권역 코드 그대로 사용 | string: `capital`, `west`, `east`, `jeju-islands` | 필수 | 두 split | 허용된 범주형 입력이자 scope metadata |
| `split` | 데이터 분할 | 행이 학습 또는 검증 중 어느 쪽인지 표시 | 메타데이터 | AI Hub 파일 역할 TL/VL | TL→`train`, VL→`validation` | string: `train`, `validation` | 필수 | 각 행 하나 | 모델 입력 금지; split 간 여행 중복 금지 |
| `travel_style_1` | 여행 스타일 응답 1 | 여행자 스타일 설문 1번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_1` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_2` | 여행 스타일 응답 2 | 여행자 스타일 설문 2번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_2` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_3` | 여행 스타일 응답 3 | 여행자 스타일 설문 3번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_3` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_4` | 여행 스타일 응답 4 | 여행자 스타일 설문 4번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_4` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_5` | 여행 스타일 응답 5 | 여행자 스타일 설문 5번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_5` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_6` | 여행 스타일 응답 6 | 여행자 스타일 설문 6번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_6` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_7` | 여행 스타일 응답 7 | 여행자 스타일 설문 7번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_7` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_style_8` | 여행 스타일 응답 8 | 여행자 스타일 설문 8번 문항의 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STYL_8` | 공백 제거 및 코드 도메인 검사 | string, `1`~`7` | 허용 | 각 여행의 split | 순서별 문항으로 사용; 결측을 임의 대치하지 않음 |
| `travel_motive_1` | 여행 동기 응답 1순위 | 여행 동기 설문의 1순위 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_MOTIVE_1` | 공백 제거 및 코드 도메인 검사 | string, `1`~`10` | 허용 | 각 여행의 split | 순위 문항은 서로 바꿔 쓰지 않음; 결측을 임의 대치하지 않음 |
| `travel_motive_2` | 여행 동기 응답 2순위 | 여행 동기 설문의 2순위 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_MOTIVE_2` | 공백 제거 및 코드 도메인 검사 | string, `1`~`10` | 허용 | 각 여행의 split | 순위 문항은 서로 바꿔 쓰지 않음; 결측을 임의 대치하지 않음 |
| `travel_motive_3` | 여행 동기 응답 3순위 | 여행 동기 설문의 3순위 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_MOTIVE_3` | 공백 제거 및 코드 도메인 검사 | string, `1`~`10` | 허용 | 각 여행의 split | 순위 문항은 서로 바꿔 쓰지 않음; 결측을 임의 대치하지 않음 |
| `travel_status_destination` | 여행 목적지 유형 | 여행자 마스터에 기록된 목적지 유형 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STATUS_DESTINATION` | 공백 제거 | string, 원천 코드 | 허용 | 각 여행의 split | 운영 지역 코드와 parity가 확정됐다는 뜻 아님 |
| `companion_status` | 동반 형태 | 동반 여행 형태 코드 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_STATUS_ACCOMPANY` | 공백 제거 | string, 원천 코드 | 허용 | 각 여행의 split | `TN_COMPANION_INFO`의 관계 코드와 다른 개념 |
| `companion_count` | 동반 인원 수 | 기록된 동반 인원 정수 | 모델 입력 | `TN_TRAVELLER_MASTER.TRAVEL_COMPANIONS_NUM` | 음이 아닌 정수로 파싱 | int32, 0 이상 | 허용; 음수·파싱 실패는 null | 각 여행의 split | 값이 여행자 포함 전체 인원인지 임의 해석하지 않음 |
| `start_month` | 여행 시작 월 | 여행 시작 날짜의 월 | 모델 입력 | `TN_TRAVEL.TRAVEL_START_YMD` | 시작 날짜에서 월만 파생; 날짜 원문 미저장 | string, `01`~`12` | 날짜 오류·결측이면 null | 각 여행의 split | 예: 4월 시작이면 `04`; 여행 종료 월이 아님 |
| `elapsed_days` | 시작일부터 종료일까지 경과 일수 | 종료일에서 시작일을 뺀 날짜 차이 | 모델 입력 | `TN_TRAVEL.TRAVEL_START_YMD`, `TRAVEL_END_YMD` | `end - start` 달력 날짜 차이 | int32, 0 이상 | 날짜 오류·음수면 null | 각 여행의 split | 예: 당일=0, 1박 2일=1; 일반적인 “여행 일수”와 다를 수 있음 |

### `item_features.parquet`

| 표준 컬럼명 | 한국어 이름 | 한국어 설명 | 데이터 역할 | 원천 | 생성·계산 규칙 | 타입·허용값 | Null 정책 | train-validation 사용 범위 | 모델링 주의점 |
|---|---|---|---|---|---|---|---|---|---|
| `item_key` | 장소 키 | POI 행과 상호작용을 연결하는 실행 범위 대체 키 | 조인 키 | 권역, `POI_ID` (원시값은 메모리만) | 실행 ID·권역·원천 ID로 SHA-256 앞 128비트 생성 | string, 32 hex | 필수 | 두 split 관측 장소 | 입력·임베딩 금지; run 간 동일성 미보장 |
| `region` | 권역 | 장소가 속한 입력 권역 | 모델 입력·메타데이터 | 입력 바인딩 | 원천 권역 | string, 위 허용 목록 | 필수 | 두 split | 입력의 scope를 넘는 지리 정밀도를 뜻하지 않음 |
| `observed_in_splits` | 관측된 분할 | 이 장소가 상호작용에 나타난 분할 목록 | 메타데이터·진단값 | interaction 행의 내부 split | 연결된 interaction에서 중복 제거 후 정렬; 값은 `train`, `validation` | list<string>, 빈 목록 가능 | 필수 | 어느 쪽 관측인지 표시 | 빈 목록은 Master inventory의 train-unseen 후보; 입력 금지 |
| `train_observed_visit_type_codes` | 학습 관측 방문 유형 코드 | 학습 여행에서 해당 장소 방문 이벤트에 기록된 방문 유형 코드 집합 | 모델 입력 | `TL`/`train`의 `TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD` | train 관광 핵심 trip-item에 연결된 이벤트 코드의 정렬 고유 집합 | list<string>, 코드 목록; 빈 목록 가능 | 필수 필드, 값 없음은 빈 목록 | train만; validation 이벤트 미사용 | POI Master 정적 분류 아님. TourAPI `contenttypeid`와 같은 분류체계가 아님 |
| `canonical_admin_sido_code` | 표준 시도 코드 | AI Hub `TC_SGG` 코드북에서 확인한 광역 행정구역 코드 | 모델 입력 | 유일 `TN_POI_MASTER.SGG_CD` 또는 정적 보조 주소를 `TC_SGG`에 대조 | 유효한 5자리 SGG 코드의 앞 2자리 | string, 해당 코드북의 2자리 | 해소 불가·충돌은 null | 정적 inventory 전체; TL/VL 방문 행으로 채우지 않음 | `region`의 네 coarse product region과 별개이며 request target geography를 뜻하지 않음 |
| `canonical_admin_sgg_code` | 표준 시군구 코드 | AI Hub `TC_SGG`에서 검증된 5자리 시군구 코드 | 모델 입력 | 유일 `TN_POI_MASTER.SGG_CD`, 필요 시 정적 주소의 정확한 시도+시군구명 | `TC_SGG` 등록 코드만 허용; 10자리 표현은 뒤 5자리가 0일 때 앞 5자리로 검증 | string, 해당 `TC_SGG`의 5자리 `SGG_CD` | 미확정·충돌·미등록은 null | 정적 inventory 전체 | 시군구 단위. 읍면동·도로·거리·요청 목적지를 뜻하지 않음 |
| `canonical_admin_sido_name` | 표준 시도 이름 | canonical 시도 코드에 대응하는 AI Hub `TC_SGG.SIDO_NM` | 설명용 메타데이터 | `TC_SGG` | 코드북에서 조회 | string | 해소 불가 시 null | 정적 inventory 전체 | 모델 입력에는 코드 사용; 제공 이름은 읽기·감사용 |
| `canonical_admin_sgg_name` | 표준 시군구 이름 | canonical 시군구 코드에 대응하는 AI Hub `TC_SGG.SGG_NM` | 설명용 메타데이터 | `TC_SGG` | 코드북에서 조회 | string | 해소 불가 시 null | 정적 inventory 전체 | 코드북 표기 이름이며 세분 지리나 서비스 요청값 아님 |
| `canonical_admin_location_status` | 행정 위치 해결 상태 | 정적 근거를 모순 없이 행정구역으로 해석했는지 표시 | 모델 입력 | Master 코드·Master 주소, 선택적 TourAPI 정적 근거 | `resolved_single_source`, `resolved_multi_source`, `conflict`, `ambiguous_address`, `unavailable` | string, 위 상태 집합 | 필수 | 정적 근거만 사용 | visit-only 상태는 item feature에 쓰지 않고 visit audit status에만 보존 |
| `canonical_admin_provenance` | 행정 위치 출처 | 결정에 참여한 출처 종류 목록 | 감사 메타데이터 | Master 코드·주소, 선택적 TourAPI 코드·주소 | `master_sgg_code`, `master_address`, `tourapi_sgg_code`, `tourapi_address` 등 허용된 출처 토큰만 정렬 저장 | list<string>, 빈 목록 가능 | 필수 | 정적 근거만 포함 | 주소·코드 원문, POI ID, 좌표는 저장 금지 |
| `canonical_admin_conflict_sources` | 행정 위치 충돌 출처 | 정적 해결을 막은 출처 종류 | 감사 메타데이터 | 현재 builder의 Master 코드·주소; 추후 연결된 경우 TourAPI 정적 근거 | 현재 저장 값은 `master`만 가능; 향후 TourAPI 연결 시 `tourapi` 추가 가능 | list<string>, 빈 목록 가능 | 필수 | static-only conflict만 저장 | 모델 입력 금지; visit conflict는 이 배열이 아니라 manifest의 `train_visit_corroboration`에만 집계 |
| `coordinate_validation_status` | 좌표 검증 범위 및 사용 상태 | 과거 anchor subset 검증과 현재 좌표 사용 여부를 구분 | 감사 메타데이터 | Issue #69 공개 anchor aggregate 및 현재 위치 코드 경로 | 현재 `subset_validation_only_not_used` | string, `subset_validation_only_not_used` | 필수 | raw coordinate는 feature 생성에 쓰지 않음 | 과거 4,279/4,686 anchor subset 결과를 전체 Master inventory 보증으로 확대하지 않음; H3/거리 계산 금지 |
| `source_category_l1_code` | 원천 장소 대분류 코드 | AI Hub POI Master의 첫 번째 분류 단계 | 모델 입력 | `TN_POI_MASTER.ASORT_LCLASDC` | 고유 Master 행에서 전체 정적 inventory에 결합 | string, AI Hub 원천 코드 | Master 연결/값 없으면 null | 전체 정적 inventory | TourAPI `lclsSystm1`와 같다고 가정 금지; 별도 crosswalk 미정 |
| `source_category_l2_code` | 원천 장소 중분류 코드 | AI Hub POI Master의 두 번째 분류 단계 | 모델 입력 | `TN_POI_MASTER.ASORT_MLSFCDC` | 고유 Master 행에서 전체 정적 inventory에 결합 | string, AI Hub 원천 코드 | Master 연결/값 없으면 null | 전체 정적 inventory | TourAPI `lclsSystm2`와 동일 taxonomy 아님 |
| `source_category_l3_code` | 원천 장소 소분류 코드 | AI Hub POI Master의 세 번째 분류 단계 | 모델 입력 | `TN_POI_MASTER.ASORT_SDASDC` | 고유 Master 행에서 전체 정적 inventory에 결합 | string, AI Hub 원천 코드 | Master 연결/값 없으면 null | 전체 정적 inventory | TourAPI `lclsSystm3`와 동일 taxonomy 아님 |
| `train_positive_interaction_count` | 학습 관측 양성 수 | 해당 장소가 train의 tourism-core 고유 여행-장소 상호작용에 나타난 횟수 | 모델 입력 | `train` `trip_item_interaction`의 `observed_positive` | 권역별 item의 고유 trip-item 양성을 합산 | int64, 0 이상 | 필수; train 등장 없음은 0 | 오직 train; validation은 절대 사용하지 않음 | 전체 인기·전체 방문수가 아님. validation으로 계산하면 누수; VL-only는 0 |

### `trip_item_interaction.parquet`

| 표준 컬럼명 | 한국어 이름 | 한국어 설명 | 데이터 역할 | 원천 | 생성·계산 규칙 | 타입·허용값 | Null 정책 | train-validation 사용 범위 | 모델링 주의점 |
|---|---|---|---|---|---|---|---|---|---|
| `trip_key` | 여행 키 | 여행 문맥 행을 참조하는 실행 범위 키 | 조인 키 | `TN_TRAVEL.TRAVEL_ID` | `trip_context`와 동일한 surrogate 생성 규칙 | string, 32 hex | 필수 | 두 split | 모델 입력 금지; run 간 동일성 미보장 |
| `item_key` | 장소 키 | 장소 특성 행을 참조하는 실행 범위 키 | 조인 키 | 권역, `POI_ID` | `item_features`와 동일한 surrogate 생성 규칙 | string, 32 hex | 필수 | 두 split | 모델 입력 금지; run 간 동일성 미보장 |
| `region` | 권역 | 상호작용의 권역 | 메타데이터 | 입력 바인딩 | 여행과 장소의 region 일치 검증 | string, 위 허용 목록 | 필수 | 두 split | 조인 무결성 확인용, 모델 입력 아님 |
| `split` | 데이터 분할 | 관측 상호작용의 학습/검증 구분 | 메타데이터 | AI Hub 파일 역할 | TL→`train`, VL→`validation` | string, `train`, `validation` | 필수 | 각 상호작용 하나 | 입력 금지; 여행 split과 일치해야 함 |
| `observed_positive` | 방문 관측 양성 표시 | 해당 여행에서 POI 방문이 실제 기록됨 | 라벨 | `TN_VISIT_AREA_INFO`의 유효 tourism-core 방문 | 같은 여행-POI 반복 이벤트를 하나의 이진 양성으로 합쳐 항상 1 | int32, `1` | 필수 | 원천 split 그대로 | “좋아함”의 직접 평가나 노출을 의미하지 않음; 미방문은 음성이 아니라 미관측 |
| `repeat_visit_count` | 반복 방문 기록 수 | 중복 제거 전 동일 여행-POI 방문 이벤트 수 | 진단값 | `TN_VISIT_AREA_INFO`의 이벤트 | 같은 trip-item 양성에 속한 원시 이벤트 수 | int64, 1 이상 | 필수 | 원천 split 그대로 | 진단 전용; 학습 가중치나 라벨 강도가 아님 |

## 모델 입력 allowlist와 split 규칙

`trip_context` 입력은 `region`, `travel_style_1..8`, `travel_motive_1..3`, `travel_status_destination`, `companion_status`, `companion_count`, `start_month`, `elapsed_days`다. `item_features`의 모델 allowlist는 `region`, `train_observed_visit_type_codes`, `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`, `source_category_l1_code`~`source_category_l3_code`, `train_positive_interaction_count`다. 이름·provenance·충돌 출처·좌표 검증 상태는 설명/감사용 메타데이터라 모델 입력이 아니다. 상호작용 테이블은 입력 컬럼을 제공하지 않는다.

원천 `TL`/`VL` 역할 표시는 파일 선택과 감사 집계에서만 쓴다. Parquet split 값과 `observed_in_splits`에는 `train`/`validation`만 허용한다. 아이템의 train-derived 값은 TL 입력에서만 만든다. validation을 `train_positive_interaction_count`나 `train_observed_visit_type_codes` 생성에 포함하면 누수다.

### TL 내부 개발 분할과 행동 특징 재계산

표준 Parquet의 `train`/`validation`은 outer TL/VL 역할을 계속 나타낸다. cold-user tuning용 inner split은 canonical 관측 단위인 `(region, TRAVELER_ID, TRAVEL_ID)`에서 `(region, TRAVELER_ID)`를 group key로 삼아 같은 권역 내 같은 여행자의 모든 `TRAVEL_ID`를 한 partition에 배정하며, raw ID와 경로는 메모리 안에서만 사용한다. 원천 계약은 traveler ID의 권역 간 전역 유일성을 보장하지 않으므로 권역을 포함해 식별한다. 분포·split 대상은 canonical 학습 코호트와 맞추기 위해 `TN_TRAVEL`의 유일한 여행 행 중 유일한 `TN_TRAVELLER_MASTER` traveler 행과 연결되는 trip으로 한정한다. `scripts/recommendation/tl_traveler_split.py`는 seed와 validation 비율을 받아 결정론적으로 나누고, 여행자 overlap을 검사한다. 같은 seed로 trip 단위 reference split도 생성해 partition label 불일치 trip 수/비율을 계산하고, trip split에서 여러 partition에 나뉜 traveler 수/비율과 그 traveler의 여행 수/비율을 집계한다. label 불일치는 두 hash 단위가 달라 생기는 결정론적 비교값일 뿐 split 구조의 동등성이나 leakage 측정값을 뜻하지 않는다. 실제 구조 차이는 multi-trip traveler 비율과 trip split의 traveler overlap으로 판단한다. 실측 네 권역에서는 모두 traveler:trip 1:1이고 multi-trip share가 0%였으므로 현재 표본에서 trip split도 traveler를 분할하지 않았다. 다만 반복 traveler가 있는 미래 입력에서도 cold-user leakage를 막도록 기본 계약은 traveler group split으로 둔다. 기본 설정은 seed `issue80-v1`, validation 비율 0.2다.

inner split 뒤 I3 `train_positive_interaction_count`는 outer TL의 고유 양성 trip-item interaction 중 inner-train 여행만 세어 다시 만든다. I4 `train_observed_visit_type_codes`는 canonical `trip_item_interaction.parquet`에서 가져오지 않는다. 해당 파일에는 방문 유형이 없기 때문이다. 대신 같은 TL 원천의 `TN_VISIT_AREA_INFO.TRAVEL_ID`, `POI_ID`, `VISIT_AREA_TYPE_CD` 이벤트를 inner-train 여행과 연결해 재계산한다. 이 계산 함수 `recompute_inner_train_visit_type_codes`는 Issue #80에서 구현했고 synthetic tests로 검증했다. 최소 하나의 관광 핵심 방문 이벤트가 있는 trip-item만 item feature 대상이 되며, 이 쌍의 유효 방문유형 코드를 모은다. 원천 이벤트 입력이 없거나 trip/item/visit-type/TL split 필드를 확인할 수 없으면 I4를 추정하지 않고 `I4SourceUnavailableError`로 중단한다. PR #88의 #82 runner가 TL visit-event 입력을 helper에 연결해 사용한다. 이는 I4 계산 의미나 inner-train 경계를 바꾸지 않는다.

승인된 실행 환경에서 `CAPITAL_TL`, `WEST_TL`, `EAST_TL`, `JEJU_TL`을 해당 TL 입력 디렉터리에 바인딩한 뒤 다음 명령으로 privacy-safe aggregate를 출력한다. 출력은 표준 출력의 JSON이며 실제 원천 경로나 ID 값은 쓰지 않는다. Issue #80 실행에서는 네 role binding 모두 provenance 확인을 통과했다.

~~~bash
uv run python scripts/recommendation/tl_traveler_split.py \
  --seed issue80-v1 \
  --validation-fraction 0.2
~~~

이 내부 분할 규칙은 기존 Parquet의 스키마나 값 의미를 바꾸지 않는다. outer-TL 전체에서 계산된 canonical I3/I4는 TL 내부 tuning에 재사용하지 않으며, outer TL→VL 최종 학습에만 사용한다. 네 권역 입력 provenance 확인과 실제 traveler-trip aggregate 및 split 비교를 완료했고, synthetic 회귀·CLI 테스트도 실행했다. 상세 aggregate는 다음 절에 기록한다.

### 실제 학습 데이터(TL)의 여행자별 분할 결과

검증된 네 role binding으로 실행한 결과, 각 권역은 동일한 aggregate를 보였다. 각 권역에 distinct traveler 2,560명과 distinct trip 2,560개가 있었고, traveler trip-count 구간은 1 trip 2,560명, 2 trips 0명, 3+ trips 0명이었다. 평균·중앙값·최대 trips는 각각 1이며 multi-trip traveler share는 0%다.

| 권역 | Inner-train travelers / trips | Inner-validation travelers / trips | Group-split traveler overlap | Trip-split structural traveler overlap | Partition-label disagreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| 수도권 (Capital) | 2,048 / 2,048 | 512 / 512 | 0 | 0 | 784 / 2,560 (30.6250%) |
| 동부권 (East) | 2,048 / 2,048 | 512 / 512 | 0 | 0 | 812 / 2,560 (31.71875%) |
| 제주도 및 도서지역 (Jeju Islands) | 2,048 / 2,048 | 512 / 512 | 0 | 0 | 804 / 2,560 (31.40625%) |
| 서부권 (West) | 2,048 / 2,048 | 512 / 512 | 0 | 0 | 818 / 2,560 (31.953125%) |

분할 seed는 `issue80-v1`, validation fraction은 0.2다. 현재 표본에서 모든 traveler가 한 trip만 보유하고 trip-split structural traveler overlap은 권역별 0명이므로, 두 split은 traveler leakage 방지 구조 측면에서 동등하다. 기본 계약은 미래 반복 traveler를 고려해 traveler group split을 유지한다. Partition-label disagreement는 traveler key와 trip key로 만든 두 deterministic assignment의 label 비교일 뿐 structural equivalence나 leakage metric가 아니다. 집계는 aggregate 수치만 기록하며 원천 ID와 경로는 문서화하지 않는다.

## 원천→표준 컬럼 매핑

다음 표는 원천 시스템 이름을 보존하는 유일한 데이터 의미 매핑이다. 출력 Parquet에는 원천 대문자 컬럼명을 그대로 내보내지 않는다.

| 원천 | 표준 출력 |
|---|---|
| `TN_TRAVELLER_MASTER.TRAVEL_STYL_1..8` | `travel_style_1..8` |
| `TN_TRAVELLER_MASTER.TRAVEL_MOTIVE_1..3` | `travel_motive_1..3` |
| `TN_TRAVELLER_MASTER.TRAVEL_STATUS_DESTINATION` | `travel_status_destination` |
| `TN_TRAVELLER_MASTER.TRAVEL_STATUS_ACCOMPANY` | `companion_status` |
| `TN_TRAVELLER_MASTER.TRAVEL_COMPANIONS_NUM` | `companion_count` |
| `TN_TRAVEL.TRAVEL_START_YMD` | `start_month` |
| `TN_TRAVEL.TRAVEL_START_YMD`, `TRAVEL_END_YMD` | `elapsed_days` |
| 역할 입력 `TL`, `VL` | split `train`, `validation` |
| train 방문의 `TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD` | `train_observed_visit_type_codes` |
| 유일 `TN_POI_MASTER.SGG_CD`와 정적 주소 단서 + `TC_SGG` 코드북 | `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`, provenance metadata |
| `TN_POI_MASTER.ASORT_LCLASDC` | `source_category_l1_code` |
| `TN_POI_MASTER.ASORT_MLSFCDC` | `source_category_l2_code` |
| `TN_POI_MASTER.ASORT_SDASDC` | `source_category_l3_code` |
| train 고유 여행-장소 양성 집계 | `train_positive_interaction_count` |
| 상호작용 split의 고유 집합 | `observed_in_splits` |

## SGG 감사와 재조정

코드 검증은 8개 입력의 `TC_CODEB`에서 `cd_a='VIS'`의 공식 17개 코드/라벨이 #71 계약과 맞는지 확인하고, 하나라도 불일치하면 생성을 중단한다. canonical I2는 `TC_SGG`가 등록한 5자리 시군구만 허용하며, 시도 코드는 앞 2자리, 이름은 같은 행의 `SIDO_NM`/`SGG_NM`에서만 가져온다. Master 코드와 Master 주소가 서로 다른 행정구역을 가리키면 코드를 null로 두고 `conflict`와 출처 종류를 남긴다. 동일 시도에서 주소 이름이 여러 SGG와 겹치거나 코드북과 정확히 일치하지 않는 주소는 `ambiguous_address`/미확정으로 둔다.

`manifest.json`은 기존 방문 SGG 감사와 별도로 `canonical_location`의 고유 Master inventory 분모와 정적 위치 해결 상태를 region별로 집계한다. TL 방문 행의 위치 단서는 정적 canonical feature와 일치하는지 진단할 때만 쓰며 `train_visit_corroboration`에 비식별 상태 수만 기록한다. VL 방문 행은 canonical location이나 provenance 생성에 참여하지 않는다. 방문 근거는 canonical 코드·상태·출처를 채우거나 덮어쓸 수 없어서 TL inner split의 inner-validation 행도 I2를 바꾸지 않는다. 주소 텍스트와 좌표값은 출력하지 않는다. 과거 Issue #69는 매칭 anchor subset에서 WGS84 범위 및 거리 일치 aggregate를 확인했지만, 이 결과는 전체 Master inventory의 CRS source contract나 좌표 coverage를 확립하지 않는다. 따라서 현재 item 좌표 상태는 `subset_validation_only_not_used`이며 좌표/H3/거리를 feature/manifest 값으로 계산하지 않는다.

`observed_in_splits=[]`인 행은 TL/VL 상호작용에 나타나지 않은 고유 Master item이다. 해당 행도 `item_key`, region, 정적 분류, canonical I2, 0 popularity, 빈 train-visit type 목록을 가져 candidate inventory에서 사용할 수 있다. Master 연결이 없는 관측 item은 interaction 참조를 보존하기 위해 metadata-only 행으로 출력하지만, 정적 특성 설정을 충족하지 않으므로 candidate feature eligibility를 주장하지 않는다.

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
