# AI Hub 2023 국내 여행로그 데이터 설명서 — 동부권

## 출처와 변환 범위

- 데이터셋: [국내 여행로그 데이터(동부권, 2023)](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71778) (`dataSetSn=71778`)
- 원본: `119-146_국내여행로그데이터(동부권)_데이터설명서.hwp` (1,787,904 bytes)
- 원본 SHA-256: `bc3b678919e4d6cbcee2c06c7cc700c81c9474cbb676af245ab83fbc7d26d667`
- CSV 파일명 권역 접미사: `F`
- HWP 표를 Markdown 표로 변환했다. 병합 셀은 Markdown 형식에 맞춰 병합 시작 셀에만 내용을 남겼다.
- 담당자 실명·전화번호·이메일, 사진·캡션 샘플 레코드 값은 복제하지 않았다. 이미지 예시도 포함하지 않았다.
- 데이터 분포는 설명서의 공개 집계 표를 옮긴 것이며, 새로 계산한 분석 결과가 아니다.

> 표의 용어, 코드 범위, 자료형은 원문 표기를 따른다. 문서가 선언하지 않은 키 제약이나 코드 의미를 추가하지 않는다.

## 텍스트 원천 기본 메타데이터

| 메타테이블<br>정보<br>(다중기입가능) | 분야 | 데이터 유형 | 구축 데이터량 | 원천데이터 형식 | 라벨링 형식 | 라벨링 유형 |
| --- | --- | --- | --- | --- | --- | --- |
|  |  | 텍스트 | 3,200set | csv | csv | 로그데이터 (텍스트) |
|  | 데이터 출처 | 데이터 구축년도 | 구축기관(총괄) | 가공기관 | 검수기관 |  |
|  | 자체 수집 | 2023년 | ㈜ 데이터웨이 | ㈜ 지디에스 컨설팅그룹 | ㈜ 데이터웨이 |  |
|  | 데이터 소개 | 수도권, 동부권, 서부권, 제주 및 도서지역 각 권역별로 3,200세트 씩,<br>총 12,800세트의 여행로그 데이터를 구축 |  |  |  |  |
|  | 주요키워드 | 여행로그 |  |  |  |  |
| 카테고리 정의서 |  | 119-146_ 국내여행로그데이터(동부권) _ 카테고리정의서. xlsx |  |  |  |  |

## 이미지 원천 기본 메타데이터

| 메타테이블<br>정보<br>(다중기입가능) | 분야 | 데이터 유형 1) | 구축 데이터량 | 원천데이터 형식 2) | 라벨링 형식 3) | 라벨링 유형 4) |
| --- | --- | --- | --- | --- | --- | --- |
|  |  | 이미지 | 18,131장 | jpg | csv | 사진정보<br>(텍스트) |
|  | 데이터 출처 5) | 데이터 구축년도 | 구축기관(총괄) | 가공기관 | 검수기관 |  |
|  | 자체 수집 | 2023년 | ㈜ 데이터웨이 | ㈜ 지디에스 컨설팅그룹 | ㈜ 데이터웨이 |  |
|  | 데이터 소개 | 수도권, 동부권, 서부권, 제주 및 도서지역 각 권역별로 3,200세트 씩,<br>총 12,800세트의 여행로그 데이터를 구축 |  |  |  |  |
|  | 주요키워드 | 관광사진 |  |  |  |  |
| 카테고리 정의서 |  | 119-146_ 국내여행로그데이터(동부권) _ 카테고리정의서. xlsx |  |  |  |  |

## 데이터셋 개요

- **데이터셋명**: 국 문<br>국내 여행로그 데이터 (동부권)
- **영 문**: domestic travel log data
- **구축목적**: ◦ 여행자의 이동패턴과 소비내역, 활동 내역 등 데이터 수집<br>◦ 관광업계 자체적으로 수집하기 어려운 양질의 AI 데이터 제공<br>◦ AI 기술을 활용한 관광산업 혁신 생태계 구축<br>◦ AI 기술 기반의 개인화된 서비스로 관광객들의 경험 향상
- **활용서비스**: ☐ 여행로그 장소 추천 고도화<br>◦ 학습 모델 개요<br>여행지의 관광 명소를 추천하여 결정에 도움을 주는 추천시스템 개발<br>여행객이 입력한 정보를 기반으로, 비슷한 정보를 가졌던 복수의 여행객들의 데이터를 활용하여 여행 장소를 추천<br>- Collaborative Filtering( 협업 필터링) 개요<br>. Netflix Prize 를 통해 명성을 얻기 시작한 방법론<br>. 사용자와 아이템 데이터를 활용하여 ' ~ 와 비슷한 상품', '당신이 좋아할 만한 상품', '다른 고객이 함께 본 상품' 등 쇼핑, 영화, 도서 서비스에서 대중적으로 많이 사용되고 있음<br>. Collaborative Filtering( 협업 필터링)에는 사용자 특성 중심으로 분석하는 User-Based CF(UCF) 와 아이템 특성 중심으로 Item-Based CF(ICF) 2 가지로 나눌 수 있음<br>. 본 과제에서는 여행객들의 특성이 더 중요한 요인이므로 UCF 방법론을 활용을 고려 중<br>- User-Based CF (UCF)<br>. 여러 여행객들이 방문한 장소들의 특성 데이터에서 사용자와 장소 간의 상호 작용을 분석하여 여행객의 취향을 예측하는 방법론<br>. 예를 들어 여행객1 이 A, B, C 장소를 방문하였고 여행객2가 A, B 장소를 방문했으며, 사용자1, 2의 성향이 비슷하다면 여행객2가 C 도 좋아할 확률이 높음<br>. UCF 는 여행객들의 수와 여행객들이 방문한 장소의 수가 많을수록 분석의 예측력이 높아지는 구조를 가짐<br>◦ 학습 모델의 활용<br>- 기존 여행지 추천과 여행 경로 선택은 전적으로 타인의 추천 혹은 리뷰를 바탕으로 이루어졌으나, 대중적인 여행지 선택이 사용자의 취향에 부합할 수 있으나 부합하지 않을 경우 사용자가 불편함을 느낄 수 있음<br>- 여행객의 정보를 방문지 추천에 반영하여 사용자의 특성에 부합하는 장소 항목을 추천<br>- 또한 각 여행 페르소나별 선호도 예측 모델을 분석하여 어떤 항목이 포함되어 있을 때 어떤 여행지의 선호도 예측 값이 높게 나오는지 확인, 마케팅 및 여행 산업 계획에 포함시킬 수 있음<br>◦ 학습 모델의 검증 방법<br>- 해당 성능 검증 방법은 지도 학습 방식으로 모델 성능을 측정하기 위해, 추천시스템 내에서 사용하는 ‘ 만족도 예측 모델 ’ 의 성능을 검증하는 방식<br>- 만족도 예측 모델의 성능에 따라 추천시스템의 성능이 비례함으로 추천시스템 성능 검증 방법으로 제시<br>- 만족도 예측 모델 성능 검증 방식<br>. 모델을 활용하여 사용자가 다녀온 곳 과의 일정 거리 내에 있는 방문지에 대한 만족도 예측<br>. 예측한 만족도 중 만족도가 가장 높은 상위 5개 방문지 추출, 추천의 결과로 사용<br>. 해당 유저가 ‘ 만족 ’ 한다고 평가한 방문지 중, 모델이 추천한 5개의 방문지가 몇 개 포함되었는지의 비율을 구하여 recall@5 (user) 값 산출<br>. 검증 데이터셋의 모든 유저에 대한 recall@5 (user) 값을 구한 후, 그 평균을 계산하여 최종 recall@5 값 산출<br>☐ 여행객 선호도 기반 관광지 숙박 장소 추천<br>◦ 학습 모델 개요<br>- 여행지의 관광지 숙박 장소를 추천하여 결정에 도움을 주는 추천시스템 개발<br>- 여행객이 입력한 정보를 기반으로, 비슷한 정보를 가졌던 복수의 여행객들의 데이터를 활용하여 숙박 장소를 추천<br>- Collaborative Filtering( 협업 필터링) 개요<br>. Netflix Prize 를 통해 명성을 얻기 시작한 방법론<br>. 사용자와 아이템 데이터를 활용하여 ' ~ 와 비슷한 상품', '당신이 좋아할 만한 상품', '다른 고객이 함께 본 상품' 등 쇼핑, 영화, 도서 서비스에서 대중적으로 많이 사용되고 있음<br>. Collaborative Filtering( 협업 필터링)에는 사용자 특성 중심으로 분석하는 User-Based CF(UCF) 와 아이템 특성 중심으로 Item-Based CF(ICF) 그리고 잠재요인 분석 기반의 Latent Factor-based CF(LFCF) 3 가지로 나눌 수 있음<br>. 본 과제에서는 여행객과 숙박 장소 사이에 존재하는 잠재 요인이 더 중요함으로 LFCF 방법론 활용을 고려 중<br>- Latent Factor-based CF (LFCF)<br>. LFCF 는 여행객과 숙박 장소 간의 상호작용을 기반으로 여행객의 숙박 장소에 대한 선호도를 예측하는 방법입니다.<br>. 여행객과 숙박 장소의 상호작용 행렬을 두 개의 잠재 요인 행렬로 분해하는 것입니다. 이 두행렬은 각각 여행객과 숙박 장소를 잠재 공간에서의 벡터로 표현합니다. 이 벡터들은 여행객의 선호도나 숙박 장소의 특성을 나타내는 것으로 해석될 수 있습니다.<br>. 이렇게 구해진 잠재 요인 행렬을 사용하여, 여행객이 아직 평가하지 않은 숙박 장소에 대한 예측 평점을 계산하는 것입니다. 이는 여행객 벡터와 숙박 장소 벡터의 내적으로 계산됩니다.<br>. LFCF 는 행렬분해( Matrix Factorization) 기법을 사용합니다. 여행객과 숙박 장소 간의 상호작용 행렬의 빈칸이 많은 경우에도 잘 동작하며, 대규모 데이터셋에 대해 효율적으로 처리할 수 있습니다.<br>◦ 학습 모델의 활용<br>- 기존 여행지 숙박 추천은 전적으로 타인의 추천 혹은 리뷰를 바탕으로 이루어졌으나, 대중적인 숙박 장소 선택이 사용자의 취향에 부합할 수 있으나 부합하지 않을 경우 사용자가 불편함을 느낄 수 있음<br>- 여행객의 정보를 숙박 장소 추천에 반영하여 사용자의 특성에 부합하는 장소 항목을 추천<br>- 또한 각 여행 페르소나별 선호도 예측 모델을 분석하여 어떤 항목이 포함되어 있을 때 어떤 숙박 장소의 선호도가 높은지 확인, 마케팅 및 여행 산업 계획에 포함시킬 수 있음<br>◦ 학습 모델의 검증 방법<br>- 해당 성능 검증 방법은 지도 학습 방식으로 모델 성능을 측정하기 위해, 추천시스템 내에서 사용하는 ‘ 만족도 예측 모델 ’ 의 성능을 검증하는 방식<br>- 만족도 예측 모델의 성능에 따라 추천시스템의 성능이 비례함으로 추천시스템 성능 검증 방법으로 제시<br>- 만족도 예측 모델 성능 검증 방식<br>. 데이터 준비: 사용자-아이템 상호작용 데이터를 학습 데이터와 테스트 데이터로 분리합니다.<br>. 모델 학습: 학습 데이터를 사용하여 모델을 학습시킵니다. 이때 사용자와 아이템의 잠재 요인을 추정합니다.<br>. 아이템 추천: 학습된 모델을 사용하여 테스트 데이터의 각 사용자에 대해 아이템을 추천합니다. 추천 리스트는 예측 평점이 높은 순서로 정렬됩니다.<br>. Recall@5 계산: 각 사용자에 대해, 실제로 관심을 가진 아이템들 중에서 추천 리스트 상위 5개 안에 포함된 아이템의 수를 계산하고, 이를 실제 관심 아이템의 총 수로 나눕니다.<br>. 성능 평가: 모든 사용자에 대한 Recall@5 값을 평균하여 모델의 전체 성능을 평가합니다.
- **소개**: ㅇ 국내 여행로그 데이터 구축 필요성<br>- 코로나19 확산 이후 언택트 및 디지털 관광으로의 전환이 가속화되고 있음<br>- 인구구조와 여행패턴의 변화로 개인 맞춤형 관광 서비스가 본격화되고 있음<br>- 관광산업 혁신을 위해 AI 기술을 적극 도입해야 하며 이를 위한 학습용 데이터 필요<br>ㅇ 데이터 구축 내용<br>- 국내를 수도권, 동부권, 서부권, 제주 및 도서지역 등 4가지 권역으로 나누어 여행객을 모집하고, 스마트폰 전용앱을 통해 데이터를 수집<br>- 수도권, 동부권, 서부권, 제주 및 도서지역 각 권역별로 4천세트 씩, 총 16,000세트의 여행로그 데이터를 구축<br>- 여행동선 데이터, 소비내역 데이터, 활동기록 데이터, 여행지 사진 등을 수집<br>- 수집된 데이터를 정제한 후, 촬영사진 블러링, 영수증 Key-In 등의 가공작업 수행<br>- 고지출 여행객 예측모델 : F1-Score 80.07% 달성 (목표 70%)<br>- 여행장소 추천모델 : Recall@10 0.3745 달성 (목표 0.25)<br>ㅇ 시범 AI 모델 개발<br>- 여행자 정보 기반 고지출 여행객 예측 모델 : 여행객들의 사전조사 정보를 토대로 여행지에서 지출을 많이 하는 여행객들을 예측<br>- 여행자 선호도 기반 여행장소 추천모델 : 성별, 연령대, 소득 등의 여행객 정보와 여행지역(시도/시군구) 정보를 입력하면 10개의 여행지를 추천
- **데이터셋 통계<br>(구축 규모 및 분포)**: 1. 데이터 구축 규모<br>분류<br>파일구성<br>설명<br>구축 규모<br>photo<br>PHOTO<br>여행객 직접 촬영한 관광사진<br>18,131장<br>CSV<br>TN_TRAVELLER_MASTER<br>여행객에 대한 정보<br>3,200set<br>TN_TRAVEL<br>여행 기본 정보<br>3,200set<br>TN_COMPANION_INFO<br>동반자 정보<br>3,200set<br>TN_MOVE_HIS<br>여행기간동안 이동한 내역<br>3,200set<br>TN_MVMN_CONSUME_HIS<br>교통비<br>3,200set<br>TN_LODGE_CONSUME_HIS<br>숙박비<br>3,200set<br>TN_ADV_CONSUME_HIS<br>여행가기전에 소비내역<br>3,200set<br>TN_VISIT_AREA_INFO<br>여행 방문지정보<br>3,200set<br>TN_TOUR_PHOTO<br>여행중 촬영한 여행 사진<br>3,200set<br>TN_ACTIVITY_HIS<br>여행기간동안 활동한 내역<br>3,200set<br>TN_ACTIVITY_CONSUME_HIS<br>여행기간동안 소비한 내역<br>3,200set<br>TC_SGG<br>시군구 코드 테이블 정의<br>1개<br>TC_CODEA<br>코드 리스트 테이블 정의<br>1개<br>TC_CODEB<br>코드 상세 테이블 정의<br>1개<br>GPS<br>TN_GPS_COORD<br>이동경로 GPS 좌표 정보<br>3,200개<br>서브라벨링<br>JSON<br>이미지캡션 라벨링데이터<br>3,059개<br>PHOTO<br>이미지캡션 이미지데이터<br>3,059장<br>other<br>TN_POI_MASTER<br>POI 정보<br>1개<br>2. 데이터 분포<br>동부권 성별 남 1,340 41.88% 여 1,860 58.12% 합계 3,200 100% 연령별 20대 1,056 33.00% 30대 968 30.25% 40대 681 21.28% 50대 ↑ 495 15.47% 합계 3,200 100% 여행 기간별 당일 1,478 46.19% 1박2일 1,349 42.16% 2박3일 ↑ 373 11.66% 합계 3,200 100%<br>동부권<br>성별<br>남<br>1,340<br>41.88%<br>여<br>1,860<br>58.12%<br>합계<br>3,200<br>100%<br>연령별<br>20대<br>1,056<br>33.00%<br>30대<br>968<br>30.25%<br>40대<br>681<br>21.28%<br>50대 ↑<br>495<br>15.47%<br>합계<br>3,200<br>100%<br>여행 기간별<br>당일<br>1,478<br>46.19%<br>1박2일<br>1,349<br>42.16%<br>2박3일 ↑<br>373<br>11.66%<br>합계<br>3,200<br>100%
- **데이터셋 구성**: 1. 데이터 구축 ERD<br>2. 파일명 구성정보<br>csv 파일<br>예시 세부 구성 설명 tn_activity_consume_his_ 활동소비내역 _F.csv {tn_activity_consume_his}_{ 활동소비내역 }_{F}.csv { 영문테이블명 }_{ 한글테이블명 }_{ 권역정보 }.csv ※ 권역정보 E : 수도권 F : 동부권 G : 서부권 H : 제주도 및 도서지역<br>예시<br>세부 구성 설명<br>tn_activity_consume_his_ 활동소비내역 _F.csv<br>{tn_activity_consume_his}_{ 활동소비내역 }_{F}.csv<br>{ 영문테이블명 }_{ 한글테이블명 }_{ 권역정보 }.csv<br>※ 권역정보<br>E : 수도권<br>F : 동부권<br>G : 서부권<br>H : 제주도 및 도서지역<br>gps_data 파일<br>예시 세부 구성 설명 tn_gps_coord_e_<예시 식별자 생략>.csv {tn_gps_coord}_{e_<예시 식별자 생략>}.csv { 영문테이블명 }_{ 여행객아이디 }.csv<br>예시<br>세부 구성 설명<br>tn_gps_coord_e_<예시 식별자 생략>.csv<br>{tn_gps_coord}_{e_<예시 식별자 생략>}.csv<br>{ 영문테이블명 }_{ 여행객아이디 }.csv<br>관광사진 파일<br>예시 세부 구성 설명 <예시 식별자 생략>.jpg {<예시 식별자 생략>}{01}{004}{p}{00}{03}.jpg { 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg 여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>예시<br>세부 구성 설명<br><예시 식별자 생략>.jpg<br>{<예시 식별자 생략>}{01}{004}{p}{00}{03}.jpg<br>{ 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg<br>여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>여행자 계정<br>여행일<br>순번<br>경로<br>번호<br>사진구 분<br>활동번호<br>사진번호<br>(7)<br>(2)<br>(3)<br>(1)<br>(2)<br>(2)<br>권역 + 6자리<br>1일 ~n 일<br>001 ~ 099<br>P= 관광<br>사진<br>사진 구분 P 이면, 00값 입력<br>사진번호<br>json 파일<br>예시 세부 구성 설명 <예시 식별자 생략>.json {<예시 식별자 생략>}{01}{004}{p}{00}{03}.json { 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg 여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>예시<br>세부 구성 설명<br><예시 식별자 생략>.json<br>{<예시 식별자 생략>}{01}{004}{p}{00}{03}.json<br>{ 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg<br>여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>여행자 계정<br>여행일<br>순번<br>경로<br>번호<br>사진구 분<br>활동번호<br>사진번호<br>(7)<br>(2)<br>(3)<br>(1)<br>(2)<br>(2)<br>권역 + 6자리<br>1일 ~n 일<br>001 ~ 099<br>P= 관광<br>사진<br>사진 구분 P 이면, 00값 입력<br>사진번호<br>데이터 파일<br>구분 파일유형 파일명 원천데이터 photo 여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조) 라벨링데이터 csv c_codea_ 코드 A.csv tc_codeb_ 코드 B.csv tc_sgg_ 시군구코드. csv tn_activity_consume_his_ 활동소비내역 _F.csv tn_activity_his_ 활동내역 _F.csv tn_adv_consume_his_ 사전소비내역 _F.csv tn_companion_info_ 동반자정보 _F.csv tn_lodge_consume_his_ 숙박소비내역 _F.csv tn_move_his_ 이동내역 _F.csv tn_mvmn_consume_his_ 이동수단소비내역 _F.csv tn_tour_photo_ 관광사진 _F.csv tn_traveller_master_ 여행객 Master_F.csv tn_travel_ 여행 _F.csv tn_visit_area_info_ 방문지정보 _F.csv gps_data n_gps_coord_{}.csv (3200 개) ( {} = 여행객 ID ) 서브라벨링 json 여행객 ID + 순번. json ( 파일명 구성 및 세부 구성 정보 참조) photo 여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조) other 메타데이터 tn_poi_master_POIMaster.csv<br>구분<br>파일유형<br>파일명<br>원천데이터<br>photo<br>여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조)<br>라벨링데이터<br>csv<br>c_codea_ 코드 A.csv<br>tc_codeb_ 코드 B.csv<br>tc_sgg_ 시군구코드. csv<br>tn_activity_consume_his_ 활동소비내역 _F.csv<br>tn_activity_his_ 활동내역 _F.csv<br>tn_adv_consume_his_ 사전소비내역 _F.csv<br>tn_companion_info_ 동반자정보 _F.csv<br>tn_lodge_consume_his_ 숙박소비내역 _F.csv<br>tn_move_his_ 이동내역 _F.csv<br>tn_mvmn_consume_his_ 이동수단소비내역 _F.csv<br>tn_tour_photo_ 관광사진 _F.csv<br>tn_traveller_master_ 여행객 Master_F.csv<br>tn_travel_ 여행 _F.csv<br>tn_visit_area_info_ 방문지정보 _F.csv<br>gps_data<br>n_gps_coord_{}.csv (3200 개) ( {} = 여행객 ID )<br>서브라벨링<br>json<br>여행객 ID + 순번. json ( 파일명 구성 및 세부 구성 정보 참조)<br>photo<br>여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조)<br>other<br>메타데이터<br>tn_poi_master_POIMaster.csv<br>3. 여행로그 테이블 리스트<br>한글테이블명<br>영문테이블명<br>설명<br>여행객 Master<br>TN_TRAVELLER_MASTER<br>여행객에 대한 정보<br>POI Master<br>TN_POI_MASTER<br>POI 정보<br>여행<br>TN_TRAVEL<br>여행 기본 정보<br>동반자정보<br>TN_COMPANION_INFO<br>동반자 정보<br>이동내역<br>TN_MOVE_HIS<br>여행기간동안 이동한 내역<br>GPS 좌표<br>TN_GPS_COORD<br>이동한 GPS 좌표 정보<br>이동수단소비내역<br>TN_MVMN_CONSUME_HIS<br>교통비<br>숙박소비내역<br>TN_LODGE_CONSUME_HIS<br>숙박비<br>사전소비내역<br>TN_ADV_CONSUME_HIS<br>여행가기전에 소비내역<br>방문지정보<br>TN_VISIT_AREA_INFO<br>여행 방문지정보<br>관광사진<br>TN_TOUR_PHOTO<br>여행중 촬영한 여행 사진<br>활동내역<br>TN_ACTIVITY_HIS<br>여행기간동안 활동한 내역<br>활동소비내역<br>TN_ACTIVITY_CONSUME_HIS<br>여행기간동안 소비한 내역<br>시군구<br>TC_SGG<br>시군구 코드 테이블<br>코드 A<br>TC_CODEA<br>코드 리스트 테이블<br>코드 B<br>TC_CODEB<br>코드 상세 테이블<br>4 여행로그 테이블 정의서<br>구분<br>속성명<br>타입<br>필수 여부<br>설명<br>범위<br>비고<br>1<br>TN_TRAVELLER_MASTER<br>TABEL<br>여행객 Master<br>1-1<br>TRAVELER_ID<br>varchar(255)<br>Y<br>여행객 ID<br>1-2<br>RESIDENCE_SGG_CODE<br>varchar(50)<br>N<br>거주지시군구코드<br>tc_sgg 참조<br>1-3<br>GENDER<br>varchar(50)<br>N<br>성별<br>1-4<br>AGE_GRP<br>varchar(50)<br>N<br>연령대<br>1-5<br>EDU_NM<br>varchar(50)<br>N<br>최종학력<br>[1~8]<br>코드 ‘ EDU ’<br>1-6<br>EDU_FNSH_SE<br>varchar(50)<br>N<br>최종학력이수여부<br>[1~5]<br>코드 ‘ EFS ’<br>1-7<br>MARR_STTS<br>varchar(50)<br>N<br>혼인상태<br>[1~5]<br>코드 ‘ MAR ’<br>1-8<br>FAMILY_MEMB<br>varchar(255)<br>N<br>가족현황<br>1-9<br>JOB_NM<br>varchar(100)<br>N<br>직업<br>[1~13]<br>코드 ‘ JOB ’<br>1-10<br>JOB_ETC<br>varchar(50)<br>N<br>직업 _ 기타<br>[1~3]<br>코드 ‘ JOE ’<br>1-11<br>INCOME<br>varchar(50)<br>N<br>본인소득<br>[1~12]<br>코드 ‘ INC ’<br>1-12<br>HOUSE_INCOME<br>varchar(50)<br>N<br>가구소득<br>[1~12]<br>코드 ‘ INC ’<br>1-13<br>TRAVEL_TERM<br>varchar(50)<br>N<br>여행빈도 _ 기간<br>[1~4]<br>코드 ‘ TTM ’<br>1-14<br>TRAVEL_NUM<br>int(11)<br>N<br>여행빈도<br>1-15<br>TRAVEL_LIKE_SIDO_1<br>varchar(50)<br>N<br>선호여행 _ 시도 _1<br>tc_sgg 참조<br>1-16<br>TRAVEL_LIKE_SGG_1<br>varchar(50)<br>N<br>선호여행 _ 시군구 _1<br>tc_sgg 참조<br>1-17<br>TRAVEL_LIKE_SIDO_2<br>varchar(50)<br>N<br>선호여행 _ 시도 _2<br>tc_sgg 참조<br>1-18<br>TRAVEL_LIKE_SGG_2<br>varchar(50)<br>N<br>선호여행 _ 시군구 _2<br>tc_sgg 참조<br>1-19<br>TRAVEL_LIKE_SIDO_3<br>varchar(50)<br>N<br>선호여행 _ 시도 _3<br>tc_sgg 참조<br>1-20<br>TRAVEL_LIKE_SGG_3<br>varchar(50)<br>N<br>선호여행 _ 시군구 _3<br>tc_sgg 참조<br>1-21<br>TRAVEL_STYL_1<br>varchar(50)<br>N<br>여행스타일 _1<br>[1~7]<br>코드 ‘ TSY ’<br>1-22<br>TRAVEL_STYL_2<br>varchar(50)<br>N<br>여행스타일 _2<br>[1~7]<br>코드 ‘ TSY ’<br>1-23<br>TRAVEL_STYL_3<br>varchar(50)<br>N<br>여행스타일 _3<br>[1~7]<br>코드 ‘ TSY ’<br>1-24<br>TRAVEL_STYL_4<br>varchar(50)<br>N<br>여행스타일 _4<br>[1~7]<br>코드 ‘ TSY ’<br>1-25<br>TRAVEL_STYL_5<br>varchar(50)<br>N<br>여행스타일 _5<br>[1~7]<br>코드 ‘ TSY ’<br>1-26<br>TRAVEL_STYL_6<br>varchar(50)<br>N<br>여행스타일 _6<br>[1~7]<br>코드 ‘ TSY ’<br>1-27<br>TRAVEL_STYL_7<br>varchar(50)<br>N<br>여행스타일 _7<br>[1~7]<br>코드 ‘ TSY ’<br>1-28<br>TRAVEL_STYL_8<br>varchar(50)<br>N<br>여행스타일 _8<br>[1~7]<br>코드 ‘ TSY ’<br>1-29<br>TRAVEL_STATUS_RESIDEN CE<br>varchar(50)<br>N<br>여행현황 _ 거주지<br>1-30<br>TRAVEL_STATUS_DESTINA TION<br>varchar(50)<br>N<br>여행현황 _ 목적지<br>1-31<br>TRAVEL_STATUS_ACCOMP ANY<br>varchar(50)<br>N<br>여행현황 _ 동반현황<br>1-32<br>TRAVEL_STATUS_YMD<br>varchar(50)<br>N<br>여행현황 _ 여행일자<br>1-33<br>TRAVEL_MOTIVE_1<br>varchar(50)<br>N<br>여행동기 _1<br>[1~10]<br>코드 ‘ TMT ’<br>1-34<br>TRAVEL_MOTIVE_2<br>varchar(50)<br>N<br>여행동기 _2<br>[1~10]<br>코드 ‘ TMT ’<br>1-35<br>TRAVEL_MOTIVE_3<br>varchar(50)<br>N<br>여행동기 _3<br>[1~10]<br>코드 ‘ TMT ’<br>1-36<br>TRAVEL_COMPANIONS_NU M<br>int(5)<br>N<br>여행동반자수<br>2<br>TN_POI_MASTER<br>TABEL<br>POI Master<br>2-1<br>POI_ID<br>varchar(255)<br>Y<br>POI ID<br>2-2<br>POI_NM<br>varchar(255)<br>N<br>POI 명<br>2-3<br>BRNO<br>varchar(255)<br>N<br>사업자등록번호<br>2-4<br>SGG_CD<br>varchar(255)<br>N<br>시군구코드<br>2-5<br>ROAD_NM_ADDR<br>varchar(255)<br>N<br>도로명주소<br>2-6<br>LOTNO_ADDR<br>varchar(255)<br>N<br>지번주소<br>2-7<br>ASORT_LCLASDC<br>varchar(255)<br>N<br>종별 _ 대분류<br>2-8<br>ASORT_MLSFCDC<br>varchar(255)<br>N<br>종별 _ 중분류<br>2-9<br>ASORT_SDASDC<br>varchar(255)<br>N<br>종별 _ 소분류<br>2-10<br>X_COORD<br>varchar(255)<br>N<br>X 좌표<br>2-11<br>Y_COORD<br>varchar(255)<br>N<br>Y 좌표<br>2-12<br>ROAD_NM_CD<br>varchar(255)<br>N<br>도로명코드<br>2-13<br>LOTNO_CD<br>varchar(255)<br>N<br>지번코드<br>3<br>TN_COMPANION_INFO<br>TABEL<br>동반자정보<br>3-1<br>COMPANION_SEQ<br>int(11)<br>Y<br>동반자순번<br>3-2<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>3-3<br>REL_CD<br>varchar(150)<br>N<br>동반자관계코드<br>[1~11]<br>코드 ‘ TCR ’<br>3-4<br>COMPANION_GENDER<br>varchar(50)<br>N<br>동반자성별<br>[1~2]<br>코드 ‘ GEN ’<br>3-5<br>COMPANION_AGE_GRP<br>varchar(50)<br>N<br>동반자연령대<br>[1~8]<br>코드 ‘ AGE ’<br>3-6<br>COMPANION_SITUATION<br>varchar(50)<br>N<br>동반자동반상황<br>[1~3]<br>코드 ‘ CST ’<br>4<br>TN_TRAVEL<br>TABEL<br>여행<br>4-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>4-2<br>TRAVEL_NM<br>varchar(255)<br>N<br>여행명<br>4-3<br>TRAVELER_ID<br>varchar(255)<br>Y<br>여행객 ID<br>4-4<br>TRAVEL_PURPOSE<br>varchar(150)<br>N<br>여행목적<br>코드 ‘ MIS ’<br>4-5<br>TRAVEL_START_YMD<br>date<br>N<br>여행시작일자<br>YYYY-MM-DD<br>4-6<br>TRAVEL_END_YMD<br>date<br>N<br>여행종료일자<br>YYYY-MM-DD<br>4-7<br>MVMN_NM<br>varchar(100)<br>N<br>주요이동수단<br>4-8<br>TRAVEL_PERSONA<br>varchar(150)<br>Y<br>페르소나<br>4-9<br>TRAVEL_MISSION<br>varchar(150)<br>N<br>개별미션<br>[1~13, 21~28]<br>코드 ‘ MIS ’<br>4-10<br>TRAVEL_MISSION_CHECK<br>char(50)<br>N<br>미션우선도<br>[1~13 ,21~28]<br>코드 ‘ MIS ’<br>5<br>TN_MOVE_HIS<br>TABEL<br>이동내역<br>5-1<br>TRIP_ID<br>varchar(150)<br>Y<br>Trip ID<br>5-2<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>5-3<br>START_VISIT_AREA_ID<br>varchar(100)<br>N<br>출발 방문지 ID<br>5-4<br>END_VISIT_AREA_ID<br>varchar(100)<br>N<br>도착 방문지 ID<br>5-5<br>START_DT_MIN<br>datetime<br>N<br>출발시간 _ 분<br>YYYY-MM-DD HH:MI<br>5-6<br>END_DT_MIN<br>datetime<br>N<br>도착시간 _ 분<br>YYYY-MM-DD HH:MI<br>5-7<br>MVMN_CD_1<br>varchar(255)<br>N<br>이동방법코드 _1<br>[1~16, 50]<br>코드 ‘ MOV ’<br>5-8<br>MVMN_CD_2<br>varchar(255)<br>N<br>이동방법코드 _2<br>[1~16, 50]<br>코드 ‘ MOV ’<br>6<br>TN_GPS_COORD<br>TABEL<br>GPS 좌표<br>6-1<br>MOBILE_NUM_ID<br>varchar(50)<br>Y<br>단말기번호 ID<br>6-2<br>X_COORD<br>varchar(20)<br>Y<br>X 좌표<br>6-3<br>Y_COORD<br>varchar(20)<br>Y<br>Y 좌표<br>6-4<br>DT_MIN<br>datetime<br>Y<br>시간 _ 분<br>YYYY-MM-DD HH:MI<br>6-5<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>7<br>TN_MVMN_CONSUME_HIS<br>TABEL<br>이동수단소비내역<br>7-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>7-2<br>MVMN_SE<br>varchar(150)<br>Y<br>이동수단구분<br>[1~16, 50]<br>코드 ‘ MOV ’<br>7-3<br>PAYMENT_SE<br>varchar(150)<br>Y<br>이용경비구분<br>7-4<br>PAYMENT_SEQ<br>int(11)<br>Y<br>이용경비순번<br>7-5<br>MVMN_SE_NM<br>varchar(255)<br>N<br>이동수단구분명<br>7-6<br>RSVT_YN<br>char(1)<br>N<br>예약여부<br>“ Y ” or “ N ”<br>7-7<br>PAYMENT_NUM<br>int(11)<br>N<br>포함인원<br>7-8<br>BRNO<br>varchar(10)<br>N<br>사업자등록번호<br>7-9<br>STORE_NM<br>varchar(255)<br>N<br>상호명<br>7-10<br>PAYMENT_DT<br>datetime<br>N<br>결제일시 _ 분<br>YYYY-MM-DD HH:MI<br>7-11<br>PAYMENT_MTHD_SE<br>varchar(255)<br>N<br>결제방식구분<br>[1~5]<br>코드 ‘ PAY ’<br>7-12<br>PAYMENT_AMT_WON<br>int(11)<br>N<br>결제금액 _ 원<br>7-13<br>PAYMENT_ETC<br>text<br>N<br>소비내역 _ 기타<br>8<br>TN_LODGE_CONSUME_HIS<br>TABEL<br>숙박소비내역<br>8-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>8-2<br>LODGING_NM<br>varchar(255)<br>Y<br>숙소명<br>8-3<br>LODGE_PAYMENT_SEQ<br>int(11)<br>Y<br>숙박경비순번<br>8-4<br>LODGING_TYPE_CD<br>char(10)<br>N<br>숙소유형코드<br>[1~12]<br>코드 ‘ HTY ’<br>8-5<br>RSVT_YN<br>char(3)<br>N<br>예약여부<br>8-6<br>CHK_IN_DT_MIN<br>datetime<br>N<br>체크인시간 _ 분<br>YYYY-MM-DD HH:MI<br>8-7<br>CHK_OUT_DT_MIN<br>datetime<br>N<br>체크아웃시간 _ 분<br>YYYY-MM-DD HH:MI<br>8-8<br>PAYMENT_NUM<br>int(11)<br>N<br>소비인원<br>단위 : 명<br>8-9<br>BRNO<br>varchar(10)<br>N<br>사업자등록번호<br>8-10<br>STORE_NM<br>varchar(255)<br>N<br>상호명<br>8-11<br>ROAD_NM_ADDR<br>varchar(255)<br>N<br>도로명주소<br>8-12<br>LOTNO_ADDR<br>varchar(255)<br>N<br>지번주소<br>8-13<br>ROAD_NM_CD<br>varchar(255)<br>N<br>도로명코드<br>8-14<br>LOTNO_CD<br>varchar(255)<br>N<br>지번코드<br>8-15<br>PAYMENT_DT<br>datetime<br>N<br>결제일시 _ 분<br>YYYY-MM-DD HH:MI<br>8-16<br>PAYMENT_MTHD_SE<br>varchar(255)<br>N<br>결제방식구분<br>[1~5]<br>코드 ‘ PAY ’<br>8-17<br>PAYMENT_AMT_WON<br>int(11)<br>N<br>결제금액 _ 원<br>8-18<br>PAYMENT_ETC<br>text<br>N<br>소비내역 _ 기타<br>9<br>TN_ACTIVITY_HIS<br>TABEL<br>활동내역<br>9-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>9-2<br>VISIT_AREA_ID<br>varchar(150)<br>Y<br>방문지 ID<br>9-3<br>ACTIVITY_TYPE_CD<br>varchar(150)<br>Y<br>활동유형코드<br>[1~7,99]<br>코드 ‘ ACT ’<br>9-4<br>ACTIVITY_TYPE_SEQ<br>int(11)<br>Y<br>활동유형순번<br>9-5<br>ACTIVITY_ETC<br>varchar(255)<br>N<br>활동 _ 기타<br>직접입력<br>9-6<br>ACTIVITY_DTL<br>varchar(400)<br>N<br>세부내역<br>9-7<br>RSVT_YN<br>char(3)<br>N<br>예약여부<br>9-8<br>EXPND_SE<br>varchar(255)<br>N<br>지출구분<br>[1~5]<br>코드 ‘ EXP ’<br>9-9<br>ADMISSION_SE<br>varchar(255)<br>N<br>입장료구분<br>[1~2]<br>코드 ‘ AMS ’<br>10<br>TN_ADV_CONSUME_HIS<br>TABEL<br>사전소비내역<br>10-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>10-2<br>ADV_NM<br>varchar(255)<br>Y<br>구매내역<br>10-3<br>ADV_SEQ<br>int(11)<br>Y<br>구매순번<br>10-4<br>PAYMENT_NUM<br>int(11)<br>N<br>소비인원<br>단위 : 명<br>10-5<br>BRNO<br>varchar(10)<br>N<br>사업자등록번호<br>10-6<br>STORE_NM<br>varchar(255)<br>N<br>상호명<br>10-7<br>ROAD_NM_ADDR<br>varchar(255)<br>N<br>도로명주소<br>10-8<br>LOTNO_ADDR<br>varchar(255)<br>N<br>지번주소<br>10-9<br>ROAD_NM_CD<br>varchar(255)<br>N<br>도로명코드<br>10-10<br>LOTNO_CD<br>varchar(255)<br>N<br>지번코드<br>10-11<br>PAYMENT_DT<br>datetime<br>N<br>결제일시 _ 분<br>YYYY-MM-DD HH:MI<br>10-12<br>PAYMENT_MTHD_SE<br>varchar(255)<br>N<br>결제방식구분<br>[1~5]<br>코드 ‘ PAY ’<br>10-13<br>PAYMENT_AMT_WON<br>int(11)<br>N<br>결제금액 _ 원<br>10-14<br>PAYMENT_ETC<br>text<br>N<br>소비내역 _ 기타<br>10-15<br>SGG_CD<br>char(50)<br>N<br>시군구코드<br>tc_sgg 참조<br>11<br>TN_ACTIVITY_CONSUME_HI S<br>TABEL<br>활동소비내역<br>11-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>11-2<br>VISIT_AREA_ID<br>varchar(150)<br>Y<br>방문지 ID<br>11-3<br>ACTIVITY_TYPE_CD<br>varchar(150)<br>Y<br>활동유형코드<br>[1~7,99]<br>코드 ‘ ACT ’<br>11-4<br>ACTIVITY_TYPE_SEQ<br>int(11)<br>Y<br>활동유형순번<br>11-5<br>CONSUME_HIS_SEQ<br>int(11)<br>Y<br>소비내역순번<br>11-6<br>CONSUME_HIS_SNO<br>int(11)<br>Y<br>소비내역부번<br>11-7<br>PAYMENT_NUM<br>int(11)<br>N<br>소비인원<br>단위 : 명<br>11-8<br>BRNO<br>varchar(10)<br>N<br>사업자등록번호<br>11-9<br>STORE_NM<br>varchar(255)<br>N<br>상호명<br>11-10<br>ROAD_NM_ADDR<br>varchar(255)<br>N<br>도로명주소<br>11-11<br>LOTNO_ADDR<br>varchar(255)<br>N<br>지번주소<br>11-12<br>ROAD_NM_CD<br>varchar(255)<br>N<br>도로명코드<br>11-13<br>LOTNO_CD<br>varchar(255)<br>N<br>지번코드<br>11-14<br>PAYMENT_DT<br>datetime<br>N<br>결제일시 _ 분<br>YYYY-MM-DD HH:MI<br>11-15<br>PAYMENT_MTHD_SE<br>varchar(255)<br>N<br>결제방식구분<br>[1~5]<br>코드 ‘ PAY ’<br>11-16<br>PAYMENT_AMT_WON<br>int(11)<br>N<br>결제금액 _ 원<br>11-17<br>PAYMENT_ETC<br>text<br>N<br>소비내역 _ 기타<br>11-18<br>SGG_CD<br>char(50)<br>N<br>시군구코드<br>tc_sgg 참조<br>12<br>TN_VISIT_AREA_INFO<br>TABEL<br>방문지정보<br>12-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>12-2<br>VISIT_AREA_ID<br>varchar(150)<br>Y<br>방문지 ID<br>12-3<br>VISIT_ORDER<br>int(11)<br>Y<br>진행순서<br>12-4<br>VISIT_AREA_NM<br>varchar(255)<br>Y<br>방문지명<br>12-5<br>VISIT_START_YMD<br>date<br>N<br>방문시작일자<br>YYYY-MM-DD<br>12-6<br>VISIT_END_YMD<br>date<br>N<br>방문종료일자<br>YYYY-MM-DD<br>12-7<br>ROAD_NM_ADDR<br>varchar(255)<br>N<br>도로명주소<br>12-8<br>LOTNO_ADDR<br>varchar(255)<br>N<br>지번주소<br>12-9<br>X_COORD<br>varchar(255)<br>N<br>X 좌표<br>12-10<br>Y_COORD<br>varchar(255)<br>N<br>Y 좌표<br>12-11<br>ROAD_NM_CD<br>varchar(255)<br>N<br>도로명코드<br>12-12<br>LOTNO_CD<br>varchar(255)<br>N<br>지번코드<br>12-13<br>POI_ID<br>varchar(255)<br>N<br>POI ID<br>12-14<br>POI_NM<br>varchar(255)<br>N<br>POI 명<br>12-15<br>RESIDENCE_TIME_MIN<br>int(11)<br>N<br>체류시간 _ 분<br>단위 : 분<br>12-16<br>VISIT_AREA_TYPE_CD<br>varchar(255)<br>N<br>방문지유형코드<br>[1~13, 21~24]<br>코드 ‘ VIS ’<br>12-17<br>REVISIT_YN<br>varchar(255)<br>N<br>재방문여부<br>12-18<br>VISIT_CHC_REASON_CD<br>varchar(255)<br>N<br>방문선택이유코드<br>[1~11]<br>코드 ‘ REN ’<br>12-19<br>LODGING_TYPE_CD<br>varchar(255)<br>N<br>숙소유형코드<br>[1~12]<br>코드 ‘ HTY ’<br>12-20<br>DGSTFN<br>varchar(255)<br>N<br>만족도<br>[1~5]<br>코드 ‘ DGS ’<br>12-21<br>REVISIT_INTENTION<br>varchar(255)<br>N<br>재방문의향<br>[1~5]<br>코드 ‘ REP ’<br>12-22<br>RCMDTN_INTENTION<br>varchar(255)<br>N<br>추천의향<br>[1~5]<br>코드 ‘ REC ’<br>12-23<br>SGG_CD<br>char(50)<br>N<br>시군구코드<br>tc_sgg 참조<br>13<br>TN_TOUR_PHOTO<br>TABEL<br>관광사진<br>13-1<br>TRAVEL_ID<br>varchar(50)<br>Y<br>여행 ID<br>13-2<br>VISIT_AREA_ID<br>varchar(150)<br>Y<br>방문지 ID<br>13-3<br>TOUR_PHOTO_SEQ<br>int(11)<br>Y<br>관광사진순번<br>13-4<br>PHOTO_FILE_ID<br>varchar(255)<br>N<br>사진파일 ID<br>13-5<br>PHOTO_FILE_NM<br>varchar(255)<br>N<br>사진파일명<br>13-6<br>PHOTO_FILE_FRMAT<br>varchar(50)<br>N<br>사진파일포맷<br>JPG<br>13-7<br>PHOTO_FILE_DT<br>datetime<br>N<br>사진파일촬영일시<br>YYYY-MM-DD HH:MI:SS<br>13-8<br>PHOTO_FILE_SAVE_PATH<br>varchar(150)<br>N<br>사진파일저장경로<br>13-9<br>PHOTO_FILE_RESOLUTION<br>varchar(255)<br>N<br>사진파일해상도<br>13-10<br>PHOTO_FILE_X_COORD<br>varchar(255)<br>N<br>사진파일 X 좌표<br>13-11<br>PHOTO_FILE_Y_COORD<br>varchar(255)<br>N<br>사진파일 Y 좌표<br>13-12<br>VISIT_AREA_NM<br>varchar(255)<br>N<br>방문지명<br>14<br>TC_SGG<br>TABEL<br>시군구<br>14-1<br>SGG_CD<br>char(50)<br>Y<br>전체코드<br>14-2<br>SGG_CD1<br>char(10)<br>N<br>시도코드<br>14-3<br>SGG_CD2<br>char(10)<br>N<br>시군구코드<br>14-4<br>SGG_CD3<br>char(10)<br>N<br>읍면동코드<br>14-5<br>SGG_CD4<br>char(10)<br>N<br>리코드<br>14-6<br>SIDO_NM<br>varchar(100)<br>Y<br>시도명<br>14-7<br>SGG_NM<br>varchar(100)<br>N<br>시군구명<br>14-8<br>DONG_NM<br>varchar(100)<br>N<br>읍면동<br>14-9<br>RI_NM<br>varchar(100)<br>N<br>리<br>15<br>TC_CODEA<br>TABEL<br>코드 A<br>15-1<br>idx<br>int(11)<br>Y<br>idx<br>15-2<br>cd_a<br>varchar(10)<br>Y<br>코드 A<br>15-3<br>cd_nm<br>varchar(255)<br>Y<br>코드 A 명<br>15-4<br>cd_memo<br>varchar(255)<br>N<br>메모<br>15-5<br>cd_memo2<br>varchar(255)<br>N<br>메모2<br>15-6<br>del_flag<br>char(1)<br>Y<br>숨김여부<br>15-7<br>order_num<br>int(11)<br>Y<br>순서<br>15-8<br>perm_write<br>ENUM('Y','N)<br>Y<br>등록가능여부<br>[Y, N]<br>15-9<br>perm_edit<br>ENUM('Y','N)<br>Y<br>수정가능여부<br>[Y, N]<br>15-10<br>perm_delete<br>ENUM('Y','N)<br>Y<br>삭제가능여부<br>[Y, N]<br>15-11<br>ins_dt<br>datetime<br>Y<br>등록일<br>YYYY-MM-DD HH:MI:SS<br>15-12<br>edit_dt<br>datetime<br>N<br>수정일<br>YYYY-MM-DD HH:MI:SS<br>16<br>TC_CODEB<br>TABEL<br>코드 B<br>16-1<br>idx<br>int(11)<br>Y<br>idx<br>16-2<br>cd_a<br>varchar(10)<br>Y<br>코드 A<br>16-3<br>cd_b<br>varchar(8)<br>Y<br>코드 B<br>16-4<br>cd_nm<br>varchar(255)<br>Y<br>코드 B 명<br>16-5<br>cd_memo<br>varchar(255)<br>N<br>메모<br>16-6<br>cd_memo2<br>varchar(255)<br>N<br>메모2<br>16-7<br>del_flag<br>char(1)<br>Y<br>숨김여부<br>16-8<br>order_num<br>int(11)<br>Y<br>순서<br>16-9<br>ins_dt<br>datetime<br>Y<br>등록일<br>YYYY-MM-DD HH:MI:SS<br>16-10<br>edit_dt<br>datetime<br>N<br>수정일<br>YYYY-MM-DD HH:MI:SS<br>- 이미지캡션 데이터 구성 ( JSON 메타데이터)<br>구분<br>속성명<br>타입<br>필수 여부<br>설명<br>범위<br>비고<br>1<br>info<br>Object<br>데이터셋 정보<br>1-1<br>DATASET_NM<br>string<br>Y<br>데이터셋명<br>1-2<br>DATASET_DETAIL<br>string<br>Y<br>상세설명<br>2<br>images<br>Object<br>이미지정보<br>2-1<br>PHOTO_FILE_ID<br>string<br>Y<br>파일아이디<br>2-2<br>PHOTO_FILE_NM<br>string<br>Y<br>파일명<br>2-3<br>PHOTO_FILE_SAVE_PATH<br>string<br>Y<br>저장경로<br>2-4<br>PHOTO_FILE_RESOLUTION<br>string<br>Y<br>해상도<br>2-5<br>PHOTO_FILE_DT<br>string<br>Y<br>촬영일자<br>YYYY-MM-D D HH:MI:SS<br>2-6<br>PHOTO_FILE_X_COORD<br>string<br>Y<br>촬영위치( X)<br>2-7<br>PHOTO_FILE_Y_COORD<br>string<br>Y<br>촬영위치( Y)<br>2-8<br>VISIT_AREA_NM<br>string<br>N<br>방문지정보<br>2-9<br>LANDMARK<br>string<br>N<br>랜드마크( POI)<br>3<br>caption<br>Object<br>캡션정보<br>3-1<br>IMG_CAPTION<br>string<br>Y<br>이미지캡션 내용<br>3-2<br>TOKEN<br>int(11)<br>Y<br>토큰<br>3-3<br>TIME_STAMP<br>varchar(150)<br>N<br>촬영일자<br>YYYY-MM-D D HH:MI:SS<br>4<br>licenses<br>Object<br>라이센스정보<br>3-1<br>ID<br>varchar(50)<br>Y<br>ID<br>3-2<br>NAME<br>varchar(50)<br>Y<br>구축기관
- 수행기관 담당자 및 연락처: `[원문 연락정보 생략]`
- **참여기관**: 기관명<br>담당업무<br>기관명<br>담당업무
- **㈜ 데이터웨이**: 사업관리 데이터검수<br>㈜ 에이드리븐<br>여행자 모집/관리
- **㈜ 케이스탯 리서치**: 여행자운영 데이터수집<br>㈜ 지디에스 컨설팅그룹<br>데이터가공
- **㈜ 올포랜드**: 공간데이터 정제/가공<br>와이비에스에듀 사회적협동조합<br>데이터가공
- **고려대학교 산학협력단**: 검증용 AI 알고리즘

## 파일 구성 및 구축 규모

| 분류 | 파일구성 | 설명 | 구축 규모 |
| --- | --- | --- | --- |
| photo | PHOTO | 여행객 직접 촬영한 관광사진 | 18,131장 |
| CSV | TN_TRAVELLER_MASTER | 여행객에 대한 정보 | 3,200set |
|  | TN_TRAVEL | 여행 기본 정보 | 3,200set |
|  | TN_COMPANION_INFO | 동반자 정보 | 3,200set |
|  | TN_MOVE_HIS | 여행기간동안 이동한 내역 | 3,200set |
|  | TN_MVMN_CONSUME_HIS | 교통비 | 3,200set |
|  | TN_LODGE_CONSUME_HIS | 숙박비 | 3,200set |
|  | TN_ADV_CONSUME_HIS | 여행가기전에 소비내역 | 3,200set |
|  | TN_VISIT_AREA_INFO | 여행 방문지정보 | 3,200set |
|  | TN_TOUR_PHOTO | 여행중 촬영한 여행 사진 | 3,200set |
|  | TN_ACTIVITY_HIS | 여행기간동안 활동한 내역 | 3,200set |
|  | TN_ACTIVITY_CONSUME_HIS | 여행기간동안 소비한 내역 | 3,200set |
|  | TC_SGG | 시군구 코드 테이블 정의 | 1개 |
|  | TC_CODEA | 코드 리스트 테이블 정의 | 1개 |
|  | TC_CODEB | 코드 상세 테이블 정의 | 1개 |
| GPS | TN_GPS_COORD | 이동경로 GPS 좌표 정보 | 3,200개 |
| 서브라벨링 | JSON | 이미지캡션 라벨링데이터 | 3,059개 |
|  | PHOTO | 이미지캡션 이미지데이터 | 3,059장 |
| other | TN_POI_MASTER | POI 정보 | 1개 |

## 데이터 분포

|  |  | 동부권 |  |
| --- | --- | --- | --- |
| 성별 | 남 | 1,340 | 41.88% |
|  | 여 | 1,860 | 58.12% |
|  | 합계 | 3,200 | 100% |
| 연령별 | 20대 | 1,056 | 33.00% |
|  | 30대 | 968 | 30.25% |
|  | 40대 | 681 | 21.28% |
|  | 50대 ↑ | 495 | 15.47% |
|  | 합계 | 3,200 | 100% |
| 여행 기간별 | 당일 | 1,478 | 46.19% |
|  | 1박2일 | 1,349 | 42.16% |
|  | 2박3일 ↑ | 373 | 11.66% |
|  | 합계 | 3,200 | 100% |

## CSV 파일명 구성

| 예시 | 세부 구성 설명 |
| --- | --- |
| tn_activity_consume_his_ 활동소비내역 _F.csv<br>{tn_activity_consume_his}_{ 활동소비내역 }_{F}.csv | { 영문테이블명 }_{ 한글테이블명 }_{ 권역정보 }.csv<br>※ 권역정보<br>E : 수도권<br>F : 동부권<br>G : 서부권<br>H : 제주도 및 도서지역 |

## GPS 파일명 구성

| 예시 | 세부 구성 설명 |
| --- | --- |
| tn_gps_coord_<여행객 ID>.csv | {tn_gps_coord}_{<여행객 ID>}.csv<br>개별 파일 예시는 식별자 보호를 위해 생략 |

## 관광사진 파일명 구성

| 예시 | 세부 구성 설명 |
| --- | --- |
| <여행객 ID 및 순번으로 된 예시 파일명 생략> | { 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg<br>여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>여행자 계정<br>여행일<br>순번<br>경로<br>번호<br>사진구 분<br>활동번호<br>사진번호<br>(7)<br>(2)<br>(3)<br>(1)<br>(2)<br>(2)<br>권역 + 6자리<br>1일 ~n 일<br>001 ~ 099<br>P= 관광<br>사진<br>사진 구분 P 이면, 00값 입력<br>사진번호 |

## 관광사진 파일명 구성 요소

| 여행자 계정 | 여행일<br>순번 | 경로<br>번호 | 사진구 분 | 활동번호 | 사진번호 |
| --- | --- | --- | --- | --- | --- |
| (7) | (2) | (3) | (1) | (2) | (2) |
| 권역 + 6자리 | 1일 ~n 일 | 001 ~ 099 | P= 관광<br>사진 | 사진 구분 P 이면, 00값 입력 | 사진번호 |

## 캡션 JSON 파일명 구성

| 예시 | 세부 구성 설명 |
| --- | --- |
| <여행객 ID 및 순번으로 된 예시 파일명 생략> | { 여행자계정 }{ 여행일순번 }{ 경로번호 }{ 사진구분 }{ 활동번호 }{ 사진번호 }.jpg<br>여행자 계정 여행일 순번 경로 번호 사진구 분 활동번호 사진번호 (7) (2) (3) (1) (2) (2) 권역 + 6자리 1일 ~n 일 001 ~ 099 P= 관광 사진 사진 구분 P 이면, 00값 입력 사진번호<br>여행자 계정<br>여행일<br>순번<br>경로<br>번호<br>사진구 분<br>활동번호<br>사진번호<br>(7)<br>(2)<br>(3)<br>(1)<br>(2)<br>(2)<br>권역 + 6자리<br>1일 ~n 일<br>001 ~ 099<br>P= 관광<br>사진<br>사진 구분 P 이면, 00값 입력<br>사진번호 |

## 캡션 JSON 파일명 구성 요소

| 여행자 계정 | 여행일<br>순번 | 경로<br>번호 | 사진구 분 | 활동번호 | 사진번호 |
| --- | --- | --- | --- | --- | --- |
| (7) | (2) | (3) | (1) | (2) | (2) |
| 권역 + 6자리 | 1일 ~n 일 | 001 ~ 099 | P= 관광<br>사진 | 사진 구분 P 이면, 00값 입력 | 사진번호 |

## 디렉터리별 파일 목록

| 구분 | 파일유형 | 파일명 |
| --- | --- | --- |
| 원천데이터 | photo | 여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조) |
| 라벨링데이터 | csv | c_codea_ 코드 A.csv<br>tc_codeb_ 코드 B.csv<br>tc_sgg_ 시군구코드. csv<br>tn_activity_consume_his_ 활동소비내역 _F.csv<br>tn_activity_his_ 활동내역 _F.csv<br>tn_adv_consume_his_ 사전소비내역 _F.csv<br>tn_companion_info_ 동반자정보 _F.csv<br>tn_lodge_consume_his_ 숙박소비내역 _F.csv<br>tn_move_his_ 이동내역 _F.csv<br>tn_mvmn_consume_his_ 이동수단소비내역 _F.csv<br>tn_tour_photo_ 관광사진 _F.csv<br>tn_traveller_master_ 여행객 Master_F.csv<br>tn_travel_ 여행 _F.csv<br>tn_visit_area_info_ 방문지정보 _F.csv |
|  | gps_data | n_gps_coord_{}.csv (3200 개) ( {} = 여행객 ID ) |
| 서브라벨링 | json | 여행객 ID + 순번. json ( 파일명 구성 및 세부 구성 정보 참조) |
|  | photo | 여행객 ID + 순번. jpg ( 파일명 구성 및 세부 구성 정보 참조) |
| other | 메타데이터 | tn_poi_master_POIMaster.csv |

## 테이블 정의

| 한글테이블명 | 영문테이블명 | 설명 |
| --- | --- | --- |
| 여행객 Master | TN_TRAVELLER_MASTER | 여행객에 대한 정보 |
| POI Master | TN_POI_MASTER | POI 정보 |
| 여행 | TN_TRAVEL | 여행 기본 정보 |
| 동반자정보 | TN_COMPANION_INFO | 동반자 정보 |
| 이동내역 | TN_MOVE_HIS | 여행기간동안 이동한 내역 |
| GPS 좌표 | TN_GPS_COORD | 이동한 GPS 좌표 정보 |
| 이동수단소비내역 | TN_MVMN_CONSUME_HIS | 교통비 |
| 숙박소비내역 | TN_LODGE_CONSUME_HIS | 숙박비 |
| 사전소비내역 | TN_ADV_CONSUME_HIS | 여행가기전에 소비내역 |
| 방문지정보 | TN_VISIT_AREA_INFO | 여행 방문지정보 |
| 관광사진 | TN_TOUR_PHOTO | 여행중 촬영한 여행 사진 |
| 활동내역 | TN_ACTIVITY_HIS | 여행기간동안 활동한 내역 |
| 활동소비내역 | TN_ACTIVITY_CONSUME_HIS | 여행기간동안 소비한 내역 |
| 시군구 | TC_SGG | 시군구 코드 테이블 |
| 코드 A | TC_CODEA | 코드 리스트 테이블 |
| 코드 B | TC_CODEB | 코드 상세 테이블 |

## CSV 필드 사전

| 구분 |  | 속성명 | 타입 | 필수 여부 | 설명 | 범위 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  | TN_TRAVELLER_MASTER | TABEL |  | 여행객 Master |  |  |
|  | 1-1 | TRAVELER_ID | varchar(255) | Y | 여행객 ID |  |  |
|  | 1-2 | RESIDENCE_SGG_CODE | varchar(50) | N | 거주지시군구코드 |  | tc_sgg 참조 |
|  | 1-3 | GENDER | varchar(50) | N | 성별 |  |  |
|  | 1-4 | AGE_GRP | varchar(50) | N | 연령대 |  |  |
|  | 1-5 | EDU_NM | varchar(50) | N | 최종학력 | [1~8] | 코드 ‘ EDU ’ |
|  | 1-6 | EDU_FNSH_SE | varchar(50) | N | 최종학력이수여부 | [1~5] | 코드 ‘ EFS ’ |
|  | 1-7 | MARR_STTS | varchar(50) | N | 혼인상태 | [1~5] | 코드 ‘ MAR ’ |
|  | 1-8 | FAMILY_MEMB | varchar(255) | N | 가족현황 |  |  |
|  | 1-9 | JOB_NM | varchar(100) | N | 직업 | [1~13] | 코드 ‘ JOB ’ |
|  | 1-10 | JOB_ETC | varchar(50) | N | 직업 _ 기타 | [1~3] | 코드 ‘ JOE ’ |
|  | 1-11 | INCOME | varchar(50) | N | 본인소득 | [1~12] | 코드 ‘ INC ’ |
|  | 1-12 | HOUSE_INCOME | varchar(50) | N | 가구소득 | [1~12] | 코드 ‘ INC ’ |
|  | 1-13 | TRAVEL_TERM | varchar(50) | N | 여행빈도 _ 기간 | [1~4] | 코드 ‘ TTM ’ |
|  | 1-14 | TRAVEL_NUM | int(11) | N | 여행빈도 |  |  |
|  | 1-15 | TRAVEL_LIKE_SIDO_1 | varchar(50) | N | 선호여행 _ 시도 _1 |  | tc_sgg 참조 |
|  | 1-16 | TRAVEL_LIKE_SGG_1 | varchar(50) | N | 선호여행 _ 시군구 _1 |  | tc_sgg 참조 |
|  | 1-17 | TRAVEL_LIKE_SIDO_2 | varchar(50) | N | 선호여행 _ 시도 _2 |  | tc_sgg 참조 |
|  | 1-18 | TRAVEL_LIKE_SGG_2 | varchar(50) | N | 선호여행 _ 시군구 _2 |  | tc_sgg 참조 |
|  | 1-19 | TRAVEL_LIKE_SIDO_3 | varchar(50) | N | 선호여행 _ 시도 _3 |  | tc_sgg 참조 |
|  | 1-20 | TRAVEL_LIKE_SGG_3 | varchar(50) | N | 선호여행 _ 시군구 _3 |  | tc_sgg 참조 |
|  | 1-21 | TRAVEL_STYL_1 | varchar(50) | N | 여행스타일 _1 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-22 | TRAVEL_STYL_2 | varchar(50) | N | 여행스타일 _2 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-23 | TRAVEL_STYL_3 | varchar(50) | N | 여행스타일 _3 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-24 | TRAVEL_STYL_4 | varchar(50) | N | 여행스타일 _4 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-25 | TRAVEL_STYL_5 | varchar(50) | N | 여행스타일 _5 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-26 | TRAVEL_STYL_6 | varchar(50) | N | 여행스타일 _6 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-27 | TRAVEL_STYL_7 | varchar(50) | N | 여행스타일 _7 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-28 | TRAVEL_STYL_8 | varchar(50) | N | 여행스타일 _8 | [1~7] | 코드 ‘ TSY ’ |
|  | 1-29 | TRAVEL_STATUS_RESIDEN CE | varchar(50) | N | 여행현황 _ 거주지 |  |  |
|  | 1-30 | TRAVEL_STATUS_DESTINA TION | varchar(50) | N | 여행현황 _ 목적지 |  |  |
|  | 1-31 | TRAVEL_STATUS_ACCOMP ANY | varchar(50) | N | 여행현황 _ 동반현황 |  |  |
|  | 1-32 | TRAVEL_STATUS_YMD | varchar(50) | N | 여행현황 _ 여행일자 |  |  |
|  | 1-33 | TRAVEL_MOTIVE_1 | varchar(50) | N | 여행동기 _1 | [1~10] | 코드 ‘ TMT ’ |
|  | 1-34 | TRAVEL_MOTIVE_2 | varchar(50) | N | 여행동기 _2 | [1~10] | 코드 ‘ TMT ’ |
|  | 1-35 | TRAVEL_MOTIVE_3 | varchar(50) | N | 여행동기 _3 | [1~10] | 코드 ‘ TMT ’ |
|  | 1-36 | TRAVEL_COMPANIONS_NU M | int(5) | N | 여행동반자수 |  |  |
| 2 |  | TN_POI_MASTER | TABEL |  | POI Master |  |  |
|  | 2-1 | POI_ID | varchar(255) | Y | POI ID |  |  |
|  | 2-2 | POI_NM | varchar(255) | N | POI 명 |  |  |
|  | 2-3 | BRNO | varchar(255) | N | 사업자등록번호 |  |  |
|  | 2-4 | SGG_CD | varchar(255) | N | 시군구코드 |  |  |
|  | 2-5 | ROAD_NM_ADDR | varchar(255) | N | 도로명주소 |  |  |
|  | 2-6 | LOTNO_ADDR | varchar(255) | N | 지번주소 |  |  |
|  | 2-7 | ASORT_LCLASDC | varchar(255) | N | 종별 _ 대분류 |  |  |
|  | 2-8 | ASORT_MLSFCDC | varchar(255) | N | 종별 _ 중분류 |  |  |
|  | 2-9 | ASORT_SDASDC | varchar(255) | N | 종별 _ 소분류 |  |  |
|  | 2-10 | X_COORD | varchar(255) | N | X 좌표 |  |  |
|  | 2-11 | Y_COORD | varchar(255) | N | Y 좌표 |  |  |
|  | 2-12 | ROAD_NM_CD | varchar(255) | N | 도로명코드 |  |  |
|  | 2-13 | LOTNO_CD | varchar(255) | N | 지번코드 |  |  |
| 3 |  | TN_COMPANION_INFO | TABEL |  | 동반자정보 |  |  |
|  | 3-1 | COMPANION_SEQ | int(11) | Y | 동반자순번 |  |  |
|  | 3-2 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 3-3 | REL_CD | varchar(150) | N | 동반자관계코드 | [1~11] | 코드 ‘ TCR ’ |
|  | 3-4 | COMPANION_GENDER | varchar(50) | N | 동반자성별 | [1~2] | 코드 ‘ GEN ’ |
|  | 3-5 | COMPANION_AGE_GRP | varchar(50) | N | 동반자연령대 | [1~8] | 코드 ‘ AGE ’ |
|  | 3-6 | COMPANION_SITUATION | varchar(50) | N | 동반자동반상황 | [1~3] | 코드 ‘ CST ’ |
| 4 |  | TN_TRAVEL | TABEL |  | 여행 |  |  |
|  | 4-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 4-2 | TRAVEL_NM | varchar(255) | N | 여행명 |  |  |
|  | 4-3 | TRAVELER_ID | varchar(255) | Y | 여행객 ID |  |  |
|  | 4-4 | TRAVEL_PURPOSE | varchar(150) | N | 여행목적 |  | 코드 ‘ MIS ’ |
|  | 4-5 | TRAVEL_START_YMD | date | N | 여행시작일자 |  | YYYY-MM-DD |
|  | 4-6 | TRAVEL_END_YMD | date | N | 여행종료일자 |  | YYYY-MM-DD |
|  | 4-7 | MVMN_NM | varchar(100) | N | 주요이동수단 |  |  |
|  | 4-8 | TRAVEL_PERSONA | varchar(150) | Y | 페르소나 |  |  |
|  | 4-9 | TRAVEL_MISSION | varchar(150) | N | 개별미션 | [1~13, 21~28] | 코드 ‘ MIS ’ |
|  | 4-10 | TRAVEL_MISSION_CHECK | char(50) | N | 미션우선도 | [1~13 ,21~28] | 코드 ‘ MIS ’ |
| 5 |  | TN_MOVE_HIS | TABEL |  | 이동내역 |  |  |
|  | 5-1 | TRIP_ID | varchar(150) | Y | Trip ID |  |  |
|  | 5-2 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 5-3 | START_VISIT_AREA_ID | varchar(100) | N | 출발 방문지 ID |  |  |
|  | 5-4 | END_VISIT_AREA_ID | varchar(100) | N | 도착 방문지 ID |  |  |
|  | 5-5 | START_DT_MIN | datetime | N | 출발시간 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 5-6 | END_DT_MIN | datetime | N | 도착시간 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 5-7 | MVMN_CD_1 | varchar(255) | N | 이동방법코드 _1 | [1~16, 50] | 코드 ‘ MOV ’ |
|  | 5-8 | MVMN_CD_2 | varchar(255) | N | 이동방법코드 _2 | [1~16, 50] | 코드 ‘ MOV ’ |
| 6 |  | TN_GPS_COORD | TABEL |  | GPS 좌표 |  |  |
|  | 6-1 | MOBILE_NUM_ID | varchar(50) | Y | 단말기번호 ID |  |  |
|  | 6-2 | X_COORD | varchar(20) | Y | X 좌표 |  |  |
|  | 6-3 | Y_COORD | varchar(20) | Y | Y 좌표 |  |  |
|  | 6-4 | DT_MIN | datetime | Y | 시간 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 6-5 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
| 7 |  | TN_MVMN_CONSUME_HIS | TABEL |  | 이동수단소비내역 |  |  |
|  | 7-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 7-2 | MVMN_SE | varchar(150) | Y | 이동수단구분 | [1~16, 50] | 코드 ‘ MOV ’ |
|  | 7-3 | PAYMENT_SE | varchar(150) | Y | 이용경비구분 |  |  |
|  | 7-4 | PAYMENT_SEQ | int(11) | Y | 이용경비순번 |  |  |
|  | 7-5 | MVMN_SE_NM | varchar(255) | N | 이동수단구분명 |  |  |
|  | 7-6 | RSVT_YN | char(1) | N | 예약여부 |  | “ Y ” or “ N ” |
|  | 7-7 | PAYMENT_NUM | int(11) | N | 포함인원 |  |  |
|  | 7-8 | BRNO | varchar(10) | N | 사업자등록번호 |  |  |
|  | 7-9 | STORE_NM | varchar(255) | N | 상호명 |  |  |
|  | 7-10 | PAYMENT_DT | datetime | N | 결제일시 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 7-11 | PAYMENT_MTHD_SE | varchar(255) | N | 결제방식구분 | [1~5] | 코드 ‘ PAY ’ |
|  | 7-12 | PAYMENT_AMT_WON | int(11) | N | 결제금액 _ 원 |  |  |
|  | 7-13 | PAYMENT_ETC | text | N | 소비내역 _ 기타 |  |  |
| 8 |  | TN_LODGE_CONSUME_HIS | TABEL |  | 숙박소비내역 |  |  |
|  | 8-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 8-2 | LODGING_NM | varchar(255) | Y | 숙소명 |  |  |
|  | 8-3 | LODGE_PAYMENT_SEQ | int(11) | Y | 숙박경비순번 |  |  |
|  | 8-4 | LODGING_TYPE_CD | char(10) | N | 숙소유형코드 | [1~12] | 코드 ‘ HTY ’ |
|  | 8-5 | RSVT_YN | char(3) | N | 예약여부 |  |  |
|  | 8-6 | CHK_IN_DT_MIN | datetime | N | 체크인시간 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 8-7 | CHK_OUT_DT_MIN | datetime | N | 체크아웃시간 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 8-8 | PAYMENT_NUM | int(11) | N | 소비인원 |  | 단위 : 명 |
|  | 8-9 | BRNO | varchar(10) | N | 사업자등록번호 |  |  |
|  | 8-10 | STORE_NM | varchar(255) | N | 상호명 |  |  |
|  | 8-11 | ROAD_NM_ADDR | varchar(255) | N | 도로명주소 |  |  |
|  | 8-12 | LOTNO_ADDR | varchar(255) | N | 지번주소 |  |  |
|  | 8-13 | ROAD_NM_CD | varchar(255) | N | 도로명코드 |  |  |
|  | 8-14 | LOTNO_CD | varchar(255) | N | 지번코드 |  |  |
|  | 8-15 | PAYMENT_DT | datetime | N | 결제일시 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 8-16 | PAYMENT_MTHD_SE | varchar(255) | N | 결제방식구분 | [1~5] | 코드 ‘ PAY ’ |
|  | 8-17 | PAYMENT_AMT_WON | int(11) | N | 결제금액 _ 원 |  |  |
|  | 8-18 | PAYMENT_ETC | text | N | 소비내역 _ 기타 |  |  |
| 9 |  | TN_ACTIVITY_HIS | TABEL |  | 활동내역 |  |  |
|  | 9-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 9-2 | VISIT_AREA_ID | varchar(150) | Y | 방문지 ID |  |  |
|  | 9-3 | ACTIVITY_TYPE_CD | varchar(150) | Y | 활동유형코드 | [1~7,99] | 코드 ‘ ACT ’ |
|  | 9-4 | ACTIVITY_TYPE_SEQ | int(11) | Y | 활동유형순번 |  |  |
|  | 9-5 | ACTIVITY_ETC | varchar(255) | N | 활동 _ 기타 |  | 직접입력 |
|  | 9-6 | ACTIVITY_DTL | varchar(400) | N | 세부내역 |  |  |
|  | 9-7 | RSVT_YN | char(3) | N | 예약여부 |  |  |
|  | 9-8 | EXPND_SE | varchar(255) | N | 지출구분 | [1~5] | 코드 ‘ EXP ’ |
|  | 9-9 | ADMISSION_SE | varchar(255) | N | 입장료구분 | [1~2] | 코드 ‘ AMS ’ |
| 10 |  | TN_ADV_CONSUME_HIS | TABEL |  | 사전소비내역 |  |  |
|  | 10-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 10-2 | ADV_NM | varchar(255) | Y | 구매내역 |  |  |
|  | 10-3 | ADV_SEQ | int(11) | Y | 구매순번 |  |  |
|  | 10-4 | PAYMENT_NUM | int(11) | N | 소비인원 |  | 단위 : 명 |
|  | 10-5 | BRNO | varchar(10) | N | 사업자등록번호 |  |  |
|  | 10-6 | STORE_NM | varchar(255) | N | 상호명 |  |  |
|  | 10-7 | ROAD_NM_ADDR | varchar(255) | N | 도로명주소 |  |  |
|  | 10-8 | LOTNO_ADDR | varchar(255) | N | 지번주소 |  |  |
|  | 10-9 | ROAD_NM_CD | varchar(255) | N | 도로명코드 |  |  |
|  | 10-10 | LOTNO_CD | varchar(255) | N | 지번코드 |  |  |
|  | 10-11 | PAYMENT_DT | datetime | N | 결제일시 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 10-12 | PAYMENT_MTHD_SE | varchar(255) | N | 결제방식구분 | [1~5] | 코드 ‘ PAY ’ |
|  | 10-13 | PAYMENT_AMT_WON | int(11) | N | 결제금액 _ 원 |  |  |
|  | 10-14 | PAYMENT_ETC | text | N | 소비내역 _ 기타 |  |  |
|  | 10-15 | SGG_CD | char(50) | N | 시군구코드 |  | tc_sgg 참조 |
| 11 |  | TN_ACTIVITY_CONSUME_HI S | TABEL |  | 활동소비내역 |  |  |
|  | 11-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 11-2 | VISIT_AREA_ID | varchar(150) | Y | 방문지 ID |  |  |
|  | 11-3 | ACTIVITY_TYPE_CD | varchar(150) | Y | 활동유형코드 | [1~7,99] | 코드 ‘ ACT ’ |
|  | 11-4 | ACTIVITY_TYPE_SEQ | int(11) | Y | 활동유형순번 |  |  |
|  | 11-5 | CONSUME_HIS_SEQ | int(11) | Y | 소비내역순번 |  |  |
|  | 11-6 | CONSUME_HIS_SNO | int(11) | Y | 소비내역부번 |  |  |
|  | 11-7 | PAYMENT_NUM | int(11) | N | 소비인원 |  | 단위 : 명 |
|  | 11-8 | BRNO | varchar(10) | N | 사업자등록번호 |  |  |
|  | 11-9 | STORE_NM | varchar(255) | N | 상호명 |  |  |
|  | 11-10 | ROAD_NM_ADDR | varchar(255) | N | 도로명주소 |  |  |
|  | 11-11 | LOTNO_ADDR | varchar(255) | N | 지번주소 |  |  |
|  | 11-12 | ROAD_NM_CD | varchar(255) | N | 도로명코드 |  |  |
|  | 11-13 | LOTNO_CD | varchar(255) | N | 지번코드 |  |  |
|  | 11-14 | PAYMENT_DT | datetime | N | 결제일시 _ 분 |  | YYYY-MM-DD HH:MI |
|  | 11-15 | PAYMENT_MTHD_SE | varchar(255) | N | 결제방식구분 | [1~5] | 코드 ‘ PAY ’ |
|  | 11-16 | PAYMENT_AMT_WON | int(11) | N | 결제금액 _ 원 |  |  |
|  | 11-17 | PAYMENT_ETC | text | N | 소비내역 _ 기타 |  |  |
|  | 11-18 | SGG_CD | char(50) | N | 시군구코드 |  | tc_sgg 참조 |
| 12 |  | TN_VISIT_AREA_INFO | TABEL |  | 방문지정보 |  |  |
|  | 12-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 12-2 | VISIT_AREA_ID | varchar(150) | Y | 방문지 ID |  |  |
|  | 12-3 | VISIT_ORDER | int(11) | Y | 진행순서 |  |  |
|  | 12-4 | VISIT_AREA_NM | varchar(255) | Y | 방문지명 |  |  |
|  | 12-5 | VISIT_START_YMD | date | N | 방문시작일자 |  | YYYY-MM-DD |
|  | 12-6 | VISIT_END_YMD | date | N | 방문종료일자 |  | YYYY-MM-DD |
|  | 12-7 | ROAD_NM_ADDR | varchar(255) | N | 도로명주소 |  |  |
|  | 12-8 | LOTNO_ADDR | varchar(255) | N | 지번주소 |  |  |
|  | 12-9 | X_COORD | varchar(255) | N | X 좌표 |  |  |
|  | 12-10 | Y_COORD | varchar(255) | N | Y 좌표 |  |  |
|  | 12-11 | ROAD_NM_CD | varchar(255) | N | 도로명코드 |  |  |
|  | 12-12 | LOTNO_CD | varchar(255) | N | 지번코드 |  |  |
|  | 12-13 | POI_ID | varchar(255) | N | POI ID |  |  |
|  | 12-14 | POI_NM | varchar(255) | N | POI 명 |  |  |
|  | 12-15 | RESIDENCE_TIME_MIN | int(11) | N | 체류시간 _ 분 |  | 단위 : 분 |
|  | 12-16 | VISIT_AREA_TYPE_CD | varchar(255) | N | 방문지유형코드 | [1~13, 21~24] | 코드 ‘ VIS ’ |
|  | 12-17 | REVISIT_YN | varchar(255) | N | 재방문여부 |  |  |
|  | 12-18 | VISIT_CHC_REASON_CD | varchar(255) | N | 방문선택이유코드 | [1~11] | 코드 ‘ REN ’ |
|  | 12-19 | LODGING_TYPE_CD | varchar(255) | N | 숙소유형코드 | [1~12] | 코드 ‘ HTY ’ |
|  | 12-20 | DGSTFN | varchar(255) | N | 만족도 | [1~5] | 코드 ‘ DGS ’ |
|  | 12-21 | REVISIT_INTENTION | varchar(255) | N | 재방문의향 | [1~5] | 코드 ‘ REP ’ |
|  | 12-22 | RCMDTN_INTENTION | varchar(255) | N | 추천의향 | [1~5] | 코드 ‘ REC ’ |
|  | 12-23 | SGG_CD | char(50) | N | 시군구코드 |  | tc_sgg 참조 |
| 13 |  | TN_TOUR_PHOTO | TABEL |  | 관광사진 |  |  |
|  | 13-1 | TRAVEL_ID | varchar(50) | Y | 여행 ID |  |  |
|  | 13-2 | VISIT_AREA_ID | varchar(150) | Y | 방문지 ID |  |  |
|  | 13-3 | TOUR_PHOTO_SEQ | int(11) | Y | 관광사진순번 |  |  |
|  | 13-4 | PHOTO_FILE_ID | varchar(255) | N | 사진파일 ID |  |  |
|  | 13-5 | PHOTO_FILE_NM | varchar(255) | N | 사진파일명 |  |  |
|  | 13-6 | PHOTO_FILE_FRMAT | varchar(50) | N | 사진파일포맷 |  | JPG |
|  | 13-7 | PHOTO_FILE_DT | datetime | N | 사진파일촬영일시 |  | YYYY-MM-DD HH:MI:SS |
|  | 13-8 | PHOTO_FILE_SAVE_PATH | varchar(150) | N | 사진파일저장경로 |  |  |
|  | 13-9 | PHOTO_FILE_RESOLUTION | varchar(255) | N | 사진파일해상도 |  |  |
|  | 13-10 | PHOTO_FILE_X_COORD | varchar(255) | N | 사진파일 X 좌표 |  |  |
|  | 13-11 | PHOTO_FILE_Y_COORD | varchar(255) | N | 사진파일 Y 좌표 |  |  |
|  | 13-12 | VISIT_AREA_NM | varchar(255) | N | 방문지명 |  |  |
| 14 |  | TC_SGG | TABEL |  | 시군구 |  |  |
|  | 14-1 | SGG_CD | char(50) | Y | 전체코드 |  |  |
|  | 14-2 | SGG_CD1 | char(10) | N | 시도코드 |  |  |
|  | 14-3 | SGG_CD2 | char(10) | N | 시군구코드 |  |  |
|  | 14-4 | SGG_CD3 | char(10) | N | 읍면동코드 |  |  |
|  | 14-5 | SGG_CD4 | char(10) | N | 리코드 |  |  |
|  | 14-6 | SIDO_NM | varchar(100) | Y | 시도명 |  |  |
|  | 14-7 | SGG_NM | varchar(100) | N | 시군구명 |  |  |
|  | 14-8 | DONG_NM | varchar(100) | N | 읍면동 |  |  |
|  | 14-9 | RI_NM | varchar(100) | N | 리 |  |  |
| 15 |  | TC_CODEA | TABEL |  | 코드 A |  |  |
|  | 15-1 | idx | int(11) | Y | idx |  |  |
|  | 15-2 | cd_a | varchar(10) | Y | 코드 A |  |  |
|  | 15-3 | cd_nm | varchar(255) | Y | 코드 A 명 |  |  |
|  | 15-4 | cd_memo | varchar(255) | N | 메모 |  |  |
|  | 15-5 | cd_memo2 | varchar(255) | N | 메모2 |  |  |
|  | 15-6 | del_flag | char(1) | Y | 숨김여부 |  |  |
|  | 15-7 | order_num | int(11) | Y | 순서 |  |  |
|  | 15-8 | perm_write | ENUM('Y','N) | Y | 등록가능여부 | [Y, N] |  |
|  | 15-9 | perm_edit | ENUM('Y','N) | Y | 수정가능여부 | [Y, N] |  |
|  | 15-10 | perm_delete | ENUM('Y','N) | Y | 삭제가능여부 | [Y, N] |  |
|  | 15-11 | ins_dt | datetime | Y | 등록일 |  | YYYY-MM-DD HH:MI:SS |
|  | 15-12 | edit_dt | datetime | N | 수정일 |  | YYYY-MM-DD HH:MI:SS |
| 16 |  | TC_CODEB | TABEL |  | 코드 B |  |  |
|  | 16-1 | idx | int(11) | Y | idx |  |  |
|  | 16-2 | cd_a | varchar(10) | Y | 코드 A |  |  |
|  | 16-3 | cd_b | varchar(8) | Y | 코드 B |  |  |
|  | 16-4 | cd_nm | varchar(255) | Y | 코드 B 명 |  |  |
|  | 16-5 | cd_memo | varchar(255) | N | 메모 |  |  |
|  | 16-6 | cd_memo2 | varchar(255) | N | 메모2 |  |  |
|  | 16-7 | del_flag | char(1) | Y | 숨김여부 |  |  |
|  | 16-8 | order_num | int(11) | Y | 순서 |  |  |
|  | 16-9 | ins_dt | datetime | Y | 등록일 |  | YYYY-MM-DD HH:MI:SS |
|  | 16-10 | edit_dt | datetime | N | 수정일 |  | YYYY-MM-DD HH:MI:SS |

## 캡션 JSON 필드 사전

| 구분 |  | 속성명 | 타입 | 필수 여부 | 설명 | 범위 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  | info | Object |  | 데이터셋 정보 |  |  |
|  | 1-1 | DATASET_NM | string | Y | 데이터셋명 |  |  |
|  | 1-2 | DATASET_DETAIL | string | Y | 상세설명 |  |  |
| 2 |  | images | Object |  | 이미지정보 |  |  |
|  | 2-1 | PHOTO_FILE_ID | string | Y | 파일아이디 |  |  |
|  | 2-2 | PHOTO_FILE_NM | string | Y | 파일명 |  |  |
|  | 2-3 | PHOTO_FILE_SAVE_PATH | string | Y | 저장경로 |  |  |
|  | 2-4 | PHOTO_FILE_RESOLUTION | string | Y | 해상도 |  |  |
|  | 2-5 | PHOTO_FILE_DT | string | Y | 촬영일자 |  | YYYY-MM-D D HH:MI:SS |
|  | 2-6 | PHOTO_FILE_X_COORD | string | Y | 촬영위치( X) |  |  |
|  | 2-7 | PHOTO_FILE_Y_COORD | string | Y | 촬영위치( Y) |  |  |
|  | 2-8 | VISIT_AREA_NM | string | N | 방문지정보 |  |  |
|  | 2-9 | LANDMARK | string | N | 랜드마크( POI) |  |  |
| 3 |  | caption | Object |  | 캡션정보 |  |  |
|  | 3-1 | IMG_CAPTION | string | Y | 이미지캡션 내용 |  |  |
|  | 3-2 | TOKEN | int(11) | Y | 토큰 |  |  |
|  | 3-3 | TIME_STAMP | varchar(150) | N | 촬영일자 |  | YYYY-MM-D D HH:MI:SS |
| 4 |  | licenses | Object |  | 라이센스정보 |  |  |
|  | 3-1 | ID | varchar(50) | Y | ID |  |  |
|  | 3-2 | NAME | varchar(50) | Y | 구축기관 |  |  |

## 해석 시 유의점

- `필수 여부`의 Y/N 표기는 원문 컬럼 정의다. 원문이 선언하지 않은 PK/FK·유일성 제약을 뜻하지 않는다.
- 코드 열의 설명서 범위와 코드 그룹 참조를 보존했다. 모든 코드명·실제 관측값을 이 문서가 정의한다고 해석하지 않는다.
- 원문에 포함된 예시 사진·캡션 및 개별 값은 재수록하지 않았다.
