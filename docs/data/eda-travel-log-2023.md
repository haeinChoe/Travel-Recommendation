# 2023 국내 여행로그 4개 권역 EDA 보고서

Issue #12의 EDA 파이프라인과 보고 양식이다. 이 문서에는 안전한 집계와 데이터 구조 설명만 기록한다. 원본 행, 여행자 ID, 정확한 GPS 좌표, 장소명, 정확한 날짜·timestamp, 사진 캡션 같은 예시 레코드는 기록하지 않는다.

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| EDA 스크립트(`scripts/eda/`) | 구현됨. 과거 중단 실행의 임시 artifact는 정리됨. 2026-10-08 West 후속 profile·fit·SbL 구조 분석은 별도 ignored 결과로 완료 |
| 의존성·lock(`pyproject.toml`, `uv.lock`) | 기록됨 |
| 권역별 다운로드 승인 | **확인됨** (사용자 확인, 2026-10-06) |
| 권역별 `datasetkey`·`filekey`·용량 | **확인됨** (공식 Shell 목록 모드 결과) |
| 다운로드할 파일 선택 | **정함** (아래 "다운로드 계획") |
| 공식 이용·취급 조건 | **확인됨** (AI Hub 개방 데이터 이용정책; 파일별 추가 조건 표시는 확인되지 않음) |
| API Key | 사용자 로컬 `pass` 저장소에만 보관. 성공한 Shell 다운로드 모드 호출에서 인증됨. 키 값은 기록하지 않음 |
| 수도권 파일 | PR #14의 과거 pilot 입력으로 Shell 목록 8개 범주가 추출됨. 사진 archive 포함은 당시 이력이며 후속 권역 입력 요구가 아님 |
| 원본 보관 | 사용자가 지정한 로컬 raw root 하위에서 읽기 전용으로 사용. 실제 경로는 문서에 기록하지 않음 |
| 수도권 pilot | **프로파일링·집계 재억제·read-only 재검토 완료**. 모든 tabular 입력을 검사했고 linkage-pair 검사는 최대 20개로 제한. 결과와 checksum inventory는 계속 로컬에만 유지 |
| 4개 권역 EDA | **4개 권역 구조·추천 적합성 EDA 실행 완료, 필드별 관측값 의미 검증 일부 미완료**. 네 권역 프로파일·C 집계·비교 및 SbL 허용 필드 포함률·후보 연결 산출물이 생성됨. West/East/Jeju의 문서 매핑 필드는 제한 검사했으며, 일부 값은 직접 대응 미확인이고 수도권은 기존 일부 검증만 재사용함. East 프로파일 숫자 종료 코드는 보존되지 않았으며 권역 밖 방문 검사는 미확인 |
| 실제 분석 결과 | 수도권 역사 기록과 네 권역 safe aggregate를 로컬에 생성함. 이 문서에는 원본 레코드·식별자·캡션·정확 좌표·정확 count/rate를 기록하지 않음 |

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

괄호 앞은 `filekey`, 괄호 안은 Shell 목록의 용량 표기다. 이 표는 전체 공식 Shell 인벤토리의 근거 기록이며, 사진 행은 후속 다운로드 목록이 아니다.

### 공식 어노테이션·데이터 구조와 pilot 대응

이 절의 각 항목은 **[공식 문서 사실]**, **[로컬 집계 관측]**, **[추론]**, **[미확인]**으로 근거 수준을 구분한다. 출처는 [AI Hub 국내 여행로그 데이터(수도권, 2023) 상세페이지](https://aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71776&topMenu=100)다.

- **[공식 문서 사실]** 2026-10-07 확인 시 페이지의 데이터 버전 표시는 1.2였고, 버전 변경이력은 2024-12-04 서브라벨링 추가를 기록한다. 페이지의 별도 데이터 히스토리에는 이후 구축업체 정보 수정 이력이 표시된다.

- **[범위 구분]** 아래 사진 파일·스키마 사실과 수도권 사진 집계는 PR #14의 과거 수도권 pilot 기록이다. 현재 후속 권역 정책은 사진 archive의 다운로드, binary metadata 검사, 사진 파일 수·형식·크기 집계를 요구하지 않는다. 후속 JSON 작업은 승인된 `SbL`의 JSON 구조·스키마 coverage·후보 linkage만 다룬다.

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
- **[이전 HEAD 검증, 2026-10-07]** 요청된 `uv sync --locked`는 기본 uv cache의 쓰기 오류로 exit 2였다. 별도 임시 cache로 실행한 sync는 성공했고 lock 변경은 없었다. 두 결과는 구분해 기록한다.
- **[이전 HEAD 검증]** Ruff 실행 파일이 프로젝트 환경과 로컬 offline cache에 없어 Ruff lint를 실행하지 못했다. 네트워크 설치나 의존성 변경은 하지 않았다.
- **[이전 HEAD 검증]** `uv run python -m compileall scripts/eda`는 성공했다.
- **[현재 HEAD 검증]** 다음 7개 CLI의 `--help`가 모두 exit 0으로 끝나 import/argument parsing을 확인했다: `profile_travel_log.py`, `compare_regions.py`, `diagnose_capital_photo_id_links.py`, `extract_capital_sbl_json.py`, `inspect_capital_json.py`, `interpret_capital_codebook.py`, `validate_capital_codebook.py`. `compare_regions.py`는 Matplotlib cache 경고 후 임시 cache를 사용했지만 도움말 실행은 성공했다.
- **[현재 HEAD 검증]** 기존 합성 안전성 테스트 `.venv/bin/python -m unittest discover -s tests -p 'test_eda_safety_smoke.py'`는 3개 통과했다. k=10 complementary suppression, symlink 뒤 `..` 차단, CLI 입력 경로 guard를 확인하므로 이 범위에는 새 테스트를 추가하지 않았다.
- **[미실행]** 전체 수도권 원본 프로파일링 및 다른 권역 분석은 재실행하지 않았다. 기존 pilot aggregate는 이번 검증에서 새로 계산하지 않았다.
- DuckDB `memory_limit`은 실행 시점의 `MemAvailable` 25%를 1~16 GiB로 제한해 자동 지정하고 `run_metadata.json`에 기록한다. `--memory-limit`으로 덮어쓸 수 있다.
- DuckDB 임시 작업 폴더는 권역·실행별로 분리하며 종료 시 삭제한다. DuckDB는 `:memory:`로 열어 DB 파일을 만들지 않고, 확장 자동 설치를 끈다.
- 수도권 pilot 원본은 사용자가 지정한 로컬 입력 경로에 보관한다. 실제 경로는 이 문서에 기록하지 않는다. 프로파일러는 `--raw-root`로 명시한 경로와 그 하위 입력만 허용하고, 입력 파일은 읽기 전용으로 다룬다. 경로 내 symlink와 출력 경로 이탈을 차단한다.

## 후속 권역 다운로드 계획

후속 west/east/jeju-islands 분석은 승인된 표·GPS·보조자료와 SbL JSON에 한정한다. 사진 archive(`TS_photo`, `VS_photo`)는 다운로드하거나 검사하지 않는다. 전체 Shell 인벤토리는 위 표에 근거 기록으로 남지만 다운로드 선택에는 포함하지 않는다.

| 파일 | 후속 목적 |
| --- | --- |
| `TL_csv`, `VL_csv` | 각 split의 표 구조·coverage·추천 적합성 지표 |
| `TL_gps_data`, `VL_gps_data` | GPS 파일·테이블 구조 및 요청된 coverage·품질 점검 |
| `Other` | POI Master 및 코드/POI 보조자료의 구조·연결 후보 |
| `SbL` | 이미지 payload 없이 JSON schema 구조, allowlisted 필드 coverage, photo-ID 후보 linkage를 안전 집계 |

Shell 목록의 반올림 용량 기준으로 선택 파일은 west 약 16.575 GB, east 약 14.599 GB, jeju-islands 약 15.657 GB이며 세 권역 합계는 약 47.831 GB다. 파일 시스템 여유 공간은 다운로드·압축 해제 가이드의 2–3배 기준으로 전체 batch 약 95.7–143.5 GB를 확보한다. 권역별 순차 처리의 3배 상한은 west 약 49.8 GB, east 약 43.8 GB, jeju-islands 약 47.0 GB다. 실제 다운로드 직전에 Shell 용량과 대상 볼륨의 여유를 다시 확인한다. 이 추정은 사진 archive를 제외하고 SbL JSON archive를 포함한다.

### 디스크 여유 공간 확인

- AI Hub는 선택한 다운로드 용량의 2~3배 여유 공간을 다운로드·압축 해제에 권장한다.
- 각 다운로드 batch 직전에 실제 대상 파일시스템의 여유 공간을 확인하고, 선택한 파일 용량과 권장 여유 공간을 충족하는지 판단한다. `df`의 표시만으로 호스트 저장 공간을 추정하지 않는다.
- 다운로드 현황과 원본 보관 위치는 현재 상태 표에 기록한다. 개인 시스템의 디스크 용량·가용 공간은 이 보고서에 기록하지 않는다.

## 수도권 pilot 이력과 기존 결과

Issue #12의 승인 기록과 수도권 승인 filekey는 확인했다. AI Hub 상세페이지 및 개방 데이터 이용정책도 확인했다. 과거 수도권 pilot은 당시 선택한 8개 범주를 사용했으며 이 범위에는 사진 archive가 포함됐다. 세 번의 이전 프로파일링 시도는 결과 artifact 작성 전에 graceful interrupt 되었고 임시 폴더도 정리했다. 네 번째(capital) 실행은 2026-10-06 18:32:56–20:18:52 UTC에 완료했다. 모든 tabular 입력을 검사했으며 linkage-pair 검사는 최대 20개로 제한했다. 결과는 `results/eda/travel-log-2023/capital/`에 생성됐다. 이 과거 상태는 보존하며 후속 권역 정책으로 일반화하지 않는다.

- 기존 인증 확인 파일은 재사용했으며 중복 다운로드하지 않았다. 이 기록은 당시 수도권 pilot의 범위만 설명한다.
- 세 번의 중단된 profiler 실행은 graceful interrupt 후 임시 폴더까지 정리했다. 완료된 실행은 checksum을 포함한 집계 산출물을 만들었고 원본은 변경하지 않았다.
- 사용자가 제공한 공식 HWP 설명서의 코드 도메인을 필드별로 대조했다. 당시 수도권 pilot의 photo-file metadata 관측은 역사적 결과이며 후속 권역에는 적용하지 않는다.
- 입력·terms gate와 코드 안전장치 read-only 재검토가 완료됐다. 당시 실행은 추출된 수도권 원본만 대상으로 했으며, 서부·동부·제주·도서 권역과 권역 비교는 포함하지 않았다. 후속 네 권역 실행 상태는 아래 절에서 갱신한다.

## 후속 비사진 자료 확인 (2026-10-09)

- 네 권역 raw root에서 승인된 `Other`, `TL_csv`, `TL_gps_data`, `VL_csv`, `VL_gps_data`, `SbL` ZIP의 존재와 중앙 디렉터리 판독을 확인했다. 동부·제주 다운로드 로그에는 각 5개 CSV 역할의 완료 기록이 있다. West/East/Jeju 추출은 extractor의 사전 검사, 스트리밍 CRC/크기 확인 및 최종 inventory가 완료됐다. 수도권 추출물은 이전 실행 산출물로 재사용했으며 이번에 전체 CRC를 다시 검증하지 않았다. 원본 ZIP은 보존했다.
- 각 권역의 다섯 CSV 역할 추출물이 존재한다. 수도권 `VL_csv` 추출물은 다른 수도권 CSV 추출 디렉터리와 별도 경로에 있다. West/East/Jeju 추출물에는 5개 역할 디렉터리가 있다. 사진 ZIP이나 이미지 payload는 열거나 열거하지 않았다.
- 각 권역의 추출된 TL CSV에서 `TC_CODEA`, `TC_CODEB`, `TC_SGG` 테이블이 각각 확인됐고 header는 읽을 수 있었다. 기존 `validate_capital_codebook.py` 자체는 HWP에서 옮긴 수도권 domain과 `_E.csv` 패턴에 한정되지만, 그 명시 target-field list 중 같은 이름의 38개 컬럼이 각 권역 TL/VL 역할 테이블 header에 있었다. 해당 컬럼만 한 번씩 스트리밍해 지역별 `TC_CODEA/B` reference union과 대조했다. 세부는 아래 코드표 후보 coverage 절에 기록한다. `TC_SGG`는 존재하지만 validator target list와 같은 이름으로 연결되는 field는 없어 이번 값 대조에서 제외했다.
- SbL JSON은 ZIP에서 직접 스트리밍해 검사했고 JSON을 별도 추출하지 않았다. 아래 allowlist field coverage와 같은 권역의 `TN_TOUR_PHOTO` CSV 후보 linkage도 안전 집계했다.
- 원본 HWP 설명서는 Downloads에서 수도권 `119-145` (동일 문서 사본 `(2)` 포함), 서부권 `119-147`, 동부권 `119-146`, 제주·도서권 `119-148` 파일을 찾았다. 이번 WSL 실행 환경에서는 HWP 원본을 직접 변환하지 못했다. 네 권역 설명서의 기존 Markdown 변환본은 PR #15에서 `dev`에 병합됐으며 현재 작업 트리의 `docs/data/travel-log-2023/`에 있다.

### Four-region execution evidence and exits

| 권역 | archive·download evidence | CSV extraction | profile / EDA status |
| --- | --- | --- | --- |
| capital | 승인된 다섯 CSV 역할과 SbL ZIP이 기존 raw root에 있었고 ZIP central directory를 읽었다. 기존 download exit marker는 이번 실행 기록에서 확인하지 않았다. | 과거 추출물 재사용. 다섯 역할 산출물 확인; 이번에는 전체 CRC를 다시 실행하지 않음 | 역사적 profile 완료. 기존 수도권 결과 보존; 수도권 combined traveler/trip cardinality 재계산 안 함 |
| west | 다섯 CSV 역할과 SbL ZIP 존재 및 central directory 판독 확인. | 다섯 CSV 역할 추출에서 declared size, CRC 및 최종 inventory 검증 완료 | full/TL/VL profile과 West C 완료; 이전 기록의 profile 실행 exit 0. SbL structure/field linkage도 완료 |
| east | 다섯 structured CSV 역할의 `ROLE_COMPLETE` 기록과 batch completion marker 확인; SbL ZIP은 직접 구조/필드 분석 가능. numeric downloader exit marker는 보존되지 않음 | 다섯 CSV 역할 추출의 CRC, declared size 및 최종 inventory 검증 완료 | profile completion log marker와 필수 artifact 확인; numeric East profile exit marker는 기록되지 않음. East C exit 0 |
| jeju-islands | 다섯 structured CSV 역할의 `ROLE_COMPLETE` 기록과 batch completion marker 확인; SbL ZIP은 직접 구조/필드 분석 가능. numeric downloader exit marker는 보존되지 않음 | 다섯 CSV 역할 추출의 CRC, declared size 및 최종 inventory 검증 완료 | 사용자 확인 `JEJU_PROFILE_EXIT=0`; Jeju C exit 0 |

- 사진 archive는 후속 다운로드 역할에 포함하지 않았고 `TS_photo`/`VS_photo` filekey 호출, ZIP 열기, listing, extraction, image payload 접근은 하지 않았다. 기존 수도권 pilot의 사진 메타데이터 결과는 역사적 기록으로만 유지한다.
- 4개 권역 comparison exit 0 (`comparison-four-region-followup`), integrated C exit 0 (`readiness-four-region-integrated`), SbL field/linkage exit 0 (`sbl-fields-linkage-four-region`), targeted code-table membership exit 0 (`code-table-coverage-summary`). East와 Jeju focused C도 각각 exit 0이다. East profile은 종료 artifact로 완료를 확인했으나 숫자 exit marker는 남지 않았다.
- 최종 소규모 검증: extractor/archive unittest 19개 통과, EDA safety smoke 3개 통과, `compileall scripts/eda` 통과, 두 archive CLI `--help` exit 0, `git diff --check` 통과. Ruff는 executable/package가 offline cache에 없어 실행하지 못했다. 기존 read-only reviewer는 최종 수정 diff와 safe aggregate를 확인했고 actionable finding이 없다고 회신했다.

## 수도권 pilot 실행 순서

1. 이미 승인·추출된 수도권 원본만 처리한다. 기존 `VL_csv` 인증 확인 파일은 다시 받지 않는다. 분석에는 API Key가 필요하지 않다.
2. 권역별 프로파일링. 먼저 Issue에 해당 데이터셋의 공식 이용·취급 조건 확인 기록이 있어야 한다. `--confirm-approved`와 `--confirm-terms`는 승인/권한 확인과 이용 조건 확인에 대한 별도 사용자 선언이다:

   ```bash
   UV_OFFLINE=1 uv run --offline python scripts/eda/profile_travel_log.py \
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
| 파일 | 현재 serializer는 표 데이터를 실제 파일명·경로 대신 생성한 순번 라벨과 크기 구간으로 기록하고 sha256은 제외한다. 이전 legacy artifact에는 exact 크기나 sha256이 있을 수 있어 ignored 로컬 결과로만 보존한다. 사진은 확장자별 bucket 개수·크기 구간만 집계하며 파일명·경로·이미지 헤더·내용을 읽지 않음. 기타 파일의 미확인 확장자는 `<other>`로 합침 |
| 스키마 | DuckDB 추론 컬럼명·타입. CSV는 UTF-8/UTF-16만 처리하고 그 외 인코딩은 `unsupported_encoding`으로 기록 |
| 규모·품질 | 행 수, 컬럼별 결측·고유값 수·중복값 행 수, 완전 중복 행 수, 빈 문자열, NaN/Inf |
| 분포 | 정확한 수치 min/max/mean/stddev/분위수는 출력하지 않음(단일 관측값과 일치할 수 있음). 유효·음수·0 개수만 k 미만 억제 규칙으로 기록. 저카디널리티 빈도도 코호트/셀 기준 k 억제 |
| 날짜 | 날짜형 값은 **연-월 단위** 빈도만 기록. 전체 유효 코호트가 k 미만이면 요약 전체를 억제하며, 소수 월이 억제되는 경우 정확한 관측 범위도 기록하지 않음. 잘못된 연-월 수는 k 미만이면 `<k`로 표시 |
| 키·연결 | 단일 컬럼 유일성 진단과 제한된 same-name 컬럼 연결 후보를 평가. 연결 metrics는 모든 distinct/unmatched counts가 k 이상일 때만 함께 공개하며, 하나라도 작으면 비율을 포함한 전체 metric bundle을 억제 |
| 코드북 | generic profile의 `--codebook`은 공식 허용 목록과 문자열 정확 비교한다. 현재 serializer는 sub-k 억제·보완 억제를 적용하고 행·고유값 count를 `0`, `<10`, `10+` bucket으로 기록한다. serializer 변경 전 생성된 legacy artifact에는 k 이상 exact count가 남아 있을 수 있으며 ignored 로컬에만 보존한다. 별도 focused validator도 count bucket을 사용 |
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

`results/eda/travel-log-2023/<slug>-archive-metadata/`: `archive_metadata.csv`, `run_metadata.json` (SbL JSON structural metadata only; separate from profile comparison).

`profile.json`의 legacy `photo_summary`는 입력 트리에 우연히 존재하는 일반 이미지 파일을 확장자·크기 bucket으로 분류하는 방어적 파일 인벤토리다. 후속 권역에서 사진 archive를 요구하지 않으며, 새 region comparison은 photo count/size를 비교하지 않는다. PR #14 수도권 산출물은 재작성하지 않는다.

기존 결과가 있으면 중단하며, `--overwrite`는 위 파일만 교체한다. 기존 결과 파일이나 출력 폴더가 심볼릭 링크이거나 출력 폴더 밖으로 해석되면 중단한다. 입력은 저장소 기본 `data/raw/` 또는 명시한 `--raw-root` 하위여야 하며 경로 내 symlink는 거부한다. 외부 원본 루트를 사용할 때도 출력은 `results/eda/travel-log-2023/` 하위여야 한다. 비교 스크립트는 입력 폴더명과 라벨이 `capital`, `west`, `east`, `jeju-islands` 중 하나로 정확히 일치하는 네 프로필을 요구한다.

### SbL JSON 메타데이터 검사

`scripts/eda/inspect_travel_log_archives.py`는 명시적으로 지정한 승인 SbL ZIP의 직접 포함된 `.json` 멤버만 ZIP stream에서 메모리로 읽어 파싱한다. 사진 archive role은 지원하지 않는다. 사진 binary는 열거나 추출하지 않는다. JSON 파일도 디스크에 추출하지 않는다. 공개 결과는 최상위 JSON root type, 최상위 object의 key 개수 band(0, 1-4, 5-9, 10+), 최상위 직계 값/array 요소의 generic type 집계다. 실제 JSON key 이름·값·member 이름·경로·per-member 식별자는 저장하지 않는다. 별도 capital-only schema/linkage 검사 범위는 역사적 수도권 결과 절에 기록되어 있으며 후속권역에 그 결과를 일반화하지 않는다.

안전 한도는 archive당 중앙 디렉터리 최대 20,000 entries 및 32 MiB, 전체 선언 비압축 크기 최대 1 TiB, SbL JSON 최대 10,000 files·합계 1 GiB·파일별 16 MiB다. depth 64 초과, symlink, absolute/traversal 경로, 중복 case-insensitive 경로, 암호화된 JSON member는 거부한다. nested archive는 열지 않는다. 입력 ZIP은 명시적으로 지정하고 raw root 아래의 일반 파일이어야 하며 경로 구성요소 symlink를 거부한다. 출력 디렉터리는 새 경로여야 한다. 오류는 파일명·경로·원본 내용을 출력하지 않고 일반 안전 오류만 보고한다. 이 도구는 SbL package의 구조 요약 용도이며 이미지 존재·형식·크기 분석 도구가 아니다.

권역마다 output 경로를 새로 정해 다음 형태로 실행한다. 각 role은 해당 권역의 승인된 filekey에 해당하는 ZIP 하나를 가리켜야 한다. 값은 로컬 셸 변수로만 지정한다.

~~~bash
.venv/bin/python scripts/eda/inspect_travel_log_archives.py \
  --raw-root "$AIHUB_RAW_ROOT" \
  --region west \
  --archive "SbL=$AIHUB_WEST_SBL_ZIP" \
  --output results/eda/travel-log-2023/west-archive-metadata \
  --confirm-approved --confirm-terms
~~~

동일한 명령을 승인된 east와 jeju-islands에서 각각 별도 output으로 실행한다. 후속 권역에는 capital archive를 다시 넣지 않는다. 이 ZIP report는 SbL JSON의 generic structure만 요약하며 공식 필드별 coverage나 유효한 linkage를 단독으로 입증하지 않는다. 후속 SbL 결과가 준비되면 확인된 권역별 schema에 근거한 field coverage와 명시적인 linkage 후보만 별도 안전 집계로 기록하며 실제 연결 규칙으로 확정하지 않는다. 현재 generic inspector만으로는 field-level coverage/linkage를 측정하지 않는다. 사진 ZIP은 이 command 및 follow-up input 목록에 없다.

### 권역 CSV ZIP 추출

`scripts/eda/extract_travel_log_csvs.py`는 승인된 west/east/jeju-islands ZIP에서 명시한 역할의 CSV만 새 전용 폴더로 추출한다. `--raw-root`는 세 권역 디렉터리를 포함하는 상위 raw root이며, 도구는 그 아래 `2023-travel-log-<region>` 디렉터리가 실제 디렉터리로 존재하고 symlink 경로 구성요소가 없는지 확인한다. 모든 archive와 새 output은 선택한 동일 권역 디렉터리의 descendant여야 한다. 지원 역할은 `Other`, `TL_csv`, `TL_gps_data`, `VL_csv`, `VL_gps_data`이며 역할별 ZIP 하나를 반복 `--archive ROLE=PATH`로 지정한다. JSON과 사진은 추출하지 않는다. ZIP 내부 상대 경로는 `output/<ROLE>/` 아래 보존되므로 profile에는 output root를, recommendation-fit에는 각각 `TL_csv`와 `VL_csv` role root를 입력한다. 사용 전에 raw root 안의 ZIP 경로와 새 output 경로를 로컬 변수로 지정한다. output의 부모 디렉터리는 이미 존재해야 하며 output 자체는 없어야 한다.

```bash
.venv/bin/python scripts/eda/extract_travel_log_csvs.py \
  --raw-root "$AIHUB_RAW_ROOT" \
  --region west \
  --archive "Other=$AIHUB_WEST_OTHER_ZIP" \
  --archive "TL_csv=$AIHUB_WEST_TL_CSV_ZIP" \
  --archive "TL_gps_data=$AIHUB_WEST_TL_GPS_ZIP" \
  --archive "VL_csv=$AIHUB_WEST_VL_CSV_ZIP" \
  --archive "VL_gps_data=$AIHUB_WEST_VL_GPS_ZIP" \
  --output "$AIHUB_RAW_ROOT/2023-travel-log-west/extracted-csv-followup" \
  --confirm-approved --confirm-terms
```

동일한 명령 템플릿을 `--region east` 및 `--region jeju-islands`와 각 raw root·승인 ZIP 변수에 적용하고 권역별로 순차 실행한다. `--archive`는 실제로 profiling/C 입력에 필요한 ZIP만 지정할 수 있다. 이 도구는 각 입력과 새 output이 선택한 `2023-travel-log-<region>` 아래 있는지, 경로 구성요소에 symlink가 없는지 확인한다. 모든 ZIP의 중앙 디렉터리와 멤버 metadata를 먼저 검증한 뒤 추출을 시작한다. 입력당 최대 20,000개 member 및 32 MiB central directory, 최대 depth 64, archive 전체 선언 크기 16 GiB, CSV 최대 20,000개·파일당 4 GiB·합계 16 GiB 제한을 둔다. 필요한 여유 공간은 archive마다 `max(CSV 선언 크기 합계, ZIP 크기의 3배)` 이상이어야 한다.

절대·traversal·backslash·colon 경로, depth 초과, symlink/encrypted/대소문자 무시 중복 member, 파일-디렉터리 충돌, 손상된 또는 제한을 넘은 중앙 디렉터리와 과도한 선언 크기는 거부한다. CSV는 memory-bounded stream으로 기록하고 읽기 완료 시 CRC와 선언 크기를 검사한다. 추출 전후 archive 크기·mtime이 같고 최종 파일 inventory가 계획과 일치하는지 확인한다. 실패하면 이 실행이 생성한 output만 정리한다. archive는 보존한다. 로그에는 member 이름·경로와 정확한 파일 수·크기를 출력하지 않는다. 사진 파일 처리나 SbL JSON 검사는 별도의 작업이며, follow-up에서는 사진 archive를 입력하지 않는다.

#### 후속 profile·comparison·C 명령

CSV 추출이 끝난 권역에서만 아래 profile을 실행한다. 각 권역 output은 새 경로로 실행하고 수도권 profile을 재계산하지 않는다. `AIHUB_WEST_CSV_ROOT`는 west의 새 CSV 추출 output, 즉 `TL_csv`·`VL_csv` role 폴더를 포함하는 root로 지정한다. east와 jeju-islands도 동일하게 별도 실행한다.

```bash
.venv/bin/python scripts/eda/profile_travel_log.py \
  --raw-root "$AIHUB_RAW_ROOT" \
  --input "$AIHUB_WEST_CSV_ROOT" \
  --output results/eda/travel-log-2023/west \
  --region-label west \
  --confirm-approved --confirm-terms
```

세 권역 profile이 준비되면 기존 수도권 profile을 포함해 네 권역 비교를 한 번 수행한다. 새 output 경로를 사용한다.

```bash
.venv/bin/python scripts/eda/compare_regions.py \
  --inputs results/eda/travel-log-2023/capital \
    results/eda/travel-log-2023/west \
    results/eda/travel-log-2023/east \
    results/eda/travel-log-2023/jeju-islands \
  --output results/eda/travel-log-2023/comparison-followup
```

recommendation-fit 통합 후보에는 기존 capital TL/VL 입력과 새 권역별 `TL_csv`, `VL_csv` role root만 지정한다. 아래는 명령 형태다. 모든 입력 변수는 해당 raw root 아래의 지정된 추출 디렉터리를 가리키며, output은 아직 없는 ignored 경로여야 한다.

```bash
.venv/bin/python scripts/eda/analyze_recommendation_fit.py \
  --raw-root "$AIHUB_RAW_ROOT" \
  --input "capital:TL=$AIHUB_CAPITAL_TL_CSV_ROOT" \
  --input "capital:VL=$AIHUB_CAPITAL_VL_CSV_ROOT" \
  --input "west:TL=$AIHUB_WEST_CSV_ROOT/TL_csv" \
  --input "west:VL=$AIHUB_WEST_CSV_ROOT/VL_csv" \
  --input "east:TL=$AIHUB_EAST_CSV_ROOT/TL_csv" \
  --input "east:VL=$AIHUB_EAST_CSV_ROOT/VL_csv" \
  --input "jeju-islands:TL=$AIHUB_JEJU_CSV_ROOT/TL_csv" \
  --input "jeju-islands:VL=$AIHUB_JEJU_CSV_ROOT/VL_csv" \
  --output results/eda/travel-log-2023/readiness-four-region-followup \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

SbL inspector는 같은 후속 권역별 SbL ZIP을 `--archive "SbL=$AIHUB_<REGION>_SBL_ZIP"`로 한 번씩 직접 지정한다. inspector는 CSV 추출과 별개이며 archive 내 JSON member만 stream 처리한다. 현재 inspector가 제공하는 것은 generic root/key-count/type 요약뿐이며, field-level coverage/linkage를 완료했다고 간주하지 않는다. 이 명령들에 TS_photo/VS_photo 경로 또는 photo archive가 들어가지 않는다.

### ignored EDA 산출물의 안전 출력 계약

새 profile·region comparison·recommendation-fit 산출물에는 exact count를 쓰지 않는다. count는 `0`, `<10`, `10+`로 버킷화하고, 이미 버킷화된 지역 값을 합칠 때 경계가 모호하면 `suppressed`로 둔다. 비율은 분자·분모가 k 기준을 통과한 경우에도 `0-<10%`, `10-<25%`, `25-<50%`, `50-<75%`, `75-<90%`, `90-100%` 밴드만 기록하며, 작은 분자·분모는 `<10/suppressed`로 표시한다. 범주 분포는 작은 셀을 complementary suppression으로 합친 뒤 literal 값을 순번 범주 라벨로 대체한다. 날짜는 월 literal 대신 순번 기간 라벨, decade 범위만 남긴다. 파일 크기와 길이도 넓은 구간으로 표시한다.

생성 artifact에는 원본 행, 원본 ID/식별자 값, 정확 좌표, 자유 텍스트·캡션·이미지 내용, 원본 경로·파일명 또는 source checksum을 기록하지 않는다. 프로파일러는 DuckDB 임시 경로도 metadata에 남기지 않는다. exact arithmetic은 해당 실행 메모리 안에서만 사용한다. 이 계약을 반영하기 위해 기존 결과를 재작성하거나 삭제하지 않았으며, 수도권 기존 결과는 별도 승인 없이 재계산하지 않는다.

## 수도권 pilot 결과

이 절은 PR #14의 역사적 수도권 pilot 결과다. 기존 관측·상세 결과를 그대로 보존하며, 사진 archive metadata 및 capital 사진-ID 진단은 후속 권역의 파일 선택이나 분석 요건이 아니다.

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

  `AIHUB_RAW_ROOT`와 `AIHUB_CAPITAL_INPUT`은 실행 전에 로컬 shell에서 설정하며, 입력은 지정한 raw root 안이어야 한다. 전용 `codebook_validation.csv`는 코호트·결측·mismatch의 `0`, `<10`, `10+` 구간 및 상태만 기록한다. 해석 결과는 별도 `codebook_interpretation.csv`에 역할·필드·cause class와 구간 bucket만 기록한다. 두 focused artifact에는 원본 경로·파일명·fingerprint·관측 코드 문자열·정확한 count가 없다. 현재 generic profile serializer도 `codebook_check.csv` count를 `0`, `<10`, `10+` bucket으로 기록한다. serializer 변경 전 생성된 legacy generic profile에는 k 이상 exact count나 fingerprint가 남아 있을 수 있으므로 ignored 로컬 결과로만 보존하며, 새 serializer 정책을 과거 산출물에 소급 적용하지 않는다.
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

- **[역사적 추론] 추천·TourAPI 활용 후보:** 과거 수도권 문서 검토에서는 `IMG_CAPTION`, `TOKEN`, `PHOTO_FILE_ID`, 방문지명·랜드마크의 잠재 활용을 논의했으나 feature 추출이나 외부 조회는 수행하지 않았다. 이 논의는 현재 후속 범위가 아니다.
- **[범위 제한] JSON 효용·한계:** 후속 권역 SbL은 JSON schema/structure, 안전한 필드 coverage, 명시된 linkage 후보만 집계한다. 캡션·토큰·장소명·랜드마크·라이선스 값이나 사진 내용은 후속 분석·feature 생성·외부 조회에 사용하지 않는다.
- **[로컬 집계 관측] 개인정보 보호 검토:** 첫 read-only 리뷰는 여러 산출물에 k 미만 코호트의 정확한 count/rate가 남아 있음을 발견했다. 기존 집계 profile만 사용해 당시 억제 로직을 보완·재생성했으며, 이후에는 별도 focused validation만 수행했다. 현재 serializer는 count를 `0`, `<10`, `10+` bucket으로, rate를 coarse band로 내보내고 `codebook_check.csv`도 같은 count 정책을 적용한다. serializer 변경 전 생성된 legacy inventory와 run metadata에는 exact 크기, 입력 식별 또는 checksum 같은 재현 metadata가 있을 수 있어 기존 결과는 ignored 로컬에 보존하고 공유하지 않는다. 새 focused-validation artifact도 구간 bucket을 사용한다. 이 휴리스틱은 의미 기반 재식별 위험을 보증하지 않는다.
- **[로컬 집계 관측·역사적 범위] 실행 범위:** 이 문장은 수도권 pilot 당시의 상태 기록이다. 후속 네 권역 프로파일·C·비교 완료 상태는 본 문서의 후속 결과 절을 참조한다.

## Issue #12 C 후속 집계 (수도권만 측정)

- **[로컬 집계 관측] 범위와 공개 정책:** 기존 capital TL/VL CSV 입력만 `scripts/eda/analyze_recommendation_fit.py`로 읽었다. 이 절의 C 지표는 수도권 TL, VL, 두 분할의 합산 scope와 TL/VL 비교까지다. count는 `0`, `<10`, `10+`만 기록하고 rate는 `0-<10%`, `10-<25%`, `25-<50%`, `50-<75%`, `75-<90%`, `90-100%` 등 넓은 범주로 표시한다. 작은 분자·분모에는 k=10 억제와 분포 셀 complementary suppression을 적용했다. 정확한 cardinality와 rate는 문서에 싣지 않는다. 로컬 ignored 결과는 `results/eda/travel-log-2023/readiness-capital-reviewfix/`에 있다.
- **[로컬 집계 관측] 지표 coverage:** TL·VL·합산 scope 모두 방문 행, 고유 방문지 후보, 고유 POI 후보 및 방문/여행·여행자·POI 빈도 분포를 산출했다. `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`은 세 scope 모두 코드 `1`–`5`와 결측 범주를 집계할 수 있었다. 관측된 공개 count bucket은 `10+`이며 각 분포에 complementary suppression 셀이 존재하면 `<suppressed>`로 합쳤다. 여행자-여행 연결 후보의 모호 매핑 진단은 `0` bucket이었다. 요청된 unique travelers/trips 전체 cardinality는 기존 수도권 관측을 재사용하기 위해 다시 계산하거나 새 결과로 쓰지 않았다.
- **[로컬 집계 관측·미확인] 방문지/POI 후보 관계:** 로컬 방문 입력에서 `POI_ID` header가 관측되어 `--confirm-poi-candidate` gate로 미확정 컬럼 후보 분석을 확인했다. 이 gate는 HWP의 table-specific 정의를 확인했다는 주장이 아니다. 검토한 HWP는 `TN_POI_MASTER.POI_ID`를 설명하지만, `TN_VISIT_AREA_INFO.POI_ID`의 table-specific 의미를 확인해 주지 않는다. 따라서 POI ID와 `(TRAVEL_ID, VISIT_AREA_ID)`는 관측 후보이며 canonical item이나 PK/FK가 아니다. 두 컬럼 후보가 모두 있는 방문 행은 TL·VL·합산 scope에서 `50-<75%` rate band, POI 후보만 결측이고 방문지 후보는 있는 행은 `25-<50%` band였다. 공개된 두 관계 셀의 count bucket은 `10+`였다.
- **[로컬 집계 관측] 사용 이력 및 cold-start 후보:** `trips_per_traveler`에서는 `1` 구간이 공개됐고, `visits_per_trip`, `visits_per_traveler`, `visitors_per_poi`, `poi_visit_frequency`에는 하나 이상의 공개 또는 억제된 빈도 구간이 있었다. 단일 방문 POI 후보 비율은 `75-<90%` band로 기록됐다. TL/VL POI 후보 overlap rate는 `25-<50%`, VL cold-start POI share는 `50-<75%`였다. 인기도 long-tail은 구간 빈도만 요약했으며 개별 POI나 exact frequency를 남기지 않았다.
- **[방법·한계]** 방문지 후보는 distinct `(region, TRAVEL_ID, VISIT_AREA_ID)`, POI 후보는 region-scoped non-null `POI_ID` 컬럼 값으로 계산했다. ID는 빈 값 판정 외에는 원문자열을 보존하며 trim/casefold 정규화를 하지 않는다. 여행자별 집계는 관측된 `TRAVEL_ID`→`TRAVELER_ID` 쌍이 하나로 확인되는 경우만 사용했다. POI overlap은 TL·VL의 region-scoped `POI_ID` 후보 비교다. canonical item 정책이 없으므로 matrix sparsity는 계산하지 않았고 추천 모델, interaction 정의, 결측 처리, canonical POI 또는 서비스 구조를 결정하지 않았다.
- **[후속 평가 문구]** 이후 추천 실험은 `docs/PRD.md`의 단계적 baseline 접근에 맞춰 popularity baseline을 비교 기준에 포함할 수 있도록 설계한다. 이 Issue의 EDA는 baseline을 구현·평가하거나 추천 알고리즘을 선택하지 않는다.
- **[범위 상태]** 이 절의 기록은 capital-only 실행 당시의 snapshot이다. 이후 four-region profile/C/comparison 및 SbL coverage/linkage는 아래 후속 절에 기록했다. 기존 수도권의 일부 cardinality는 재계산하지 않았고 다른 권역으로 일반화하지 않는다.

## 추천 시스템 관점의 제한된 관찰

- **[기존 로컬 집계 기록]** 기존 수도권 점검에서는 TL/VL 합산의 고유 여행·여행자 수가 모두 `10+` bucket으로 기록됐으며 서로 같았다는 기존 관측이 있다. 현재 후속 작업은 해당 cardinality를 재계산하거나 exact 값으로 다시 기록하지 않았다.
- **[해석 제한]** 기존 수도권 TL/VL 관측에서 고유 여행 수와 고유 여행자 수가 같았다는 사실만으로 장기 반복 사용자 행동을 전제하는 전통적 user-history 기반 CF의 적합성을 판단하기 어렵다. 다른 권역 및 미확인 데이터 범위까지 일반화하지 않는다. 이는 후속 EDA 질문이며 알고리즘 선택 결론이 아니다.

## West 후속 B/C 결과 (부분 범위)

- **[범위·보관]** 2026-10-08 West만 처리했다. `Other`, `TL_csv`, `TL_gps_data`, `VL_csv`, `VL_gps_data`의 CSV를 승인된 추출기로 raw-root의 West dataset child `eda-csv-extracted/`에 추출했다. `profile`, `profile-tl`, `profile-vl`, `recommendation-fit` 결과는 ignored `results/eda/travel-log-2023/west/` 아래에 생성했다. SbL은 ZIP에서 JSON 구조만 직접 검사해 `sbl-structure`에 기록했다. 사진 archive는 열거나 추출·분석하지 않았고, 사진/바이너리 metadata 요구도 포함하지 않았다. 기존 수도권 산출물은 재실행·변경하지 않았다.
- **[프로필·coverage]** 전체 CSV profile과 TL-only/VL-only profile은 모두 종료 코드 0이었다. 각 산출물에서 테이블 수와 행 수는 `10+` bucket에 있었고, 프로파일된 테이블 상태는 모두 `ok` bucket이었다. TL과 VL의 대응 테이블 schema는 공개된 컬럼명·자료형 기준으로 모두 일치했다. 공식 문서의 구축 규모와 실제 profile 행 수는 모두 공개 `10+` 범위로만 비교할 수 있어 차이의 크기나 비율은 산출하지 않았다. 전체 입력 profile은 composite 후보 상한을 2로 설정했다.
- **[품질·날짜]** 전체 CSV profile에서는 전체 행 중복이 관측된 테이블 그룹, 모든 값이 결측인 컬럼, 상수 컬럼이 각각 `10+` bucket으로 관측됐다. 날짜 분포는 월 단위로 요약하고 작은 셀은 억제했다. 좌표·식별자·자유 텍스트 값은 공개하지 않았다. 이 결과는 원자료를 수정하거나 품질 원인으로 확정하지 않는다.
- **[이전 로컬 HWP Markdown 기반 비교]** 이전 작업에서 수도권·동부권·서부권·제주/도서권 데이터 설명서의 명시 범위 도메인을 비교했고, West profile의 공개 category aggregate에서 HWP 범위 밖 후보가 `10+` category / `10+` field bucket으로 관측됐다. 일부 범주는 k 억제로 합쳐졌으므로 전체 도메인 검증은 아니다. 공식 문서 출처는 [AI Hub 국내 여행로그 데이터(수도권, 2023) 상세페이지 및 연결된 권역별 데이터 설명서](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71776)다. 이 과거 category 결과는 별도 관측으로 보존한다. 최초 profile 실행은 `--codebook`을 주지 않아 `codebook_check.csv`가 생성되지 않았지만, 이후 아래의 focused codebook-only 갱신으로 West/East/Jeju의 기존 profile에 허용값 검사 결과를 채웠다. 값 정규화나 원인 추정은 하지 않았다.
- **[C: split·반복 이력]** TL, VL, combined 각각에서 unique travelers, trips, visits, visit areas, POI 후보의 count bucket은 모두 `10+`였다. `ambiguous_trip_traveler_mappings`는 각 scope에서 `0` bucket이었다. 공개된 trips-per-traveler 분포에는 `1` 구간이 있었고, visits-per-trip 및 visits-per-traveler는 여러 억제·빈도 구간으로만 남겼다. visitors-per-POI와 POI visit frequency에는 `1`, `2–4`, `5–9`, `10–49` 및 일부 scope의 `50+` 구간이 나타났다. 전 count는 bucket, rate는 coarse band이며 분포에는 complementary suppression을 유지했다.
- **[C: POI 후보·feedback]** `POI_ID`와 방문지 식별 열은 후보 관계로만 계산했다. 둘 다 있는 행의 비율 band는 TL `75–<90%`, VL `50–<75%`, combined `75–<90%`; POI 후보가 비고 방문지 후보가 있는 행은 각각 `10–<25%`, `25–<50%`, `10–<25%`였다. TL/VL POI 후보 overlap은 `50–<75%`, VL cold-start POI share는 `25–<50%`였다. 단일 방문 POI 후보 비율은 TL/combined `50–<75%`, VL `75–<90%`였다. 세 feedback 필드의 코드 `1`–`5` 및 결측 범주는 각 scope에서 공개 count bucket `10+`였다. HWP 및 CLI gate는 `TN_VISIT_AREA_INFO.POI_ID`의 table-specific 의미나 PK/FK를 확정하지 않으므로 canonical POI·관계로 해석하지 않는다.
- **[SbL JSON 구조·field coverage]** generic inspector의 structural aggregate와 별도 allowlist one-off의 field coverage/linkage를 모두 생성했다. 상세 bucket/band는 Four-region SbL 절을 참조한다.
- **[지리 범위·통합 비교]** 좌표는 공개하지 않았다. 승인된 권역 경계 정의를 확인하지 못해 out-of-region visits는 계산하지 않았다. `compare_regions.py` 4권역 comparison은 완료됐지만, 합산된 row counts는 region 간 비교 자체를 넘어서는 해석에 사용하지 않는다.
- **[모델링 비결정]** canonical POI, interaction 정의, 결측 처리, 모델/평가 split 및 서비스 구조를 결정하지 않았다. 후속 추천 실험에는 popularity baseline을 비교 기준으로 포함할 수 있다는 기존 평가 문구만 유지한다.

## East·Jeju 후속 작업 (완료)

- **[입력 범위]** East와 Jeju/도서권은 승인된 `Other`, `TL_csv`, `TL_gps_data`, `VL_csv`, `VL_gps_data` 역할의 추출 CSV만 사용한다. 사진 archive는 다운로드·열람·추출·분석하지 않는다. 원본 ZIP은 보존한다.
- **[SbL JSON 구조]** `inspect_travel_log_archives.py`를 각 권역의 승인된 SbL ZIP에 직접 실행했고 두 명령 모두 종료 코드 0이었다. 두 권역 모두 JSON root type `object`가 `10+` bucket, top-level key count band `1–4`의 aggregate가 `10+`, top-level child type `object`가 `10+`로 기록됐다. 원본 key·member 이름·경로·값은 산출물에 없다.
- **[SbL field coverage/linkage]** generic inspector와 별도의 안전한 one-off 집계로 7개 allowlist field의 타입·key presence·blank/nonblank 상태 및 같은 권역 `TN_TOUR_PHOTO` candidate linkage를 측정했다. 네 권역 결과는 아래 four-region SbL 절에 bucket/band로 기록했다.
- **[C: East·Jeju]** 두 권역의 입력은 각각 `readiness-east-followup/` 및 `readiness-jeju-followup/`에서 안전하게 집계했다. TL, VL, combined scope에서 고유 traveler/trip/visit/visit-area/POI 후보 count가 `10+`였고 모호한 trip-traveler 매핑은 `0`이었다. 세 feedback 필드의 공개 분포 셀은 `10+` bucket이며 결측 셀도 `10+`였다. visits-per-trip/traveler는 빈도 구간과 complementary suppression으로 요약했다. visitors-per-POI와 POI visit frequency는 East에서 TL/combined에 `50+` 빈도 구간, VL에는 `10–49`까지 관측됐다. Jeju는 세 scope에 `50+` 및 억제 구간이 관측됐다. 개별 항목·정확 횟수는 기록하지 않았다.
- **[C: 후보 관계]** East와 Jeju 모두 POI 후보와 visit-area 후보가 함께 있는 행 비율은 `75–<90%`, POI 후보 결측·visit-area 후보 존재 비율은 `10–<25%`였다. TL/VL POI 후보 overlap은 `50–<75%`, VL cold-start POI share는 `25–<50%`였고 관련 공개 count는 `10+`였다. 이 지표는 관측 컬럼 후보 관계이며 canonical POI나 PK/FK 의미를 확정하지 않는다.
- **[프로파일 상태]** East 로그에 profiler `완료:` 표식이 있고 오류 표식은 없으며 필수 aggregate artifact가 모두 존재한다. manifest의 시작·완료 시각 및 `east` label을 확인했고 재실행하지 않았다. Jeju는 사용자가 확인한 `JEJU_PROFILE_EXIT=0` marker와 14개 필수 aggregate artifact로 완료를 확인했다. source manifest의 추출 폴더 label은 비교 projection에서만 `jeju-islands`로 매핑했다.
- **[비교 상태]** `compare_regions.py`의 4개 권역 실행은 exit 0으로 완료됐다. 입력 projection은 run metadata, tables, columns, date-month aggregates만 포함하고 photo summary 및 파일 inventory를 제외했다. 비교 결과 region label은 `capital`, `west`, `east`, `jeju-islands`다. 각 권역에서 공개 테이블/행 수는 `10+` bucket이며 공개 schema type conflict는 `0` bucket이다.

## Four-region SbL allowlist coverage and candidate linkage

- **[로컬 집계 관측]** 네 권역의 승인된 `SbL` JSON에서 `images.PHOTO_FILE_ID`, `images.PHOTO_FILE_NM`, `images.VISIT_AREA_NM`, `images.LANDMARK`, `caption.IMG_CAPTION`, `caption.TOKEN`, `caption.TIME_STAMP`만 대상으로 존재·타입·결측 상태를 집계했다. 모든 권역·필드의 JSON 관측 수는 `10+`, key presence와 nonblank coverage는 각각 `90–100%` band였다. 모든 지정 필드는 string 타입 `10+`였고 `caption.TOKEN`은 number 타입 `10+`였다. `images.VISIT_AREA_NM` 및 `images.LANDMARK` 각각에서 blank와 nonblank 값이 모두 `10+` bucket이었다. 나머지 필드는 공개 분포상 non-null `10+`였다. 값 자체는 공개하지 않았다.
- **[로컬 집계 관측·후보 연결]** JSON의 `PHOTO_FILE_ID`를 같은 권역 CSV `TN_TOUR_PHOTO` metadata ID와 exact-string으로 메모리 내 비교했다. 네 권역 모두 JSON/CSV 고유 ID, matched 및 양방향 unmatched count는 `10+`; JSON→CSV candidate match rate는 `75–<90%`, CSV→JSON rate는 `10–<25%`였다. non-string JSON ID count는 `0` bucket이었다. 이는 문자열 일치 기반 후보 연결이며 PK/FK 또는 공식 관계를 뜻하지 않는다. ID는 산출물에 기록하지 않았다.
- **[방법·보호]** JSON member 경로·파일명, ID, caption/token/text, CSV 원본 행 및 이미지 payload는 결과로 내보내지 않았다. count는 `0`, `<10`, `10+` bucket, rate는 coarse band를 사용하고 분포에 complementary suppression을 적용했다. ignored artifact는 `results/eda/travel-log-2023/sbl-fields-linkage-four-region/` 아래 `field_coverage.csv`, `photo_file_id_candidate_linkage.csv`, `run_metadata.json`이다.
- **[정책 범위]** 사진 archive 다운로드·열거·검사 또는 이미지 binary metadata/내용 분석은 하지 않았다. 이전 수도권 pilot의 사진 파일 metadata 결과는 역사 기록이며 이번 네 권역 정책의 요구나 산출물로 간주하지 않는다.

## Four-region recommendation-fit aggregate

- **[로컬 집계 관측]** 통합 C scan은 exit 0으로 끝났고 ignored 결과는 `results/eda/travel-log-2023/readiness-four-region-integrated/`에 있다. 권역별 TL/VL/combined와 통합 TL/VL/combined scope에서 측정 가능한 unique traveler/trip/visit/visit-area/POI 후보 count는 `10+` bucket, 모호한 traveler-trip mapping은 `0` bucket이었다. 기존 수도권 combined traveler/trip 관측은 재계산하지 않았고 결과에서 unavailable로 유지했다.
- **[로컬 집계 관측]** 통합 TL/VL POI candidate overlap은 `50–<75%`, VL cold-start POI share는 `25–<50%` band였다. 각 권역 combined overlap은 `25–<50%`(capital), `50–<75%`(west/east/jeju-islands); cold-start share는 `50–<75%`(capital), `25–<50%`(west/east/jeju-islands)였다. POI_ID와 visit-area 후보가 함께 관측된 비율은 capital `50–<75%`, west/east/jeju-islands 및 integrated `75–<90%`; POI 후보 결측·visit-area 후보 존재는 capital `25–<50%`, 나머지 region/integrated scope `10–<25%`였다. 공개 count는 `10+` bucket이며 분포에는 complementary suppression이 적용됐다.
- **[범위 제한]** 표준화된 canonical item 정책이 없으므로 matrix sparsity를 확정 지표로 계산하지 않았다. 추천 모델, interaction 정의, 결측 처리, canonical POI 또는 서비스 구조를 결정하지 않았다. 이후 평가에는 popularity baseline을 비교 기준으로 포함할 수 있다는 문구만 유지한다.

## Four-region code-table candidate coverage

- **[로컬 집계 관측]** 기존 validator의 명시 target-field mapping 38개를 각 권역 TL/VL CSV header에서 확인했고, 네 권역·두 split에서 해당 컬럼만 한 번씩 스트리밍했다. 산출물은 304 field-split aggregate rows이며 ignored `results/eda/travel-log-2023/code-table-coverage-summary/code_table_membership.csv`에 있다. `valid`, `unknown`, `blank` row counts와 distinct-code counts만 k=10 bucket으로 기록하고 작은 분할에는 complementary suppression을 적용했다. raw code values/rates는 artifact에 기록하지 않았다.
- **[로컬 집계 관측·주의]** same-region `TC_CODEA.cd_a` 및 `TC_CODEB.cd_a/cd_b`의 합집합과 정확 문자열 비교했을 때 `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK`, `EXPND_SE`의 unknown-cell count는 네 권역 TL/VL 각각 `10+` bucket이었다. blank-cell count도 `ADMISSION_SE`, `DGSTFN`, `EXPND_SE`, `HOUSE_INCOME`, `JOB_ETC`, `MVMN_CD_1`, `MVMN_CD_2`, `RCMDTN_INTENTION`, `REVISIT_INTENTION`, `TRAVEL_MOTIVE_3`, `VISIT_CHC_REASON_CD`에서 모든 권역·split별 `10+` bucket이었다. 그 밖의 값은 field-level artifact에서 bucket/suppression 상태로 확인할 수 있다. 여기서 unknown은 값이 넓은 코드표 union에 없다는 뜻일 뿐, 해당 field의 잘못된 코드라는 뜻이 아니다. field별 code group을 구분하지 않았으며 구분자 포함 복합 표현도 분해하지 않아 unknown에 포함될 수 있다.
- **[문서 매핑]** PR #15에서 병합된 수도권·서부권·동부권·제주/도서권 설명서는 아래 38개 대상 필드의 허용 범위와 코드 그룹을 동일하게 명시한다. 범위는 문서 정의이며 관측값의 적합성을 뜻하지 않는다.

| 필드 | 문서상 허용 범위 | 코드 그룹 |
| --- | --- | --- |
| `ACTIVITY_TYPE_CD` | `1–7, 99` | `ACT` |
| `ADMISSION_SE` | `1–2` | `AMS` |
| `COMPANION_AGE_GRP` | `1–8` | `AGE` |
| `COMPANION_GENDER` | `1–2` | `GEN` |
| `COMPANION_SITUATION` | `1–3` | `CST` |
| `DGSTFN` | `1–5` | `DGS` |
| `EDU_FNSH_SE` | `1–5` | `EFS` |
| `EDU_NM` | `1–8` | `EDU` |
| `EXPND_SE` | `1–5` | `EXP` |
| `HOUSE_INCOME`, `INCOME` | `1–12` | `INC` |
| `JOB_ETC` | `1–3` | `JOE` |
| `JOB_NM` | `1–13` | `JOB` |
| `LODGING_TYPE_CD` | `1–12` | `HTY` |
| `MARR_STTS` | `1–5` | `MAR` |
| `MVMN_CD_1`, `MVMN_CD_2`, `MVMN_SE` | `1–16, 50` | `MOV` |
| `PAYMENT_MTHD_SE` | `1–5` | `PAY` |
| `RCMDTN_INTENTION` | `1–5` | `REC` |
| `REL_CD` | `1–11` | `TCR` |
| `REVISIT_INTENTION` | `1–5` | `REP` |
| `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK` | `1–13, 21–28` | `MIS` |
| `TRAVEL_MOTIVE_1`, `TRAVEL_MOTIVE_2`, `TRAVEL_MOTIVE_3` | `1–10` | `TMT` |
| `TRAVEL_STYL_1`–`TRAVEL_STYL_8` | `1–7` | `TSY` |
| `TRAVEL_TERM` | `1–4` | `TTM` |
| `VISIT_AREA_TYPE_CD` | `1–13, 21–24` | `VIS` |
| `VISIT_CHC_REASON_CD` | `1–11` | `REN` |

- **[코드표 도메인 대조]** 네 권역의 기존 TL 추출 경로에서 `TC_CODEA`와 `TC_CODEB`를 직접 읽어 문서의 10+ 코드 그룹 키와 그룹별 허용 코드 집합을 대조했다. 네 권역 모두 문서상 허용 코드가 해당 그룹의 `TC_CODEB.cd_b` 고유값에 포함됐고, 누락·추가 도메인 값과 그룹 키 누락은 각각 `0` 구간이었다. 원본 코드값은 출력하지 않았다.
- **[West/East/Jeju 관측값 검사]** 기존 TL/VL 역할 디렉터리에서 문서 매핑 대상 열을 순차 읽어 각 관측값 전체를 문서 허용 범위와 대조했다. 이 가운데 `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK`, `EXPND_SE`만 해당 권역 `TC_CODEB`의 `MIS` 또는 `EXP` 그룹 고유 코드와 추가로 정확 대조했다. 다른 직접 대응 필드는 권역별 통과 필드 수가 `10+` 구간이고 비결측 관측값이 모두 문서 범위에 포함됐다. 세 추가 대조 필드는 세 권역 TL/VL 각각 직접 일치 실패 후보가 `10+` 구간이다. 네 권역 Markdown 설명서는 이 필드들의 구분자, 복합 코드 분해 또는 표기 정규화를 정의하지 않는다. 따라서 구분 토큰을 임의로 나누거나 정규화하지 않았고, 이 후보가 유효한 복합 표현인지 도메인 밖 값인지 판정하지 못해 미검증으로 유지한다. `JOB_ETC`는 세 권역 모두 비결측 관측 `0`, 결측 `10+` 구간이라 실제 값 검증을 할 수 없었다. 안전 집계는 Git 추적 제외 경로 `results/eda/travel-log-2023/code-domain-three-fields-codebook-retry-20261009/observations.csv`에 저장했으며 원본 행·값·파일명은 포함하지 않는다.
- **[수도권 및 기존 결과 한계]** 이번 확인에서 수도권 TL/VL 역할로 지정 가능한 추출 파일은 없었다. 새 원본 경로 탐색이나 재처리는 하지 않고 [수도권 스키마 참조](aihub-71776-capital-schema.md)에 기록된 일부 필드의 기존 제한 검증만 유지한다. 최초 West/East/Jeju 프로파일 실행에는 `--codebook`이 제공되지 않아 당시 `run_metadata.json`에 `codebook_provided=false`, `codebook_source_recorded=false`가 기록됐고 `profile.json`의 `codebook_check`는 비어 있었다. East와 Jeju의 당시 `codebook_check.csv`는 헤더 없는 빈 파일이었으며 West의 해당 출력도 비어 있었다. 이는 no-codebook 분기의 결과이지 CSV 입력 실패나 컬럼 불일치가 아니다. `profile_travel_log.py --codebook`은 `TC_CODEB.csv`가 아니라 공식 문서에서 구성한 허용값 JSON을 입력으로 받으므로, 최초 프로파일 실행은 원본 `TC_CODEB` 탐색을 하지 않았다.

- **[focused codebook-only 갱신]** 전체 profile을 재실행하지 않고 `profile_travel_log.py --codebook-only`로 고정된 다섯 profile(West 통합/TL/VL, East 통합, Jeju/도서권 통합)의 문서 매핑 대상 열만 다시 검사했다. 이 목록 밖의 과거 집계 결과는 갱신 대상이 아니다. 네 권역 Markdown 설명서의 38개 필드 매핑에 더해 각 권역 `TC_CODEA`의 그룹 키와 `TC_CODEB`의 그룹별 코드 목록을 사용했다. builder는 각 직접 대응 필드의 허용값을 설명서 범위와 해당 지역 코드 그룹의 교집합으로 구성하며, 설명서 범위와 `TC_CODEB` 그룹 도메인이 일치하고 `TC_CODEA` 그룹 키가 있을 때만 그룹 검증 상태를 `valid`로 둔다. 기존 profile의 다른 집계는 보존하되, 공개 전에 모든 profile section에 k=10 serializer를 다시 적용하고 각 대응 CSV도 같은 집계로 재생성해 JSON/CSV 일치를 유지했다. 갱신 후 다섯 `run_metadata.json` 모두 `codebook_provided=true`, `codebook_source_recorded=true`이고, 코드북 검사 행은 각 결과에서 `10+` bucket이다. 허용값 수와 관측·불일치 행 수는 `0`, `<10`, `10+` bucket으로만 저장했다. 문서상 코드 표현 규칙이 확인되지 않은 `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK`, `EXPND_SE`는 allowlist에서 제외하고 `unresolved_fields`로 기록해 `unresolved_candidate`로 남겼으며 토큰 분리·정규화하지 않았다. 나머지 직접 대응 필드는 검사 가능한 비결측 값이 지역별 허용목록에 모두 포함되고 그룹 검증이 통과한 경우 `valid`로 기록했다. 별도 `validate_travel_log_code_domains.py`의 그룹 도메인 결과와 profile의 관측 행 검사는 별개다. `TC_SGG`는 기존 38개 매핑에 속하지 않아 제외했다. 수도권은 새 profile 입력이 없어 이번 focused 갱신 대상이 아니며 기존 제한 검증만 유지했다.

  재현 시 `PROFILE_INPUT`, `PROFILE_TL_CSV`, `PROFILE_OUTPUT`, `REGION`, `AIHUB_RAW_ROOT`를 이미 승인·추출한 해당 권역 경로로 로컬 shell에서 지정한다. `PROFILE_TL_CSV`는 같은 권역의 TL role directory이며, VL 입력 검사에서도 TC_CODEA/TC_CODEB reference는 이 TL role에서 읽는다. allowlist 생성기는 `validate_travel_log_code_domains.py`의 네 권역 문서 매핑을 재사용한다. 원래 profile의 `tables` alias 목록과 안전한 per-column 요약에서 문서 필드 서명을 대조해 기존 alias를 확인한 뒤, TL/VL role 아래의 해당 TN CSV만 상대 경로순으로 대응시킨다. 따라서 Other/JSON 등 선행 파일이 차지한 alias 번호 간격을 유지하며, 재탐색으로 TS_photo/VS_photo를 열거하지 않는다. photo 디렉터리는 하위 탐색 전에 제외한다. 대상 alias와 매핑 열을 확인할 수 없는 경우 생성·갱신을 중단한다. 각 필드에 연결된 문서 범위의 양 끝을 포함해 정수 값을 확장한 뒤 같은 권역 `TC_CODEA`에서 그룹 키를 확인하고 `TC_CODEB`에서 해당 그룹의 코드 문자열을 읽는다. 지역 허용목록은 문서 범위와 그룹 코드 집합의 교집합으로 만든다. 두 집합이 같고 `TC_CODEA`에 그룹 키가 있을 때만 `group_validation`을 `valid`로 기록하며, 그 외에는 관측값이 교집합에 있더라도 profile 상태를 `unresolved_codebook_domain`으로 남긴다. 같은 권역 그룹 도메인은 `validate_travel_log_code_domains.py`의 별도 도메인 결과에서도 검증했으며 이 결과와 필드별 CSV 관측 행 검사는 분리한다. `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK`, `EXPND_SE`는 허용값 목록에서 제외하고 `unresolved_fields`에 기록하므로 관측값이 목록에 맞아도 결과는 `unresolved_candidate`다. 해당 세 필드의 `MIS`/`EXP` 그룹 membership은 이 profile 검사의 대상이 아니다. 직접 대응값 비교는 정확 문자열 비교이며 공백 제거, 대소문자 변경, 구분자 분리나 기타 정규화는 하지 않는다. JSON은 실제 관측값을 포함하지 않고 무시 규칙이 적용되는 결과 폴더에만 둔다.

  ```bash
  .venv/bin/python scripts/eda/build_travel_log_codebook.py \
    --input-root "$PROFILE_INPUT" --region "$REGION" \
    --codebook-root "$PROFILE_TL_CSV" \
    --profile-json "$PROFILE_OUTPUT/profile.json" \
    --output "$PROFILE_OUTPUT/codebook-allowlist.json"

  .venv/bin/python - "$PROFILE_OUTPUT/codebook-allowlist.json" <<'PY'
  import json, sys
  spec = json.load(open(sys.argv[1], encoding="utf-8"))
  assert isinstance(spec.get("source"), str)
  assert isinstance(spec.get("tables"), dict)
  assert isinstance(spec.get("unresolved_fields"), dict)
  assert isinstance(spec.get("column_groups"), dict)
  assert isinstance(spec.get("group_validation"), dict)
  assert set(spec["group_validation"].values()) <= {"valid", "unresolved"}
  assert all(isinstance(values, list) and all(isinstance(v, str) for v in values)
             for columns in spec["tables"].values() for values in columns.values())
  print("allowlist JSON structure valid")
  PY

  .venv/bin/python scripts/eda/profile_travel_log.py \
    --raw-root "$AIHUB_RAW_ROOT" --input "$PROFILE_INPUT" \
    --output "$PROFILE_OUTPUT" --codebook-only \
    --codebook "$PROFILE_OUTPUT/codebook-allowlist.json" \
    --confirm-approved --confirm-terms
  ```

  `--codebook` JSON 구조는 `source` 문자열, alias별 열과 지역 허용 문자열 목록을 담는 `tables`, unresolved 열을 담는 `unresolved_fields`, 필드→그룹 참조인 `column_groups`, 그룹 도메인 상태인 `group_validation`이다. JSON 확인 명령은 구조만 검사하고 허용 코드 문자열이나 입력 경로를 출력하지 않는다. `--codebook-only`는 지정 CSV 열만 읽어 코드북 검사 결과를 갱신하고, 보존하는 모든 기존 profile 섹션에 k=10 공개 serializer를 다시 적용한다. `profile.json`과 각 섹션 CSV를 같은 안전 집계로 함께 재생성하며 `run_metadata.json`의 실행 플래그도 갱신한다. 지원하지 않는 profile 섹션이나 k=10이 아닌 기존 결과는 안전하게 갱신할 수 없어 중단한다.

### 재현 가능한 관측값 검사기

`scripts/eda/validate_travel_log_code_domains.py`는 네 권역 Markdown 설명서의 동일한 38개 필드 매핑을 사용해 지정한 West/East/Jeju TL/VL CSV의 매핑 열만 순차 검사한다. 문서 허용 범위 검사는 모든 매핑 필드에 수행하고, 같은 권역 `TC_CODEB`의 `MIS`/`EXP` 그룹과 관측값을 정확 비교하는 검사는 `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK`, `EXPND_SE`에만 수행한다. 코드표의 그룹별 도메인 일치 결과와 CSV 관측값 검사는 별도 산출물로 기록한다. 구분자 분리나 값 정규화는 하지 않으며, 불일치는 잘못된 값으로 단정하지 않고 `unresolved_candidate`로 남긴다.

```sh
WEST=/path/to/2023-travel-log-west/eda-csv-extracted
EAST=/path/to/2023-travel-log-east/eda-csv-extracted
JEJU=/path/to/2023-travel-log-jeju-islands/eda-csv-extracted
RUN=code-domain-cli-YYYYMMDD-HHMM
.venv/bin/python scripts/eda/validate_travel_log_code_domains.py \
  --input "west:TL=$WEST/TL_csv" --input "west:VL=$WEST/VL_csv" \
  --input "east:TL=$EAST/TL_csv" --input "east:VL=$EAST/VL_csv" \
  --input "jeju-islands:TL=$JEJU/TL_csv" --input "jeju-islands:VL=$JEJU/VL_csv" \
  --codebook "west=$WEST/TL_csv" --codebook "east=$EAST/TL_csv" \
  --codebook "jeju-islands=$JEJU/TL_csv" \
  --output "results/eda/travel-log-2023/$RUN" \
  --confirm-approved --confirm-terms
```

`RUN`은 기존 출력과 겹치지 않는 새 이름으로 바꾼다. 출력은 ignored 경로의 `codebook_domains.csv` 및 `field_observations.csv`이며, 원본 값·코드값·경로·정확 건수는 저장하지 않는다. 건수는 `0`, `<10`, `10+` 구간, 상태는 `valid` 또는 `unresolved_*`로 기록한다. 기존 제한 검사에서 세 MIS/EXP 필드는 각 권역·분할의 직접 일치 실패 후보가 `10+` 구간이었다. 이 세 값의 복합 표현 여부는 설명서에 분해 규칙이 없어 미확인이다. 이 세 필드를 제외한 직접 대응 필드는 범위 밖 후보가 `0` 구간이고 통과 필드 수가 `10+` 구간이었으며, `JOB_ETC`는 비결측 관측이 `0` 구간이었다. 위 재현 명령은 전체 EDA가 아니라 해당 열만 재검사한다.

권역 파일 표식은 공식 파일 구성 설명의 수도권 E, 동부권 F, 서부권 G, 제주·도서권 H 정의를 따른다. 실제 West/East/Jeju `TC_CODEB` 파일명에는 권역 표식이 없었으며, 검사기는 코드표를 해당 권역 `2023-travel-log-<region>/.../TL_csv`에서만 찾는다. `TC_CODEB` 파일명에 E/F/G/H 표식이 명시된 경우에는 요청 권역의 표식과 일치해야 한다. 지역별 TN 테이블은 파일명 끝 표식도 확인한다.

2026-10-09에 출력 경로·코드표 역할·권역 표식 검증을 보강한 검사기를 기존 West/East/Jeju 추출 입력으로 다시 실행해 exit 0을 확인했다. 결과는 ignored `results/eda/travel-log-2023/code-domain-cli-20261009-suffix-guard/`에 생성됐다. 세 MIS/EXP 필드에 대해 이전 `observations.csv`와 비교한 West/East/Jeju TL/VL의 관측·결측·범위 불일치·코드 그룹 불일치 bucket 및 상태가 모두 일치했다. 비교 요약에는 값과 정확 건수를 출력하지 않았다. 새 `codebook_domains.csv`의 그룹 도메인 bucket은 이번 재현 산출물에 별도로 기록했다.

## 한계와 후속 결정 후보

- 이번 WSL 실행 환경에서는 HWP 원본을 직접 변환하지 못했다. 네 권역 설명서의 기존 Markdown 변환본은 PR #15에서 병합됐으며 필드 설명·허용 범위·코드 그룹 표기를 포함한다. 이번 제한 검사는 문서 정의와 코드표 도메인 및 직접 대응 가능한 관측값을 확인했지만, 복합 표기 가능성이 남은 세 필드와 수도권의 신규 관측값 검증은 미완료다. 수도권 기존 일부 필드의 HWP 도메인·코드 그룹 대조 사실은 [수도권 스키마 참조](aihub-71776-capital-schema.md)에 보존하며, 이번 네 권역 결과와 구분한다. 공식 문서 출처: [AI Hub 국내 여행로그 데이터(수도권, 2023)](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71776).
- 행정구역 수준 위치 집계는 공식 구조 확인 후 `--allow-value-column` 지정이 필요하다. 좌표 자체는 집계에 쓰지 않는다.
- 중첩 JSON은 자동으로 펼치지 않는다(펼치는 기준이 데이터 의미에 의존).
- CSV가 UTF-8/UTF-16이 아니면 변환하지 않고 중단 기록만 남긴다. 변환은 행 단위 파생 파일을 만들기 때문에 별도 결정이 필요하다.
- 발견한 품질 문제를 고치지 않고, 결과 검토 후 전처리 결정 후보로 기록한다.
