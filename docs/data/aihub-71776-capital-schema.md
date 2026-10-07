# AI Hub 71776 수도권 스키마 참조

## 출처와 범위

- **[공식 문서 사실]** 기준 페이지는 [AI Hub 국내 여행로그 데이터(수도권, 2023)](https://aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71776&topMenu=100)다. 2026-10-07 확인 당시 페이지의 데이터 버전은 1.2였고, 2024-12-04 변경 이력은 서브라벨링 추가를 기록한다. 이 문서는 사용자가 제공한 수도권 데이터 설명서의 테이블 정의를 함께 사용한다. 설명서 파일의 별도 개정 표시는 확인하지 못했다.
- **[공식 문서 사실]** 설명서의 상세 테이블 표는 컬럼명, 자료형, 필수 여부, 설명을 제공한다. `필수 여부`의 Y/N은 필수 입력 여부이며 기본키·외래키 선언으로 해석하지 않는다.
- **[미확인]** 연결된 구축·활용 가이드의 내용은 확인하지 않았다. `TC_CODEA`와 `TC_CODEB`의 모든 허용 코드값 및 코드 간 상세 매핑은 이 참조에 옮기지 않았다.

## 테이블 역할과 EDA 관련 컬럼

아래 컬럼명·의미·자료형은 설명서의 스키마 정의다. 목록은 EDA의 구조·연결 후보를 이해하는 데 필요한 필드 중심이며 전체 컬럼 사전은 아니다. 열거한 ID 필드도 데이터 행에서 유일성이나 조인 성립을 뜻하지 않는다.

| 공식 테이블 | 공식 역할 | EDA 관련 컬럼·설명서 선언 자료형 |
| --- | --- | --- |
| `TN_TRAVELLER_MASTER` | 여행객 정보 | `TRAVELER_ID` 여행객 식별 필드 (`varchar(255)`); 거주 시군구, 성별·연령대, 소득, 선호 지역·여행 스타일 등은 `varchar` 계열; `TRAVEL_NUM` 여행빈도 (`int(11)`) |
| `TN_TRAVEL` | 여행 기본 정보 | `TRAVEL_ID` (`varchar(50)`), `TRAVELER_ID` (`varchar(255)`), 목적·페르소나; 시작·종료일은 `date`, 동반자 수는 `int(5)` |
| `TN_COMPANION_INFO` | 동반자 정보 | `TRAVEL_ID` (`varchar(50)`), 동반자 관계·성별·연령대·상황은 `varchar` 계열 |
| `TN_MOVE_HIS` | 여행 중 이동 내역 | `TRIP_ID`, `TRAVEL_ID`, 출·도착 방문지 식별 필드; 시작·종료 시각은 `datetime`, 이동수단 코드는 문자열 계열 |
| `TN_GPS_COORD` | 이동 GPS 좌표 | `MOBILE_NUM_ID`, X/Y 좌표 (`varchar` 계열), `DT_MIN` (`datetime`), `TRAVEL_ID` (`varchar(50)`) |
| `TN_MVMN_CONSUME_HIS` | 교통비 내역 | `TRAVEL_ID`, 이동수단·결제 구분, 결제 시각 (`datetime`), 결제 금액 (`int(11)`); 코드·설명 필드는 문자열 계열 |
| `TN_LODGE_CONSUME_HIS` | 숙박 소비 내역 | `TRAVEL_ID`, 숙박 유형, 체크인·체크아웃 (`datetime`), 결제 금액 (`int(11)`) 및 결제 정보 |
| `TN_ADV_CONSUME_HIS` | 여행 전 소비 내역 | `TRAVEL_ID`, 구매·상점·결제 정보, 결제 금액 (`int(11)`); 결제 시각은 `datetime` |
| `TN_VISIT_AREA_INFO` | 방문지 정보 | `TRAVEL_ID`, `VISIT_AREA_ID`, 방문지명, 시작·종료일 (`date`), 위치·POI·방문 유형·만족/재방문 의향 필드 |
| `TN_TOUR_PHOTO` | 관광 사진 메타데이터 | `TRAVEL_ID`, `VISIT_AREA_ID`, 사진 식별·이름·형식·경로·해상도·좌표; 촬영 시각은 `datetime` |
| `TN_ACTIVITY_HIS` | 활동 내역 | `TRAVEL_ID`, `VISIT_AREA_ID`, 활동 유형·세부 내용·지출/입장료 구분 |
| `TN_ACTIVITY_CONSUME_HIS` | 활동 소비 내역 | `TRAVEL_ID`, `VISIT_AREA_ID`, 활동 유형 코드, 결제 금액 (`int(11)`) 및 상점·결제 정보 |
| `TN_POI_MASTER` | POI 정보 | `POI_ID`, POI명, 분류·주소·좌표 필드; 설명서 선언은 문자열 계열 |
| `TC_SGG` | 시군구 코드 테이블 | `SGG_CD`, 시도·시군구·읍면동·리 코드 및 명칭 |
| `TC_CODEA` / `TC_CODEB` | 코드 리스트 / 코드 상세 | 공식 페이지와 설명서가 용도를 정의한다. 모든 코드 컬럼·허용값은 여기서 확정하지 않는다. |

## 식별자, 코드 참조, JSON

- **[공식 문서 사실]** 설명서는 여행객·여행·방문지·사진 관련 식별 컬럼을 정의하며, 일부 시군구 코드 컬럼에 `TC_SGG` 참조를 명시한다. 표준 CSV 이름의 권역 코드 `E`는 수도권이다. 공식 페이지는 GPS CSV를 여행객별 파일로 설명하고, 사진·캡션 JSON의 이름 요소 및 JSON의 `Info`, `images`, `caption`, `licenses` 구획을 설명한다.
- **[공식 문서 사실]** 설명서의 코드 범위를 로컬 표·필드명에 연결한 내용은 다음과 같다. 범위는 공식 허용 코드 정의이지 관측 빈도나 실제 값의 예가 아니다.

  | 공식 테이블 | 공식 필드 | 허용 범위 |
  | --- | --- | --- |
  | `TN_TRAVELLER_MASTER` | `EDU_NM`, `EDU_FNSH_SE`, `MARR_STTS`, `JOB_NM`, `JOB_ETC`, `INCOME`, `HOUSE_INCOME`, `TRAVEL_TERM` | 각각 1–8, 1–5, 1–5, 1–13, 1–3, 1–12, 1–12, 1–4 |
  | `TN_TRAVELLER_MASTER` | `TRAVEL_STYL_1`–`TRAVEL_STYL_8` | 각각 1–7 |
  | `TN_TRAVELLER_MASTER` | `TRAVEL_MOTIVE_1`–`TRAVEL_MOTIVE_3` | 각각 1–10 |
  | `TN_TRAVEL` | `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK` | 두 필드 모두 허용 도메인은 `(1–13) ∪ (21–28)` |
  | `TN_COMPANION_INFO` | `REL_CD`, `COMPANION_GENDER`, `COMPANION_AGE_GRP`, `COMPANION_SITUATION` | 각각 1–11, 1–2, 1–8, 1–3 |
  | `TN_MOVE_HIS` | `MVMN_CD_1`, `MVMN_CD_2` | 각각 1–16 및 50 |
  | `TN_MVMN_CONSUME_HIS` | `MVMN_SE` | 1–16 및 50 |
  | `TN_LODGE_CONSUME_HIS` | `LODGING_TYPE_CD`, `PAYMENT_MTHD_SE` | 각각 1–12, 1–5 |
  | `TN_ACTIVITY_HIS` | `ACTIVITY_TYPE_CD`, `EXPND_SE`, `ADMISSION_SE` | 각각 1–7 및 99, 1–5, 1–2 |
  | `TN_VISIT_AREA_INFO` | `VISIT_AREA_TYPE_CD`, `VISIT_CHC_REASON_CD`, `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION` | 각각 1–13 및 21–24, 1–11, 1–5, 1–5, 1–5 |

- **[공식 문서 사실]** 설명서는 거주·선호 시군구 코드와 일부 소비/방문 시군구 코드에서 `TC_SGG` 참조를 표시한다. 필드의 의미상 공통 여행·방문·POI·사진 식별자도 이름을 정의하지만, 문서에서 이를 PK/FK 제약으로 선언하지 않는다.
- **[공식 문서 사실]** HWP에서 `TRAVEL_MISSION`은 개별 미션(`MIS`), `TRAVEL_MISSION_CHECK`는 미션 우선도(`MIS`)이며 두 필드 모두 `(1–13) ∪ (21–28)` 범위를 선언한다. `EXPND_SE`는 지출 구분(`EXP`)이며 1–5 범위를 선언한다. 설명서는 `TC_CODEA`를 코드 리스트, `TC_CODEB`를 코드 상세 테이블로 정의한다.
- **[추론]** 반복되는 `TRAVEL_ID`, 방문지 식별 필드, POI 식별 필드, 사진 식별 필드는 잠재 연결 후보로 볼 수 있다. 이름·필수 여부만으로 PK/FK, 유일성, 실제 조인 성립을 주장할 수 없다.
- **[공식 문서 사실]** 캡션 JSON의 `Info` 구획은 데이터셋명·상세 설명, `images`는 사진 식별/파일 메타데이터와 방문지·랜드마크 정보, `caption`은 캡션·토큰·시각 정보, `licenses`는 라이선스 ID·이름을 담도록 설명한다. 설명서의 이미지·캡션 필드에는 문자열 계열 자료형이 기재돼 있다. 필드 그룹마다 필수 여부 표기가 다르다.
- **[공식 문서 사실]** AI Hub 배포 목록은 `SbL`을 서브라벨링 JSON 자료 묶음으로 분류한다.
- **[로컬 기록]** 저장소의 승인 기록은 `SbL` 자료 묶음의 사용을 승인한다. JSON 구조 검사는 임의의 상위 입력 트리에서 파일명을 추측하지 않고, 실행자가 지정한 해당 승인 자료 묶음의 추출 루트를 대상으로 한다. HWP가 정의한 JSON 확장자와 문서화된 구조만 검사 대상이다.
- **[공식 문서 사실]** HWP의 JSON 필드 allowlist는 `Info`의 `DATASET_NM`, `DATASET_DETAIL`; `images`의 `PHOTO_FILE_ID`, 사진 파일명·저장경로·해상도·촬영일시·X/Y 좌표, `VISIT_AREA_NM`, `LANDMARK`; `caption`의 `IMG_CAPTION`, 정수형 `TOKEN`, `TIME_STAMP`; `licenses`의 `NAME`을 포함한다. `images` 구획에 `VISIT_AREA_ID`는 정의돼 있지 않다.
- **[로컬 집계 관측]** focused code interpretation은 `TC_CODEA`/`TC_CODEB`에서 `MIS`와 `EXP` 그룹만 메모리에서 대조했다. 세 이상 필드의 delimiter 구성요소는 각각 HWP 도메인과 해당 상세 코드 그룹에 정확히 대응했다. 전체 코드 사전이나 다른 그룹을 검증한 것은 아니다.
- **[로컬 집계 관측]** 승인된 `SbL` archive에서 JSON 멤버만 분리한 뒤 명시적 JSON root에 대해 focused structure/linkage 검사를 완료했다. 이전 broad pre-selector aggregate는 새 collection 결과의 근거로 사용하지 않는다. bucket 결과는 EDA 보고서에 기록했다.
- **[미확인]** 코드 그룹의 전체 허용값·상세 매핑은 이 참조에 포함하지 않았다. 최초 profiler 실행에는 codebook이 입력되지 않았다. 실제 캡션·토큰 내용이나 라이선스 이름은 검토하지 않았다.

## 기존 수도권 aggregate와의 대조

- **[로컬 집계 관측]** 기존 프로파일의 컬럼 라벨 집계에는 설명서가 정의한 스키마 라벨과 일치하는 항목이 여러 개 포함돼 있다. JSON alias의 최상위 구획은 공식 JSON 구조와 대응한다. 정확한 일치 건수나 소규모 테이블별 컬럼 집계는 보고하지 않는다.
- **[로컬 집계 관측]** profiler 실행 당시에는 설명서 기반 codebook이 제공되지 않았다. 순번 alias는 원본 경로가 아닌 정렬 순서에서 생성돼 개별 CSV 테이블 의미를 자동으로 보존하지 않는다. 이후 메모리 내 basename 패턴과 CSV 헤더를 공식 표·필드에 대조해 매핑 가능한 코드 필드만 제한적으로 검증했다. null·빈 문자열·모든 공백 문자만 있는 값은 결측으로 분류했으며, 그 외 값은 문자열을 정규화하지 않고 비교했다. 전용 sanitized 집계 산출물에는 비결측 코호트 구간과 결측·도메인 밖 행의 `0`, `<10`, `10+` 구간만 기록하고 관측값은 포함하지 않는다. 이는 generic profile의 `codebook_check.csv`와 별도이며, generic 산출물은 k 이상일 때 정확한 행·고유값 수를 기록한다. JSON 중첩 구조는 이후 별도 checker로 HWP allowlist에 한정해 키 존재·타입·빈 상태·배열 여부와 사진 ID 연결 후보를 집계했다. JSON 원문 값은 산출물에 포함하지 않았다.
- **[미확인]** 기존 aggregate의 추론 자료형을 개별 공식 테이블·컬럼 선언 자료형과 안전하게 1:1 대조하지 않았다. 표준 CSV 역할별 cohort가 작으므로 table-specific 결과를 공개하면 k=10 기준을 낮출 수 있다. DuckDB의 추론 타입을 설명서의 선언 타입으로 간주하지 않는다.
- **[로컬 집계 관측]** 스키마 대조에는 개인정보 검토를 마친 aggregate와 basename·확장자 기반 패턴 요약을 사용했다. 기존 JSON 구조 aggregate는 `SbL` 명시적 루트 선택 전의 checker 결과이므로 `SbL` 전용으로 보지 않는다. 코드 도메인 검증을 위해서는 매핑된 표의 문서화된 코드 열만 메모리에서 순차 확인했다. 원본 전체 profiler는 재실행하지 않았고, 코드값·행·파일명은 저장하거나 출력하지 않았다.
