# 2023 국내 여행로그 4개 권역 EDA 보고서

Issue #12의 EDA 파이프라인과 보고 양식이다. 이 문서에는 안전한 집계와 데이터 구조 설명만 기록한다. 원본 행, 여행자 ID, 정확한 GPS 좌표, 장소명, 정확한 날짜·timestamp, 사진 캡션 같은 예시 레코드는 기록하지 않는다.

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| EDA 스크립트(`scripts/eda/`) | 구현됨. 세 번의 전체 scan은 결과 작성 전에 graceful interrupt 되었고 artifact/temp는 정리됨 |
| 의존성·lock(`pyproject.toml`, `uv.lock`) | 기록됨 |
| 권역별 다운로드 승인 | **확인됨** (사용자 확인, 2026-10-06) |
| 권역별 `datasetkey`·`filekey`·용량 | **확인됨** (공식 Shell 목록 모드 결과) |
| 다운로드할 파일 선택 | **정함** (아래 "다운로드 계획") |
| 공식 이용·취급 조건 | **확인됨** (AI Hub 개방 데이터 이용정책; 파일별 추가 조건 표시는 확인되지 않음) |
| API Key | 사용자 로컬 `pass` 저장소에만 보관. 성공한 Shell 다운로드 모드 호출에서 인증됨. 키 값은 기록하지 않음 |
| 수도권 파일 | 승인된 8개 범주의 파일이 지정된 로컬 위치에 추출됨. 기존 `VL_csv` 인증 확인 파일은 재다운로드하지 않음 |
| 원본 보관 | 사용자가 지정한 로컬 raw root 하위에서 읽기 전용으로 사용. 실제 경로는 문서에 기록하지 않음 |
| 수도권 pilot | **프로파일링·집계 재억제·read-only 재검토 완료**. 모든 tabular 입력을 검사했고 linkage-pair 검사는 최대 20개로 제한. 결과와 checksum inventory는 계속 로컬에만 유지 |
| 4개 권역 EDA | **미완료**. 이번 실행 범위는 수도권 pilot만임 |
| 실제 분석 결과 | 수도권 집계 산출물 생성됨. 이 문서에는 literal 범주값·원본 레코드·파일명을 기록하지 않음 |

## 근거와 출처

### 승인·Shell 메타데이터 (확인됨)

- 출처: Issue #12 댓글 [`#issuecomment-6015260227`](https://github.com/haeinChoe/Travel-Recommendation/issues/12#issuecomment-6015260227)
- 사용자가 네 권역의 다운로드 승인 완료를 확인했다(2026-10-06). 목록은 `aihubshell -mode l` 및 `-mode l -datasetkey <key>` 결과이며 `dataSetSn`에서 `datasetkey`를 추정하지 않았다. 용량은 목록의 반올림 표기다.

| 권역 | slug | datasetkey | Other | TS_photo | TL_csv | TL_gps_data | VS_photo | VL_csv | VL_gps_data | SbL |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 수도권 | `capital` | 71776 | 539782 (386 MB) | 539783 (70 GB) | 539784 (3 MB) | 539785 (90 MB) | 539786 (9 GB) | 539787 (489 KB) | 539788 (11 MB) | 549764 (15 GB) |
| 서부권 | `west` | 71779 | 539802 (386 MB) | 539803 (73 GB) | 539804 (4 MB) | 539805 (164 MB) | 539806 (9 GB) | 539807 (559 KB) | 539808 (20 MB) | 549767 (16 GB) |
| 동부권 | `east` | 71778 | 539793 (386 MB) | 539794 (66 GB) | 539795 (4 MB) | 539796 (187 MB) | 539797 (8 GB) | 539798 (583 KB) | 539799 (21 MB) | 549766 (14 GB) |
| 제주·도서 | `jeju-islands` | 71780 | 541665 (386 MB) | 541666 (69 GB) | 541667 (5 MB) | 541668 (236 MB) | 541669 (8 GB) | 541670 (780 KB) | 541671 (29 MB) | 549769 (15 GB) |

괄호 앞은 `filekey`, 괄호 안은 Shell 목록의 용량 표기다.

### 공식 어노테이션·데이터 구조와 pilot 대응

이 절의 각 항목은 **[공식 문서 사실]**, **[로컬 집계 관측]**, **[추론]**, **[미확인]**으로 근거 수준을 구분한다. 출처는 [AI Hub 국내 여행로그 데이터(수도권, 2023) 상세페이지](https://aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71776&topMenu=100)다.

- **[공식 문서 사실]** 2026-10-07 확인 시 페이지의 데이터 버전 표시는 1.2였고, 버전 변경이력은 2024-12-04 서브라벨링 추가를 기록한다. 페이지의 별도 데이터 히스토리에는 이후 구축업체 정보 수정 이력이 표시된다.

- **[공식 문서 사실]** 페이지는 CSV/JPG/JSON 형식을 설명하고, 표준 CSV 이름에 영문 테이블명·한글 설명·권역 코드가 들어가며 `E`가 수도권이라고 정의한다. GPS CSV 이름은 `tn_gps_coord_{여행객 ID}.csv` 형태이고 여행객별 파일로 설명한다. `Other`는 POI Master 1set으로 설명한다. 사진과 캡션 JSON의 이름 규칙은 여행자·여행일 순번·경로·사진 구분·활동·사진 순번 요소를 담는 구조로 설명한다.
- **[공식 문서 사실]** 캡션 JSON 예시는 `Info`, `images`, `caption`, `licenses` 네 최상위 구획과 각각 데이터셋 정보, 이미지 메타데이터, 캡션 정보, 라이선스 정보의 역할을 보여 준다. 이미지 메타데이터 설명에는 시간·좌표·방문지 관련 필드도 포함된다. 예시 레코드의 값은 이 보고서에 옮기지 않았다.
- **[공식 문서 사실]** 사용자가 제공한 수도권 데이터 설명서를 읽기 전용으로 확인했다. 설명서는 표별 컬럼명·의미·선언 자료형·필수 여부를 제공한다. 근거가 된 필드와 선언 내용은 [수도권 스키마 참조](aihub-71776-capital-schema.md)에 정리했다. 설명서 파일의 별도 개정 표시는 확인되지 않았다.
- **[미확인]** 상세페이지에 연결된 다운로드 문서 링크는 읽을 수 있는 본문을 반환하지 않았고, 구축·활용 가이드의 내용도 확인되지 않았다. 따라서 해당 가이드에 근거한 주장은 포함하지 않는다.
- **[로컬 집계 관측]** 기존 `files_inventory.csv`의 순번 라벨은 원본 파일 경로가 아니라 정렬 순서로 생성된다. 이번 메타데이터 전용 확인에서는 basename·확장자·디렉터리 구조만 메모리에서 보고 이름 규칙을 분류했다. 표준 수도권 CSV 패턴은 11개, GPS 이름 접두 패턴은 2,880개, 사진 패턴은 3,047개, 캡션 JSON 패턴은 3,047개였다. 코드표·POI 보조 CSV 집단, 검사한 표준 CSV 권역 접미사 오류, JPG/JSON 이름 형태 불일치, 미분류 확장자 및 심볼릭 링크 집단은 각각 `<10`으로 표시한다. GPS는 공식 접두 패턴까지만 분류했고 ID 구성의 세부 형식은 검증하지 않았다. 11개 표준 CSV의 세부 테이블별 수는 공개하지 않고 k=10 억제 규칙을 적용한다. 원본 파일명이나 여행객 ID는 저장·출력하지 않았다.
- **[로컬 집계 관측]** 기존 프로파일의 3,047개 JSON 순번 라벨은 모두 최상위 object였고, 집계 스키마의 최상위 필드명은 공식 페이지가 제시한 네 JSON 구획과 모두 대응했다. 이는 최상위 구조 대응만 확인한 결과다. 프로파일러의 JSON 구조 요약은 키 이름을 보존하지 않으며, 열어 둔 집계 스키마만으로 중첩 필드 각각의 의미나 실제 JSON 내용은 확인하지 않았다.
- **[로컬 집계 관측]** 기존 `columns.csv`에는 설명서 필드명과 일치하는 스키마 라벨이 여러 개 있으나, 집계의 순번 alias만으로 개별 CSV 테이블에 필드 의미·선언 자료형을 연결해 보고하지 않는다. DuckDB 추론 자료형은 설명서 선언 자료형을 대체하지 않는다.
- **[공식 문서 사실]** AI Hub 페이지는 수도권 GPS 데이터 구축 규모를 3,200set으로 제시한다.
- **[로컬 집계 관측]** 메타데이터 전용 basename 확인에서 GPS 파일명 접두 패턴은 2,880개였다. 사진과 캡션 JSON 이름 패턴은 각각 3,047개였다.
- **[추론]** 공식 GPS set 수와 로컬 GPS 파일명 패턴 수가 다르지만, 분모나 배포 범위의 차이일 수 있어 이 차이만으로 파일 누락을 입증하지 않는다. 원인은 확인되지 않았다. 사진과 캡션 JSON의 개수 일치만으로 쌍별 내용이나 완전성을 보장하지 않는다.
- **[추론]** CSV/JPG/JSON의 큰 범주와 캡션 JSON의 네 최상위 구획은 공식 구조 설명과 대응한다고 볼 수 있다. 순번 라벨에서 각 CSV의 공식 테이블 역할을 개별 공개하거나 컬럼 품질 지표를 그 역할에 연결하면 k 미만 단일 표 집단을 드러낼 수 있으므로 하지 않는다.
- **[미확인]** 개별 CSV alias를 개별 공식 테이블 정의에 연결한 안전한 보고, 코드 허용값 대조, GPS·여행·방문 기록의 실제 조인, 사진과 JSON의 쌍별 내용 대응은 검증하지 않았다. 설명서가 필드 의미를 정의해도 profiler의 추론 스키마만으로 로컬 alias의 의미·키·조인을 확정하지 않는다.

### 공식 이용·취급 조건

- 수도권 데이터 상세페이지에는 별도 데이터 이용조건 문구가 표시되지 않았다. AI Hub의 [개방 데이터 이용정책](https://aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105)을 확인했다.
- 해당 정책은 AI 데이터 사용을 AI 학습모델 용도로 제한하고, AI Hub/NIA 사업 결과임을 밝히며, 승인받지 않은 제3자 제공·열람과 개인 재식별을 금지한다. 국외 이용·반출에는 별도 합의가 필요하다. 개인정보 등이 발견되면 AI Hub에 신고하고 내려받은 데이터셋을 삭제하도록 안내한다.
- 이 pilot은 Issue #12의 추천모델 개발을 위한 로컬 구조·품질 확인에만 사용한다. 외부 서비스·공유 저장소로 원본을 보내지 않는다. 이용정책을 넘어서는 사용은 하지 않는다.
- 원본에서 개인정보로 볼 수 있는 내용을 발견하면 분석을 중단하고 AI Hub 신고 등 필요한 조치를 확인한다. 원본 삭제를 포함한 조치는 현재의 불변 원본 지침과 충돌할 수 있으므로 임의로 수행하지 않고 사용자에게 보고한다.

## 실행 환경

- Python 3.12 (`.python-version`), `uv`, 의존성: `duckdb`, `pandas`, `matplotlib`, `seaborn` (`uv.lock`으로 고정)
- 환경 재현 명령: `uv sync --locked`를 Agy가 시도했다. 성공 여부는 확인되지 않았다.
- CLI 도움말: Agy가 `profile_travel_log.py --help`와 `compare_regions.py --help`를 각각 시도했다. 성공 여부는 확인되지 않았다. 재시도하지 않음.
- DuckDB `memory_limit`은 실행 시점의 `MemAvailable` 25%를 1~16 GiB로 제한해 자동 지정하고 `run_metadata.json`에 기록한다. `--memory-limit`으로 덮어쓸 수 있다.
- DuckDB `temp_directory`는 `results/eda/travel-log-2023/tmp/<권역>-<pid>/`이며 종료 시 삭제한다. DuckDB는 `:memory:`로 열어 DB 파일을 만들지 않고, 확장 자동 설치를 끈다.
- 수도권 pilot 원본은 사용자가 지정한 로컬 입력 경로에 보관한다. 실제 경로는 이 문서에 기록하지 않는다. 프로파일러는 `--raw-root`로 명시한 경로와 그 하위 입력만 허용하고, 입력 파일은 읽기 전용으로 다룬다. 경로 내 symlink와 출력 경로 이탈을 차단한다.

## 다운로드 계획

Issue의 목적(CSV/JSON/GPS·POI 구조 분석, 사진 파일 수·형식·크기 메타데이터)을 충족하기 위해 권역마다 **Shell 목록의 8개 파일 전부**를 대상으로 한다.

| 파일 | 선택 이유 |
| --- | --- |
| `TL_csv`, `VL_csv` | CSV 테이블 구조·품질 (학습/검증 분할 모두) |
| `TL_gps_data`, `VL_gps_data` | GPS 테이블 구조·품질 |
| `Other` | POI Master (공식 구조 자료 기준) |
| `SbL` | JSON 소스 여부를 공식 구조와 파일 목록으로 확인. 파일 구성 확인 후에도 제외할지는 결과 보고서에 근거와 함께 기록 |
| `TS_photo`, `VS_photo` | 사진 파일 수·형식·크기 메타데이터. 이미지 내용은 열지 않음 |

### 디스크 여유 공간 확인

- AI Hub는 선택한 다운로드 용량의 2~3배 여유 공간을 다운로드·압축 해제에 권장한다.
- 각 다운로드 batch 직전에 실제 대상 파일시스템의 여유 공간을 확인하고, 선택한 파일 용량과 권장 여유 공간을 충족하는지 판단한다. `df`의 표시만으로 호스트 저장 공간을 추정하지 않는다.
- 다운로드 현황과 원본 보관 위치는 현재 상태 표에 기록한다. 개인 시스템의 디스크 용량·가용 공간은 이 보고서에 기록하지 않는다.

## 현재 pilot 진행 상태와 blocker

Issue #12의 승인 기록과 수도권 승인 filekey는 확인했다. AI Hub 상세페이지 및 개방 데이터 이용정책도 확인했다. 수도권 8개 범주의 파일은 지정 위치에 추출되어 있다. 세 번의 이전 프로파일링 시도는 결과 artifact 작성 전에 graceful interrupt 되었고 임시 폴더도 정리했다. 네 번째(capital) 실행은 2026-10-06 18:32:56–20:18:52 UTC에 완료했다. 모든 tabular 입력을 검사했으며 linkage-pair 검사는 최대 20개로 제한했다. 결과는 `results/eda/travel-log-2023/capital/`에 생성됐다.

- 기존 인증 확인 파일은 재사용했으며 중복 다운로드하지 않았다. 모든 추가 작업은 승인된 수도권 범위에 한정한다.
- 세 번의 중단된 profiler 실행은 graceful interrupt 후 임시 폴더까지 정리했다. 완료된 실행은 checksum을 포함한 집계 산출물을 만들었고 원본은 변경하지 않았다.
- 사용자가 제공한 공식 HWP 설명서의 코드 도메인을 필드별로 대조했다. 사진 파일은 메타데이터만 집계한다.
- 입력·terms gate와 코드 안전장치 read-only 재검토가 완료됐다. 완료된 실행은 추출된 수도권 원본만 대상으로 하며, 서부·동부·제주·도서 권역과 권역 비교는 포함하지 않았다.

## 수도권 pilot 실행 순서

1. 이미 승인·추출된 수도권 원본만 처리한다. 기존 `VL_csv` 인증 확인 파일은 다시 받지 않는다. 분석에는 API Key가 필요하지 않다.
2. 권역별 프로파일링. 먼저 Issue에 해당 데이터셋의 공식 이용·취급 조건 확인 기록이 있어야 한다. `--confirm-approved`와 `--confirm-terms`는 승인/권한 확인과 이용 조건 확인에 대한 별도 사용자 선언이다:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --offline python scripts/eda/profile_travel_log.py \
     --raw-root "$AIHUB_RAW_ROOT" \
     --input "$AIHUB_CAPITAL_INPUT" \
     --output results/eda/travel-log-2023/capital \
     --confirm-approved --confirm-terms --max-relation-pairs 20
   ```

   `AIHUB_CAPITAL_INPUT`은 사용자가 지정한 `AIHUB_RAW_ROOT` 하위의 추출 디렉터리를 가리킨다. 실제 로컬 경로는 보고서나 셸 예시에 기록하지 않는다.

3. 결과 CSV·그림을 사람이 검토해 비식별 여부를 확인한 뒤, 안전한 집계만 아래 결과 섹션에 옮긴다. 비교 스크립트는 수도권 pilot 범위 밖이다.

## 스크립트가 하는 일

| 영역 | 동작 |
| --- | --- |
| 파일 | 표 데이터는 실제 파일명·경로 대신 생성한 순번 라벨과 크기·sha256을 기록. 사진은 확장자별 개수·크기만 집계하며 파일명·경로·이미지 헤더·내용을 읽지 않음. 기타 파일의 미확인 확장자는 `<other>`로 합침 |
| 스키마 | DuckDB 추론 컬럼명·타입. CSV는 UTF-8/UTF-16만 처리하고 그 외 인코딩은 `unsupported_encoding`으로 기록 |
| 규모·품질 | 행 수, 컬럼별 결측·고유값 수·중복값 행 수, 완전 중복 행 수, 빈 문자열, NaN/Inf |
| 분포 | 정확한 수치 min/max/mean/stddev/분위수는 출력하지 않음(단일 관측값과 일치할 수 있음). 유효·음수·0 개수만 k 미만 억제 규칙으로 기록. 저카디널리티 빈도도 코호트/셀 기준 k 억제 |
| 날짜 | 날짜형 값은 **연-월 단위** 빈도만 기록. 전체 유효 코호트가 k 미만이면 요약 전체를 억제하며, 소수 월이 억제되는 경우 정확한 관측 범위도 기록하지 않음. 잘못된 연-월 수는 k 미만이면 `<k`로 표시 |
| 키·연결 | 단일 컬럼 유일성 진단과 제한된 same-name 컬럼 연결 후보를 평가. 연결 metrics는 모든 distinct/unmatched counts가 k 이상일 때만 함께 공개하며, 하나라도 작으면 비율을 포함한 전체 metric bundle을 억제 |
| 코드북 | generic profile의 `--codebook`은 공식 허용 목록과 문자열 정확 비교하며 sub-k metrics만 억제하고 k 이상 행·고유값 수는 정확히 유지. 별도 focused validator만 `0`, `<10`, `10+` 구간을 사용 |
| JSON | `json` 표준 라이브러리로 최상위 구조 확인(값과 키 이름 미기록; 배열 요소의 키 수 분포만 집계) + DuckDB 스키마 |

### 값 노출 억제 규칙 (휴리스틱)

컬럼 의미를 확인하기 전에 쓰는 구조 기준이므로 과억제·누락 가능성이 있다. 억제 사유는 `columns.csv`의 `value_policy`와 `anomalies.csv`에 남는다. 결과 공유 전에 사람이 검토한다.

- 컬럼명 토큰이 좌표(lat, lon, x, y, gps, 위도, 경도 등)이거나 식별자(id, no, seq, key, 번호 등)이면 값 통계 억제
- 컬럼명 토큰이 이름·텍스트·주소류(name, nm, caption, addr, poi, 장소, 주소 등)이면 값 빈도 억제. 공식 구조 자료로 행정구역 등 공개 가능한 범주임을 확인한 컬럼만 `--allow-value-column`으로 허용하며 허용 목록은 `run_metadata.json`에 기록
- 실수형 값이 −180~180 범위이고 고유값 비율이 50% 이상이면 좌표 가능성으로 억제
- 정수형이 epoch 초/밀리초 범위이거나 고유값 비율이 90% 이상이면 억제
- 문자열의 평균 길이가 40 초과이거나 고유값 비율이 20% 초과이면 자유 텍스트·식별자 가능성으로 억제
- 컬럼이 200개를 넘는 표는 컬럼명을 `col_NNNN`으로 대체
- 억제 범주가 하나뿐이어서 합계로 역산되는 경우를 막기 위해 병합 합계가 k 미만이면 가장 작은 공개 범주도 병합
- exact numeric min/max/mean/stddev/quantile은 어느 값이든 한 관측값과 일치할 수 있어 출력하지 않는다. 검토된 코드북 기반 구간화가 마련되기 전까지는 k 기준으로 억제한 유효·음수·0 counts와 억제 사유만 남긴다.
- 관계 후보 생성은 정규화한 컬럼명과 테이블별 최고 고유값 수 컬럼을 사용해 lazy heap merge로 제한한다. 전체 cross-table 조합을 생성하거나 정렬하지 않는다. heap frontier는 이름 그룹당 첫 pair 하나만 만들고, 선택된 pair마다 다음 후보 하나만 추가하므로 후보 생성량은 그룹 수 + 처리 상한에 비례하며 메모리는 입력 컬럼 수 + 상한에 비례한다. 최대 `max_relation_pairs` 후보를 처리하고, 상한에 도달하고 추가 후보가 있으면 정확한 조합 수 대신 `at_least_<N>`을 기록한다. 이번 수도권 실행은 `--max-relation-pairs 20`으로 모든 tabular 파일은 계속 분석하되 상위 20개 linkage pair만 확인한다. 나머지 낮은 우선순위 연결 후보는 미검토다. 낮은 우선순위 후보와 같은 테이블의 동명 컬럼 대안은 생략될 수 있다. 후보 값은 비교 시 VARCHAR로 변환하므로 서로 다른 원본 타입의 같은 문자열 표현이 연결 후보로 잡힐 수 있다.

## 산출물 (Git 제외)

`results/eda/travel-log-2023/<slug>/`: `profile.json`, `run_metadata.json`, `files_inventory.csv`, `photo_summary.csv`, `other_files_summary.csv`, `tables.csv`, `columns.csv`, `numeric_summary.csv`, `categorical_values.csv`, `date_months.csv`, `relations.csv`, `codebook_check.csv`, `json_structure.csv`, `anomalies.csv`

`results/eda/travel-log-2023/comparison/`: `region_summary.csv`, `schema_groups.csv`, `column_presence.csv`, `date_ranges.csv`, `comparison.json`, `schema_group_rows.png`, `null_rate_heatmap.png`

기존 결과가 있으면 중단하며, `--overwrite`는 위 파일만 교체한다. 기존 결과 파일이나 출력 폴더가 심볼릭 링크이거나 출력 폴더 밖으로 해석되면 중단한다. 입력은 저장소 기본 `data/raw/` 또는 명시한 `--raw-root` 하위여야 하며 경로 내 symlink는 거부한다. 외부 원본 루트를 사용할 때도 출력은 `results/eda/travel-log-2023/` 하위여야 한다. 비교 스크립트는 입력 폴더명과 라벨이 `capital`, `west`, `east`, `jeju-islands` 중 하나로 정확히 일치하는 네 프로필을 요구한다.

## 수도권 pilot 결과

2026-10-06 20:18:52 UTC에 수도권 프로파일링이 정상 종료됐다. 실행은 전체 입력을 사용했으며 `k=10`, `max_relation_pairs=20`, checksum 활성화, codebook 미제공 설정이었다. 공식 설명서는 프로파일 실행 후 해석에 사용했으며 기존 aggregate만 대조했다. 원본 행과 literal 범주값은 이 문서에 옮기지 않았다. 산출물은 로컬의 ignored `results/eda/travel-log-2023/capital/`에만 있다.

- **[로컬 집계 관측] 파일·스키마:** CSV 2,895개와 JSON 3,047개, 총 5,942개 입력 파일이 모두 프로파일링 성공 상태였다. 26,800개 컬럼의 추론 유형은 nested 12,188, varchar 5,856, float 5,764, datetime 2,894, integer 98개였다. JSON 3,047개는 모두 최상위 object 구조로 확인됐다. 스키마 참조의 의미는 공식 설명서 사실이며, 개별 순번 alias의 field-level 로컬 의미 매핑은 미확인이다.
- **[로컬 집계 관측] 품질 요약:** 2,880개 표 프로파일에 완전 중복 행 진단이 있었고, 5,768개 컬럼은 상수값 진단을 받았다. 전체 결측·빈 문자열 진단의 건수는 k=10 미만이므로 `<10`으로 억제한다. 값 자체나 표별 세부 건수는 보고하지 않는다.
- **[로컬 집계 관측] 분포·날짜 프라이버시:** 수치 요약은 컬럼별로 안전한 count 상태와 억제 사유만 남기며 exact min/max/mean/stddev/quantile 필드는 없다. 범주·날짜·수치의 모든 count/rate는 코호트와 셀 기준 k=10 억제를 통과한 값만 남긴다. 정확한 날짜는 사용하지 않고 월 단위 결과만 대상으로 하며, 작은 코호트에서는 요약 전체와 범위도 억제한다. 로컬 정형 점검은 지정한 일부 패턴만 탐지하므로 의미 기반 비식별 보증이 아니다.
- **[로컬 집계 관측] 키·연결:** 단일 컬럼 유일성 진단은 일부 표 alias에서 후보를 표시했으나 후보 수는 `<10`으로 억제한다. same-name 관계 후보 검사는 최대 20쌍으로 제한됐다. 공개 가능한 relation 결과는 없었다.
- **[미확인] 키·연결 해석:** 설명서가 식별자 컬럼의 의미를 정의하지만, 유일성 진단은 공식 키 정의가 아니며 실제 로컬 키·관계·조인을 입증하지 않는다. 상한 이후 및 낮은 우선순위 연결은 검토하지 않았다.
- **[로컬 집계 관측] 사진:** 이미지 내용이나 헤더를 열지 않고 메타데이터만 집계했다. JPG 패턴 파일은 3,047개였고, 프로파일 집계에는 파일명 없이 확장자별 개수와 크기 합계만 남았다.
- **[공식 문서 사실] 코드 의미:** HWP는 `TRAVEL_MISSION`을 개별 미션(`MIS`), `TRAVEL_MISSION_CHECK`를 미션 우선도(`MIS`)로 정의하며 두 필드에 같은 `(1–13) ∪ (21–28)` 도메인을 선언한다. `EXPND_SE`는 지출 구분(`EXP`)이고 1–5 도메인이다. `TC_CODEA`/`TC_CODEB`는 각각 코드 리스트와 코드 상세 테이블이다.
- **[로컬 집계 관측] 코드 도메인 이상:** `scripts/eda/validate_capital_codebook.py`가 HWP 도메인과 정확 비교한 결과 세 필드 모두 도메인 밖 행이 `10+`였다. 후속 `scripts/eda/interpret_capital_codebook.py`는 대상 코드 열과 `TC_CODEA`/`TC_CODEB`의 해당 참조 열만 메모리에서 비교했다. 세 필드 각각에서 모든 이상 행이 delimiter 구성을 보였고, 분리된 각 구성요소는 해당 필드의 HWP 허용 도메인 및 `MIS` 또는 `EXP` 상세 코드 참조와 정확히 일치했다. 전용 artifact에는 원본 문자열 없이 세 필드와 원인 분류, 코호트·이상 건수의 `10+` bucket만 기록된다.
- **[추론] 코드 이상 해석:** 관측은 허용 코드 여러 개가 구분자로 결합된 직렬화일 가능성을 강하게 뒷받침한다. 다만 HWP는 해당 구분자나 필드의 복수선택 저장 방식을 설명하지 않으므로 이를 정당한 복수응답이라고 확정할 수 없다. 따라서 원자료 오류로 단정하지 않으며 값 정규화·분리는 하지 않았다. 공백만인 값은 결측으로 제외했고, 그 외 구성요소는 정규화 없이 정확 비교했다.
- **[재현 명령] 코드 검증:** 추출 입력과 raw root는 로컬 shell 변수에 설정한 뒤 실행한다:

  ```bash
  .venv/bin/python scripts/eda/validate_capital_codebook.py \
    --raw-root "$AIHUB_RAW_ROOT" \
    --input "$AIHUB_CAPITAL_INPUT" \
    --output results/eda/travel-log-2023/capital/codebook_validation.csv \
    --overwrite
  ```

  원인 분류와 code reference 대조는 다음 focused command로 재현한다:

  ```bash
  .venv/bin/python scripts/eda/interpret_capital_codebook.py \
    --raw-root "$AIHUB_RAW_ROOT" \
    --input "$AIHUB_CAPITAL_INPUT" \
    --output results/eda/travel-log-2023/capital/codebook_interpretation.csv \
    --overwrite
  ```

  `AIHUB_RAW_ROOT`와 `AIHUB_CAPITAL_INPUT`은 실행 전에 로컬 shell에서 설정하며, 입력은 지정한 raw root 안이어야 한다. 전용 `codebook_validation.csv`는 코호트·결측·mismatch의 `0`, `<10`, `10+` 구간 및 상태만 기록한다. 해석 결과는 별도 `codebook_interpretation.csv`에 역할·필드·cause class와 구간 bucket만 기록한다. 어느 artifact에도 원본 경로·파일명·fingerprint·관측 코드 문자열·정확한 count는 없다. 두 focused artifact는 generic profile의 `codebook_check.csv`와 다르며, generic 산출물은 k 이상 값에 정확한 행·고유값 수를 유지한다. 기존 inventory와 run metadata에는 경로 또는 fingerprint가 있을 수 있으므로 모든 profile artifact가 그런 정보를 제외한다고 일반화하지 않는다.
- **[미확인] 코드·비교:** 참조 대조는 `MIS`와 `EXP` 그룹으로 한정했다. 전체 `TC_CODEA`/`TC_CODEB` 사전, 다른 그룹, delimiter의 공식 저장 의미는 확인되지 않았다. 권역 비교도 이번 수도권 pilot 범위 밖이다.
- **[공식 문서 사실] JSON 구조:** 설명서는 `Info`를 데이터셋 정보, `images`를 사진·방문지·랜드마크 메타데이터, `caption`을 캡션·토큰·시각 정보, `licenses`를 라이선스 정보 구획으로 정의한다.
- **[공식 문서 사실] JSON allowlist:** HWP는 `Info`의 `DATASET_NM`, `DATASET_DETAIL`; `images`의 사진 ID·파일명·저장경로·해상도·촬영일시·좌표, `VISIT_AREA_NM`, `LANDMARK`; `caption`의 `IMG_CAPTION`, 정수형 `TOKEN`, `TIME_STAMP`; `licenses`의 `NAME`을 정의한다. JSON schema에는 `VISIT_AREA_ID`가 없다.
- **[로컬 집계 관측] SbL 자료 식별·추출:** Issue의 승인된 수도권 선택 기록과 대조되는 로컬 package archive의 중앙 디렉터리 metadata에서 JSON 자료를 확인했다. 별도 manifest는 없었다. 이 package의 JSON 멤버만 별도 로컬 child로 추출하고 사진 멤버는 열거나 복사하지 않았다. archive 중앙 디렉터리의 entry 수와 크기는 `zipfile`이 전체 member metadata를 적재하기 전에 제한했고, 경로 깊이 제한과 정렬 기반 충돌 검사를 적용했다. archive 안의 absolute member 경로는 출력 대상 루트 아래 상대 경로로 재기준화했으며, traversal·symlink·중복·file/directory 충돌 여부와 inspector 파일·총량 한도를 확인했다. 추출기는 새 mode-0700 output wrapper와 그 안의 `json` child를 각각 `mkdir(exist_ok=False)`로 원자 예약한 뒤 해당 private child에만 JSON을 쓴다. 실패 시에는 이번 실행이 만든 child와 비어 있는 wrapper reservation만 정리하고 archive 및 기존 경로는 보존한다. CRC, 선언 크기, 최종 inventory를 검증했고 다운로드 크기의 3배를 기준으로 추출 전 여유 공간을 확인했다. 경로와 파일명, checksum은 출력·보고하지 않았다.
- **[로컬 집계 관측] JSON 구조:** focused checker는 명시적으로 지정한 추출된 `SbL` JSON root만 처리했다. `document_cohort`, `parsed_document_cohort`, `root_object_cohort`, `root_type_object`는 각각 `10+`; `root_type_array`와 parse errors는 각각 `0` bucket이다. `root_object_cohort`는 성공적으로 파싱된 JSON 중 최상위 object인 문서 수를 뜻하고, `root_type_object`는 root-type 분포의 object bucket이다. 정확히 문서화된 `Info` 키는 present `0`, missing `10+`였고, 따라서 두 allowlist 필드도 각각 present `0`, missing `10+`였다. 그 원인이나 다른 키 대소문자 변형의 의미는 확인하지 않았다. `images`, `caption`, `licenses`는 각각 object `10+`였으며, 이 세 구획의 allowlist 필드는 present `10+`, missing `0`이었다. 해당 필드 타입은 공식 선언 자료형에 부합하는 string이었고 `caption.TOKEN`은 number였다. 모든 allowlist 필드의 array-type bucket은 `0`이다. `images.VISIT_AREA_NM` 및 `LANDMARK`의 empty와 nonempty는 각각 `10+`; `Info` 외 다른 allowlist 필드의 empty bucket은 `0`이었다. 값의 내용은 출력하거나 보고하지 않았다.
- **[로컬 집계 관측] JSON photo ID 연결 범위·출처:** HWP의 capital suffix 규칙과 일치하는 `TN_TOUR_PHOTO` 역할 파일 선택은 유일했고, 선택된 파일의 키 열을 끝까지 읽었다. key 열 누락 행·빈 cell·공백뿐인 값·정확 중복 키 그룹·중복 초과 행은 각각 `0` bucket이었다. 이 입력에는 해당 열을 선언하는 다른 CSV header가 없었다. Issue 기록은 capital `TL_csv` 선택을 승인하지만 local CSV의 경로에는 category 표시가 없다. 별도 provenance-only mode는 명시적으로 지정한 archive metadata에서 `TL_csv` 범주 표시를 확인하고, 해당 범주 및 capital 사진 테이블 역할 규칙에 맞는 member만 선택해 local CSV와 member의 SHA-256을 메모리에서 비교한다. archive를 추출하지 않는다. ignored provenance artifact에서 archive role candidates와 category-marked role members, hash matches는 각각 `<10` bucket이며 match 상태는 `yes_unique`다. 승인 filekey marker와 version 1.2 marker는 각각 `0` bucket이다. hash·경로·파일명은 저장하거나 출력하지 않는다. 따라서 local `TL_csv` 범주 수준의 유일한 내용 대응은 재현되지만, Issue의 승인 filekey나 version과 archive를 잇는 local marker는 확인되지 않았다. 전체 행 스캔은 지정 입력에서 발견한 역할 파일에만 적용되며 원 승인 package의 완전성이나 version을 입증하지 않는다.
- **[로컬 집계 관측] JSON photo ID exact 및 순차 후보 분류:** JSON의 비결측 `PHOTO_FILE_ID`는 문자열만 비교에 포함했다. JSON ID 누락/null·빈 문자열·공백뿐인 문자열·비문자열 값은 각각 `0` bucket이었다. exact 비교에서 matched 고유 ID와 unmatched 고유 ID는 각각 `10+` bucket이었다. exact-unmatched ID 집합에 trim-only를 적용했을 때 새 후보는 `0`; 그 후 남은 ID에 trim+casefold를 적용했을 때의 추가 후보도 `0`; 최종 미매칭은 `10+` bucket이었다. 각 변환이 새 정규화 키 충돌을 만든 경우와 각 단계 후보가 table 중복 행 또는 JSON 내부 정규화 충돌로 모호해지는 경우도 모두 `0` bucket이었다. 이 분류는 후보 비교일 뿐 변환된 조인으로 사용하지 않았다.
- **[로컬 집계 관측] 미매칭 원인·범위:** 현재 증거로는 공백, 대소문자, table 키 결측 또는 exact 중복이 미매칭 원인이라는 설명을 지지하지 않는다. 확인한 수도권 입력의 다른 CSV header에서는 `PHOTO_FILE_ID`가 발견되지 않았다. 실제 HWP는 `TN_TOUR_PHOTO.PHOTO_FILE_ID`와 SbL JSON `images.PHOTO_FILE_ID`를 정의하지만, ID를 파일명·저장경로에서 생성하거나 서로 변환하는 규칙은 제공하지 않는다. 따라서 파일명/경로 변환은 시도하지 않았다. 다른 권역·collection은 이번 진단 범위 밖이다.
- **[미확인] JSON photo ID 미매칭 및 provenance 잔여 공백:** 남은 unmatched의 실제 원인은 확인되지 않았다. 재현 가능한 provenance artifact는 local CSV와 `TL_csv` 범주로 식별된 archive 내 역할 member의 유일한 내용 일치를 기록하지만, 승인 filekey marker와 version marker는 확인되지 않았다. 따라서 현재 증거로는 archive를 승인 기록의 정확한 filekey 또는 version에 연결할 수 없다. 이 증거만으로 package 누락·불완전성을 주장할 수도 없다. 다른 권역·collection은 검사하지 않았다. 공식 웹페이지의 dataset version 표시는 로컬 CSV의 version 증거가 아니며, 정규화 후보 결과로 유효한 조인 규칙이나 데이터 오류를 단정하지 않는다.
- **[재현 명령] table/archive provenance:** `AIHUB_RAW_ROOT`, `AIHUB_CAPITAL_INPUT`, `AIHUB_CAPITAL_TL_CSV_ARCHIVE`, `AIHUB_CAPITAL_TL_CSV_FILEKEY`는 승인 자료에 따라 로컬 shell에서만 지정한다. archive는 `AIHUB_RAW_ROOT` 안의 명시적 후보여야 하며 filekey 값은 Issue 승인 기록과 대조하기 위한 로컬 metadata marker로만 사용한다. JSON은 읽지 않고 지정 table 및 해당 archive의 role/category 표식이 있는 CSV member만 chunk 단위로 hash한다. artifact는 ignored `photo_id_archive_provenance.csv`다.

  ```bash
  .venv/bin/python scripts/eda/diagnose_capital_photo_id_links.py \
    --raw-root "$AIHUB_RAW_ROOT" \
    --input "$AIHUB_CAPITAL_INPUT" \
    --archive "$AIHUB_CAPITAL_TL_CSV_ARCHIVE" \
    --approved-filekey "$AIHUB_CAPITAL_TL_CSV_FILEKEY" \
    --output results/eda/travel-log-2023/capital/photo_id_archive_provenance.csv \
    --overwrite --provenance-only
  ```

- **[재현 명령] JSON photo ID 진단:** full focused 진단은 지정한 capital input의 유일한 capital `TN_TOUR_PHOTO` 역할 파일 전체와 명시적인 SbL JSON root를 사용한다. JSON ID·table key는 메모리에서만 비교하고 산출물에는 `0`, `<10`, `10+` bucket과 안전한 상태 label만 기록한다. CSV는 typed NULL convention이 문서화되어 있지 않아 빈 cell과 whitespace-only cell을 별도로 집계하며, 이를 의미상 NULL과 동일시하지 않는다. 다음 실행에는 provenance 검사에 쓰는 동일한 archive·filekey 환경 변수가 필요하다.

  ```bash
  .venv/bin/python scripts/eda/diagnose_capital_photo_id_links.py \
    --raw-root "$AIHUB_RAW_ROOT" \
    --input "$AIHUB_CAPITAL_INPUT" \
    --json-root "$AIHUB_CAPITAL_JSON_ROOT" \
    --archive "$AIHUB_CAPITAL_TL_CSV_ARCHIVE" \
    --approved-filekey "$AIHUB_CAPITAL_TL_CSV_FILEKEY" \
    --output results/eda/travel-log-2023/capital/photo_id_linkage_diagnosis.csv \
    --overwrite
  ```

  결과는 ignored local artifact `photo_id_linkage_diagnosis.csv`이며, generic profile의 상세 행·유일값 출력과 별도다.
- **[로컬 집계 관측] 재현성 대조:** 유지관리되는 JSON 전용 추출 스크립트로 만든 fresh `json` child를 사용해 focused checker를 다시 실행했다. 새 결과의 sanitized CSV 행은 앞선 alias 수정 후 scan과 bucket·상태까지 동일했다. 비교는 메모리에서 수행했으며, raw JSON 값이나 파일 metadata를 비교 결과로 내보내지 않았다.
- **[재현 명령] SbL JSON 추출·구조 검사:** 실행 전에 `AIHUB_RAW_ROOT`, `AIHUB_CAPITAL_INPUT`(승인된 기존 추출 입력), `AIHUB_CAPITAL_SBL_ARCHIVE`를 로컬 shell 변수로 지정한다. `AIHUB_CAPITAL_JSON_BUNDLE`은 그 입력의 아직 존재하지 않는 새 child로 지정한다. 추출기는 archive가 raw root 안에 있고 bundle이 capital input의 새 child인지 확인한다. mode-0700 bundle 생성은 원자적 예약이며 inspector 입력은 그 안의 `json` child다. archive는 덮어쓰거나 삭제하지 않는다. 동일 bundle 경로가 이미 존재하면 새 전용 child 이름을 지정한다.

  ```bash
  AIHUB_CAPITAL_JSON_BUNDLE="$AIHUB_CAPITAL_INPUT/sbl-json-maintained"
  .venv/bin/python scripts/eda/extract_capital_sbl_json.py \
    --archive "$AIHUB_CAPITAL_SBL_ARCHIVE" \
    --raw-root "$AIHUB_RAW_ROOT" \
    --capital-input "$AIHUB_CAPITAL_INPUT" \
    --output "$AIHUB_CAPITAL_JSON_BUNDLE" \
    --confirm-approved --confirm-terms

  AIHUB_CAPITAL_JSON_ROOT="$AIHUB_CAPITAL_JSON_BUNDLE/json"
  .venv/bin/python scripts/eda/inspect_capital_json.py \
    --raw-root "$AIHUB_RAW_ROOT" \
    --input "$AIHUB_CAPITAL_INPUT" \
    --json-root "$AIHUB_CAPITAL_JSON_ROOT" \
    --output results/eda/travel-log-2023/capital/json_structure_linkage_reproduced.csv \
    --overwrite
  ```

- **[추론] 추천·TourAPI 활용:** 비빈 `IMG_CAPTION` string은 로컬 content-based topic/semantic features를 시험할 후보이고, `TOKEN`은 공식 정의상 integer라 실제 언어 토큰인지 의미를 별도 코드북 없이 단정할 수 없다. `PHOTO_FILE_ID`는 내부 사진 메타데이터 연결 일부에 유용하지만 partial matches와 `VISIT_AREA_ID` 부재 때문에 JSON만으로 visit-level join을 만들 수 없다. 비빈 방문지명·랜드마크 문자열은 TourAPI 검색 후보가 될 수 있다는 정도의 추론이며, 안정적 entity key·유일성·정확도는 확인되지 않았다.
- **[미확인] JSON 효용·한계:** 캡션·토큰·장소명·랜드마크·라이선스 이름의 값과 이미지 내용은 열람하지 않았다. 따라서 언어·캡션 품질, TOKEN의 계산 방식, photo ID 미매치 원인, TourAPI 매칭률, 라이선스별 사용 허용, 추천 성능 효과는 알 수 없다. 최소 다음 단계는 이용·라이선스 조건을 다시 검토한 뒤 로컬에서만 allowlisted caption feature를 추출하고, raw text 없이 품질과 추천 지표를 k-억제 집계로 비교하는 소규모 평가다. 외부 API/LLM으로 텍스트를 전송하지 않는다.
- **[로컬 집계 관측] 개인정보 보호 검토:** 첫 read-only 리뷰는 여러 산출물에 k 미만 코호트의 정확한 count/rate가 남아 있음을 발견했다. 기존 집계 profile만 사용해 당시 억제 로직을 보완·재생성했으며, 이후에는 별도 focused validation만 수행했다. 확인한 집계 산출물의 사후 점검은 k 억제 일관성을 확인했으나 모든 profile artifact가 경로·fingerprint를 제외한다고 뜻하지 않는다. 기존 inventory와 run metadata에는 입력 식별 또는 checksum 같은 민감 재현 metadata가 포함될 수 있어 계속 로컬 ignored 상태로 유지하고 공유하지 않는다. 새 focused-validation 산출물은 `0`, `<10`, `10+` 구간만 보유하며 generic `codebook_check.csv`의 k 이상 정확 count와 별도다. 이 휴리스틱은 의미 기반 재식별 위험을 보증하지 않는다.
- **[로컬 집계 관측] 실행 범위:** 수도권 pilot만 완료됐다. 서부권·동부권·제주·도서 권역 및 4개 권역 비교는 미완료다.

## 한계와 후속 결정 후보

- 사용자가 제공한 공식 설명서로 주요 테이블·컬럼 의미, 선언 자료형, 일부 공식 코드 도메인을 확인했다. 연결된 구축·활용 가이드는 확인하지 못했다. 코드 대조는 명확히 매핑 가능한 필드에 한정되며 전체 `TC_CODEA`/`TC_CODEB` 사전 검증은 아니다.
- 행정구역 수준 위치 집계는 공식 구조 확인 후 `--allow-value-column` 지정이 필요하다. 좌표 자체는 집계에 쓰지 않는다.
- 중첩 JSON은 자동으로 펼치지 않는다(펼치는 기준이 데이터 의미에 의존).
- CSV가 UTF-8/UTF-16이 아니면 변환하지 않고 중단 기록만 남긴다. 변환은 행 단위 파생 파일을 만들기 때문에 별도 결정이 필요하다.
- 발견한 품질 문제를 고치지 않고, 결과 검토 후 전처리 결정 후보로 기록한다.
