# 여행 맥락 × POI 신호 타당성 실험

Issue #45는 맥락을 반영한 추천 순위 모델을 만들기 전에 재현 가능한 타당성 점검을 수행하도록 정의합니다. 이 실험은 통계적 연관성과 홀드아웃 예측 신호를 확인하며, 인과 효과를 추정하지 않습니다.

사용 필드의 범위는 [추천 학습 데이터 계약](../training-data-contract.md), [2023 권역별 스키마 색인](../../data/travel-log-2023/README.md), [인기도 기준선](popularity-baseline.md), [CF 타당성 프로토콜](cf-baseline.md)을 따릅니다.

## 현재 실행 상태

2023년 4개 권역 데이터셋과 적용되는 AI Hub 이용 조건의 승인은 [Issue #12](../../data/eda-travel-log-2023.md)에 기록되어 있습니다. Issue #31에서 정한 TL/VL 역할 매핑은 PR #40의 4개 권역 정상 실행에서 사용되었으며, [CF 결과](cf-baseline.md)에는 권역별 및 전체 TL/VL 실행 성공, TL/VL 간 여행 ID 중복 0건, 기존 인기도 기준선과의 결과 일치가 기록되어 있습니다. Issue #45 실험은 조정자가 원래 셸 사전 점검과 승인 근거를 확인한 뒤 `context-poi-20261012-9c0b12` 실행 ID로 완료했습니다. 승인된 4개 권역의 TL/VL 역할 폴더를 확인해 사용했습니다. 헤더, 경로 포함 관계와 심볼릭 링크, 조인 품질, 권역별 TL/VL 중복 검사가 통과했습니다. 권역별 TL 역할 4개와 외부 재현용 VL 역할 4개를 사용했고, 여행 ID 중복은 0건이었습니다. 입력 경로와 capital 파일키 값은 기록하지 않았습니다. 실행 결과는 Git에서 제외되는 로컬 결과 디렉터리에 있으며 커밋하지 않았습니다.

| 분석 | 범위 | 관측 | 억제(k=10) | 지원량 부족 | 희소 기대 셀 | Cramér's V 중앙값 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 맥락/POI 연관 분석 | 통합 (`all-regions`) | 4 | 299 | 116 | 1 | 0.1704 |
| 피드백 연관 분석 | 통합 (`all-regions`) | 20 | 855 | 174 | 1 | 0.0268 |

권역별 연관 분석은 지원량이 부족했습니다. 위 요약은 기술적 집계이며 인과적 해석이 아닙니다. 카이제곱 p-value는 기술적 참고값으로만 취급합니다.

| 분석 | 테이블 수 | 상태 |
| --- | ---: | --- |
| 맥락 × POI × 피드백 결합 분포 | 180 | 모두 k=10 기준 미달로 억제 |

피드백 특징 제거 비교 점수 60개를 계산했습니다.

| 비교 | 비교 수 | context+POI와 기준선의 평균 VL log loss 차이 |
| --- | ---: | --- |
| context+POI 대 popularity-only | 15 | +0.1124 (context+POI가 더 나쁨) |
| context+POI 대 POI-only | 15 | +0.0976 (context+POI가 더 나쁨) |

현재 사용한 제한된 특징 집합에서 충분한 context-aware recommendation signal을 확인하지 못했습니다. 각 피드백 예측에서 context+POI는 popularity-only 및 POI-only보다 개선되지 않았습니다. 다만 이번 실험에는 여행 스타일, 동행자 유형/인원, 여행 기간, 기타 여행자 선호, 더 풍부한 POI master metadata가 포함되지 않았습니다. 따라서 이번 결과는 해당 특징 집합의 사후 피드백 예측 진단에 한정되며, 전체 ranking hypothesis를 기각하는 근거로 볼 수 없습니다.

## Issue #45 gate 결과

| Gate | 실행 결과 | 판단 |
| --- | --- | --- |
| 하나 이상의 핵심 여행 맥락 × POI 특징에서 trivial하지 않은 효과 크기 확인 | 통합 범위에서 일부 연관 분석이 관측되었으나 관측 건수와 k=10 억제가 제한적입니다. | 제한된 관측; 충분한 근거인지 판단 유보 |
| region/popularity 같은 주요 신호를 고려한 뒤에도 일부 관계가 유지 | 권역 및 TL 인기도 구간별 분석은 일부 수행했으나 지속 신호를 뒷받침하는 근거는 충분하지 않습니다. | 판단 유보 |
| 한 권역에만 의존하지 않는 반복 패턴 | 권역별 연관 분석은 지원량이 부족했습니다. | 미충족 |
| context+POI가 popularity-only 또는 POI-only보다 holdout 추가 예측 신호를 보임 | 방문 후 피드백 예측 log loss가 두 기준선보다 나빴습니다. 이 비교는 POI relevance Top-K ranking을 직접 평가하지 않습니다. | 미충족 |
| 누수 또는 사후 이벤트 특징 사용으로 설명되지 않는 결과 | 누수 점검을 통과했습니다. | 충족 |

**Go gate는 충족되지 않았지만, 특징 범위와 개인정보 보호를 고려한 결합 분석의 한계 때문에 전체 가설은 결론을 유보합니다.**

## 가설과 특징 범위

주요 가설은 문서화된 여행 맥락과 방문 영역 속성이 측정 가능한 연관성을 보이며, 각 방문 후 피드백 필드의 홀드아웃 예측에서 popularity-only 또는 단일 특징군 기준선보다 나은 신호를 제공한다는 것입니다. 스크립트는 현재 스키마와 계약에서 조인 경로가 명시된 필드만 사용합니다.

| 역할 | 포함 필드 | 처리 방식 |
| --- | --- | --- |
| 여행 맥락 | `TN_TRAVEL.TRAVEL_MISSION`, `TRAVEL_START_YMD`에서 파싱한 `TRAVEL_START_MONTH` | 미션과 월을 범주형으로 취급합니다. 날짜는 문서화된 `YYYY-MM-DD` 형식에서 월만 파싱하며 계절이나 순서 의미를 추론하지 않습니다. |
| POI / 영역 | 권역 원천 라벨(`region`), `TN_VISIT_AREA_INFO.SGG_CD`, `VISIT_AREA_TYPE_CD` | 권역 라벨과 방문 영역 속성을 각각 유지하고, 입력 코드를 범주형으로 취급하며 별도 코드 체계와 교차 매핑하지 않습니다. |
| 인기도 | TL의 `(region, POI_ID)`별 `POI_ID` 집계 | 권역 내 방문 빈도 구간만 사용합니다. `POI_ID`는 모델 특징이나 출력 값으로 사용하지 않습니다. TL 피드백 행의 인기도를 계산할 때 해당 여행의 방문은 제외합니다. VL 인기도는 TL 집계만 사용합니다. |
| 방문 후 결과 | `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION` | 서로 독립된 1–5 범주형 타깃으로 유지합니다. 어떤 결과값도 입력으로 사용하지 않으며, 순서 방향이나 공통 복합 척도를 가정하지 않습니다. |

권역별 스키마에서 `TRAVEL_MISSION`은 “개별 여행 목적”으로 표시됩니다. `TRAVEL_MISSION`과 `TRAVEL_START_YMD`는 모두 선택 컬럼입니다. 컬럼 가용성은 `column_availability.csv`에 권역/역할별로 기록됩니다. 어느 한쪽의 헤더가 없거나 일부 파일에서만 발견되면, 관련 맥락 분석과 특징 제거 비교를 실패로 처리하거나 인위적인 결측 범주로 채우지 않고 사용 불가로 표시합니다. 컬럼이 있을 때는 미션을 범주로 취급하고 날짜에서 월을 파싱하되 범주 의미를 추론하지 않습니다. 학습 데이터 계약에서 서비스 시점 사용 가능성, 집계 규칙 또는 방문-마스터 조인이 확정되지 않은 여행 스타일/동기 프로필, 동행자 필드, 여행 기간, `TN_POI_MASTER` 범주는 제외합니다. 스키마에 컬럼 이름이나 필수 여부가 적혀 있다는 사실만으로 키 제약이 성립하지는 않습니다. 특히 추정한 `POI_ID` 관계를 사용해 `TN_POI_MASTER`를 방문 행과 조인하지 않습니다.

따라서 이번 결과는 `TRAVEL_MISSION` + `TRAVEL_START_MONTH` 맥락과 `region` + `SGG_CD` + `VISIT_AREA_TYPE_CD` POI 표현에만 해당합니다. 여행 스타일, 동행자 유형/인원, 여행 기간, 기타 traveler preference 및 richer POI master metadata를 포함한 표현의 순위 가설로 일반화하지 않습니다.

## 결과와 통계 검정

관측된 방문 행은 양성 사례로만 취급합니다. 맥락 × 영역 분할표 검정에 사용하며 “선호” 라벨로 해석하지 않습니다. `associations.csv`와 `feedback_associations.csv`의 각 특징 쌍은 같은 `chi_square_effect` 절차를 사용합니다. 전체 지원량 `n < k=10`이거나 두 축 중 하나에 범주가 하나뿐이면 `insufficient_support`를 반환합니다. 전체 지원량이 10 이상이어도 관측된 셀 하나 이상이 1–9이면 `suppressed_k10`을 반환하고, Cramér's V와 p-value 계산을 건너뜁니다. 이 두 상태는 구분됩니다. 셀 억제를 통과하면 카이제곱 통계량과 기대 빈도를 확인합니다. 최소 기대 빈도가 5 미만이면 `sparse_expected_cells`로 표시하고 Cramér's V와 p-value를 산출하지 않습니다. 이 조건을 통과한 경우에만 Cramér's V와 기술적 참고용 `p_value_descriptive`를 계산합니다. 억제는 결과 셀을 감추는 데 그치지 않고 일부 효과 크기/검정 계산도 막습니다. 분할표 범주 표시는 권역/역할/특징/인기도 그룹 안에서만 사용하는 불투명 범주 인덱스입니다. 원래 범주 문자열과 영역 코드는 기록하지 않습니다. 권역별 및 전체 권역 범위를 각각 TL과 VL로 나누어 보고하고, TL에서 계산한 인기도 구간별 연관성도 확인합니다. 전체 권역 결과에는 권역을 별도 POI 특징으로 유지합니다. 권역별 결과는 통합 패턴이 특정 한 권역에만 국한되는지 확인합니다. 결과는 방문 행 가중 기술 통계입니다.

이 분석은 각 방문 행을 관측 단위로 세므로, 같은 여행의 반복 방문은 맥락을 공유하면서 방문 수만큼 반영됩니다. 방문이 많은 여행이 더 큰 가중치를 갖고 여행 단위 독립 관측으로 보정되지 않습니다. 따라서 Cramér's V는 방문 행 가중 기술 효과 크기이고, p-value는 독립 행 추론이나 Go 판단의 근거가 아닙니다. 다중 비교 보정이나 cluster-robust 추론은 수행하지 않았습니다.

세 피드백 필드는 각각 결측, 문서화된 1–5 범주, 범위 밖 범주를 확인하고, 포함된 각 맥락/영역 특징별 범주 분포도 점검합니다. 각 권역과 역할별로 별도 수행하며, 권역을 명시적 영역 특징으로 유지하는 전체 권역 통합 결과도 냅니다. 교차표의 특징/결과 범주 표시는 불투명 인덱스이며, 범주 수가 작거나 검정 셀이 작으면 k=10 기준으로 억제합니다.

`feedback_context_poi_distributions.csv`에는 세 결과 각각과 포함된 모든 맥락/POI 특징 쌍에 대해 맥락 × POI × 피드백 결합 분포가 추가됩니다. 맥락, POI, 피드백 범주는 불투명 인덱스로만 표시합니다. 코드는 결합 셀 수를 계산한 뒤 관측된 셀 중 하나라도 k=10 미만이면 해당 특징 쌍/결과의 표 전체를 억제합니다. 이는 계산된 분포를 단순히 감추는 데 그치지 않고 작은 셀을 포함하는 전체 분포를 산출물로 내보내지 않는 정책입니다. 선택적 맥락, POI 또는 피드백 헤더가 없으면 사용 불가로 표시합니다. 실제 180개 표가 모두 억제된 결과에는 실제 희소성과 k=10 개인정보 보호/reporting suppression이 함께 작용합니다. 공개된 표만으로 underlying signal의 부재를 결론 내릴 수 없습니다. suppression된 셀을 포함한 추가 통계가 현 정책에서 안전하게 공개될 근거가 없으므로, 여기서는 이를 한계로만 기록하고 추가 값을 공개하지 않습니다. 이 산출물은 추론용 p-value를 추가하지 않습니다.

방문 행만으로는 미방문, 방문 기회, 음성 표본 추출 모집단을 정의할 수 없습니다. 따라서 이 실험에서는 이진 방문 분류기, POI relevance Top-K ranking 지표, 관측되지 않은 POI 관련성에 대한 주장을 만들지 않습니다. 관측되지 않은 POI를 음성으로 간주하면 #45에서 승인하지 않은 라벨 계약 변경이 됩니다.

## 예측 특징 제거 비교

스크립트는 각 피드백 결과를 서로 독립적으로 다루는 결정론적 범주형 Naive Bayes 모델을 학습합니다. 타깃은 `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`이며, 다중 클래스 VL log loss는 사후 feedback predictability를 확인하는 보조 진단입니다. 이는 추천기나 POI relevance 순위 모델이 아니며 ranking objective를 직접 평가하지 않습니다. TL에서 학습한 뒤 VL에서 평가하고, 전체 권역 모델과 권역별 모델을 각각 냅니다. 선택 특징/라벨 헤더가 없으면 `column_availability.csv`에 기록하고, 결측 컬럼을 모두 결측으로 채운 것처럼 취급하지 않고 관련 분석과 특징 제거 비교를 `unavailable_missing_column`으로 표시합니다. 네 가지 특징군은 다음과 같습니다.

1. popularity-only 방문 빈도 구간
2. context-only 미션 및 시작 월
3. POI-only 권역, 행정구역 코드, 방문 영역 유형
4. context plus POI 특징

인기도는 TL에서만 계산하며 VL은 사용하지 않습니다. TL/VL을 합치거나 무작위로 다시 나누지 않으며, 하이퍼파라미터 탐색, 음성 표본 추출, 행 단위 산출물을 만들지 않습니다. 학습/검증 지원량이 부족하거나 결과 범주 하나라도 k=10 미만이면 점수를 억제합니다. VL에 있는 결과 범주가 TL에 없을 때도 해당 ablation 점수를 건너뛰며 임의의 확률 하한값을 사용해 log loss를 계산하지 않습니다. log loss는 순위 지표로 해석하지 않습니다. 동일한 VL 역할에서 context+POI를 popularity-only 및 POI-only와 비교하고, 방향이 권역별로 일관적인지 보고합니다. 이 방문 행 단위 피드백 예측 결과는 같은 여행의 반복 방문을 독립 관측처럼 보정하지 않으며, 순위 목적함수 평가나 ranking 성능의 직접 증거가 아닙니다. 15개 scope/outcome 비교에서 context+POI가 두 기준선보다 나빴다는 결과는 이번 제한된 feature set의 피드백 예측에만 해당합니다. 이는 전체 POI relevance Top-K ranking hypothesis의 실패를 직접 입증하지 않습니다. 인기도 구간 연관성 분석은 인기도 교란을 거칠게 점검할 뿐 이를 모두 제거하지는 못합니다. 더 강한 주장을 하려면 별도 승인된 모델/추정 대상이 필요합니다.

## 누수 및 개인정보 보호 점검

- `TRAVEL_ID`는 메모리 안에서 방문 행과 여행 맥락을 조인하고, TL 이벤트를 그룹화해 현재 여행의 방문이 해당 여행의 인기도 특징에 포함되지 않도록 하는 데 사용합니다. 특징 벡터나 직렬화 결과에는 포함하지 않습니다.
- `POI_ID`는 권역별 인기도 집계를 위한 그룹 키로만 사용하며 특징 벡터, 로그, 메타데이터, 결과 파일에 포함하지 않습니다.
- `VISIT_AREA_ID`와 여행자 ID는 특징으로 사용하지 않습니다. 여행자 또는 여행 식별자를 결과에 기록하지 않습니다.
- 데이터 행을 읽기 전에 필수 ID/조인 헤더를 검사합니다. 선택 후보 및 여행 맥락 컬럼(`TRAVEL_MISSION`, `TRAVEL_START_YMD`, `POI_ID`, `SGG_CD`, `VISIT_AREA_TYPE_CD`, 세 피드백 라벨)은 권역/역할/테이블별로 사용 가능, 일부 파일에서만 사용 가능, 누락 상태를 기록합니다.
- 피드백은 예측 타깃으로만 사용합니다. 피드백 필드, `REVISIT_YN`, 방문 순서/시간, 이름, 좌표, GPS, 사진, 설명문, 소비/이벤트 필드는 예측 변수로 사용하지 않습니다.
- 권역 간 일관성을 보는 것이 이 실험의 일부이므로 네 권역 각각에 TL 하나와 VL 하나를 요구합니다. 소스 검증은 기존 `evaluate_popularity.py`/`evaluate_cf.py` 계약을 따릅니다. 각 폴더는 `--raw-root` 아래에 있고 서로 달라야 하며, 역할에 맞는 이름(`TL_csv`/`VL_csv`)을 가져야 합니다. 승인된 capital 파일키 폴더는 `--allow-approved-capital-filekey-folders` 옵션을 지정한 경우에만 허용합니다. 실행기는 디렉터리 경로에서 권역을 추론하지 않습니다. `capital`, `west`, `east`, `jeju-islands` 라벨은 명시한 `--input` 역할 매핑에서 오며, 데이터 읽기 전에 승인된 Issue #31 매핑과 로컬에서 대조해야 합니다. 경로와 폴더 이름은 보고서에 기록하지 않습니다. TL은 학습/개발, VL은 외부 재현입니다. 코드에서 두 역할을 합치거나 행을 재분할하지 않습니다.
- 분석 전에 각 권역 안에서 TL과 VL의 `TRAVEL_ID`를 비교합니다. 하나라도 겹치면 실행을 중단하고 권역과 `<10` 또는 `10+`의 개인정보 보호용 개수 구간만 보고합니다. 오류에 ID나 경로는 포함하지 않습니다.
- 분석 전에 각 소스 역할의 여행-방문 맥락 조인 무결성을 검사합니다. 여행 ID 누락, 사용 가능한 맥락 값이 없는 여행, 서로 다른 맥락으로 중복된 여행 ID, 정확히 연결할 수 없는 방문 행을 각각 셉니다. 문제가 하나라도 있으면 특징 분석 전에 실패 처리합니다. 오류에는 권역/역할과 `<10`/`10+` 구간만 포함하며 식별자나 경로를 포함하지 않습니다. 연결할 수 없는 행을 조용히 제외하지 않습니다.
- 결과에는 문서화된 특징/결과 이름, 불투명 범주 인덱스, 지원량 구간, 효과 크기, 기술적 참고용 p-value, 집계 log loss만 포함합니다. 작은 지원량은 k=10 기준으로 억제합니다. 원래 범주 값, ID, 경로, 파일명, capital 역할 폴더 이름은 출력 메타데이터에 넣지 않습니다.
- 실행기는 데이터셋 승인, 이용 조건, 원래 셸 사전 점검, 잠정 POI 후보 처리를 확인하는 명시적 확인 옵션을 요구합니다. 이 옵션들은 작업자가 확인 절차를 마쳤음을 기록할 뿐, 승인 내용을 발견하거나 다른 셸을 검사하지 않습니다.

한계에는 장소 방문 기회의 비무작위성, 여행별 군집 방문, 설문/날짜 맥락의 서비스 시점 가용성 불확실성, 잠정적인 `POI_ID` 동일성, 불완전한 POI 메타데이터 연결, 결측/범위 밖 피드백, 관측 자료의 교란, 제한된 feature coverage와 k=10 suppression이 포함됩니다. 연관성, Cramér's V, descriptive p-value 및 feedback ablation은 방문 행 가중 결과이며 trip-level 독립 관측 추론이 아닙니다. joint feedback 표가 모두 억제되었으므로 공개된 표만으로 underlying context × POI × feedback signal의 존재 여부를 판정할 수 없습니다. 효과와 예측 특징 연관성을 인과적 설명으로 해석하지 않습니다. 더 풍부한 여행 맥락과 POI master metadata를 포함하지 않은 결과로 전체 ranking hypothesis를 기각하지 않습니다.

## 재현

먼저 선택한 소스 역할 계약을 읽고 사용자의 실제 로컬 셸에서 다음 변수를 확인합니다. 내보내지 않은 셸 변수도 포함합니다: `RAW_ROOT`, `CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, `JEJU_VL`. 변수 이름별 설정/미설정, 대상 존재 여부와 유형, 예상 TL/VL 역할 구조만 기록하고 값이나 경로는 절대 출력하지 않습니다. CSV를 열기 전에 2023년 4개 데이터셋의 신원, #12 승인과 이용 조건, TL/VL 역할을 확인합니다. 이 작업 트리 셸은 해당 확인을 대신하지 않습니다.

확인이 끝나면 Issue #31 인기도/CF 실행과 같은 TL/VL 역할 매핑을 사용해 이미 승인된 역할 폴더를 로컬 셸 변수에 지정합니다. 평가기 계약은 역할 폴더 이름, `RAW_ROOT` 아래 포함 관계, TL/VL 경로의 상이성을 요구하며 폴더 경로로 권역을 판별하지 않습니다. 승인된 capital 파일키 폴더를 사용할 때는 기존 TL/VL 매핑과 `--allow-approved-capital-filekey-folders` 옵션을 적용합니다. 로컬에서 확인한 `CAPITAL_TL`과 `CAPITAL_VL` 폴더를 사용합니다. 아래 명령은 로컬 셸 변수를 사용합니다.

```bash
RUN_ID="context-poi-2023-YYYYMMDD"
python3 scripts/recommendation/experiment_context_poi_signal.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --output "results/experiments/context-poi-signal/$RUN_ID" \
  --run-id "$RUN_ID" \
  --confirm-approved --confirm-terms --confirm-user-shell-preflight \
  --confirm-poi-candidate
```

매번 새 실행 ID를 사용합니다. 결과는 Git에서 제외되는 `results/experiments/context-poi-signal/` 아래에 저장되며 `associations.csv`, `context_poi_distributions.csv`, `column_availability.csv`, `feedback_distributions.csv`, `feedback_cross_distributions.csv`, `feedback_context_poi_distributions.csv`, `feedback_associations.csv`, `feedback_ablations.csv`, `run_metadata.json`을 포함합니다. 메타데이터에는 데이터셋/버전, 역할, 분할 정책, 난수 시드(없음), 코드 개정 정보와 작업 트리 변경 상태, 스크립트 해시, 실행 시간, 결과 필드 목록, 개인정보 보호 기준을 기록하되 입력 경로, 소스 파일명, 파일키 값은 기록하지 않습니다.

합성 데이터만 사용하는 검증:

```bash
python3 -m unittest tests.test_context_poi_signal -v
```

## #41 판단

**상태: Inconclusive / insufficient feature coverage.** Go gate는 충족되지 않았습니다. 제한된 현재 특징에서 충분한 context-aware recommendation signal을 확인하지 못했고, feedback prediction에서 context+POI가 popularity-only 또는 POI-only를 개선하지 못했습니다. 그러나 여행 스타일, 동행자 유형/인원, 여행 기간, 기타 traveler preference, richer POI master metadata가 빠져 있고, privacy-safe joint feedback 표가 모두 억제되어 전체 가설의 기각 근거는 부족합니다. #41의 전체 ranking hypothesis는 결론을 유보합니다. 방문 행 가중 Cramér's V와 p-value는 독립 여행 관측 추론이 아니며, feedback log loss도 trip-level 독립 관측으로 보정되지 않은 보조 predictability 진단입니다. unvisited POI를 negative로 만들지 않았으므로 POI relevance Top-K ranking objective는 직접 평가하지 않았습니다. privacy threshold를 완화하거나 작은 셀을 공개하지 않습니다.
