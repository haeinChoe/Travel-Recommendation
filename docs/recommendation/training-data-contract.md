# Recommendation Training Data Contract

Issue #17의 baseline 실험을 위한 데이터 의미와 사용 경계를 정한다. 이 문서는 추천 알고리즘이나 production serving 구조를 결정하지 않는다.

## 근거 표기

- **[문서 사실]** 저장소의 Issue #17, EDA 보고서 또는 네 권역 데이터 설명서에 명시된 내용.
- **[코드 사실]** 아래 공개 legacy 소스 파일이 구현하는 내용. 이는 AI Hub 값의 의미를 증명하지 않는다.
- **[EDA 관측]** Issue #12 문서에 기록된 안전한 집계 결과. 정확한 집계나 원본 행은 여기서 재실행하지 않았다.
- **[추론]** 문서·코드 사실에서 도출한 해석이며 도메인 사실로 확정하지 않는다.
- **[결정]** 이번 baseline 계약에 적용하는 선택.
- **[임시 결정]** 실험을 진행하기 위한 제한된 선택이며 근거·한계가 남아 있다.
- **[미결정]** 현재 근거로 정할 수 없어 후속 결정이 필요한 사항.

AI Hub 필드 표기는 [네 권역 설명서](../data/travel-log-2023/README.md)를 따른다: [수도권](../data/travel-log-2023/aihub-71776-capital.md), [동부권](../data/travel-log-2023/aihub-71778-east.md), [서부권](../data/travel-log-2023/aihub-71779-west.md), [제주·도서](../data/travel-log-2023/aihub-71780-jeju.md). EDA 근거는 [Issue #12 EDA 보고서](../data/eda-travel-log-2023.md)다.

## 1. 목적, 범위 및 비목표

**[결정]** 이 계약은 2023 국내 여행로그의 여행 방문을 recommendation baseline용 관측 positive로 구성하고, offline 후보 랭킹 실험의 입력·label·분할 경계를 일관되게 유지한다.

범위는 legacy 데이터 구조 복원, AI Hub 후보 필드 매핑, 사용자·항목·interaction·feedback 정의, feature availability, split, 후보군, 누수·cold-start·데이터 한계다. 최종 알고리즘 선택, 모델 학습·비교, hyperparameter tuning, TourAPI 실제 연동, production serving, retraining pipeline은 범위 밖이다.

**[결정]** raw image, image payload, raw image embedding은 baseline에서 제외한다. SbL caption-derived feature도 baseline 입력에서 제외하고 후속 실험 후보로만 둔다. 이는 현재 EDA의 SbL JSON 구조·allowlist 집계가 feature 품질이나 추천 효용 검증은 아니기 때문이다.

## 2. Legacy TravelMate 구조 및 복원

**[코드 사실]** 공개 `travelmate-model`의 `app/preprocessing.py`는 `gender`, `age_grp`, `start_month`를 one-hot encode하고 `content_id` 방문 pivot으로 `traveler_id` × `content_id` 방문 행렬을 만든다. 사용자 유사도는 profile 유사도와 방문 유사도를 각각 0.7 및 0.3으로 혼합한다. 이 가중치는 legacy 코드의 사실일 뿐 새 baseline 가중치가 아니다.

**[코드 사실]** `app/recommendation.py`는 유사 사용자의 방문과 `content_embeddings`를 추천 단계에서 사용한다. 이 구조는 collaborative interaction과 item-content 정보를 함께 소비했다는 것을 보여주지만, embedding 생성 provenance나 AI Hub 필드 대응을 자동으로 입증하지 않는다.

**[코드 사실]** `travelmate-model/app/schema.py`와 `models.py`는 `Preference` 입력(여행 스타일 1–7 및 동반자 포함)과 `Visited(traveler_id, content_id)`를 정의한다. `travelmate-backend`의 `Preference.java`는 traveler relation, 인구통계, 여행 날짜, 스타일 1–7 및 동반자를 보유하며, `Visited.java`는 traveler와 `contentId`를 보유한다. `TourSpot.java`의 `contentId`는 TourAPI content ID이고, 분류·지역/구역·테마 metadata가 함께 정의된다.

**[코드 사실]** backend `PreferenceDTO.java`에는 `regionId`가 있고 `RecommendController`는 survey 입력을 받아 preference를 저장한 뒤 모델에 user id와 region을 전달한다. 별도 save-visited endpoint는 방문을 저장한다. 따라서 legacy 추천 요청의 user/region/preferences context와 방문 기록은 구분된다.

**[미결정]** 공개 코드에서 `content_embeddings` 사용은 확인했으나 해당 artifact의 완전한 생성·버전·학습 출처와 AI Hub의 어느 필드로부터 만들어졌는지는 이번 근거로 확인하지 않았다. 이 계약에서는 기존 embedding을 이식하지 않는다.

## 3. Legacy → AI Hub 필드 매핑 및 유지·변경·폐기

아래 AI Hub 필드는 후보 매핑이다. 동일 이름·유사 역할만으로 값의 동등성이나 key 관계를 주장하지 않는다.

| Legacy field / artifact | Legacy role | AI Hub 2023 source candidate | 새 시스템 처리 | 근거 / 제한 |
| --- | --- | --- | --- | --- |
| `Preference.gender`, `age_grp` | 사용자 survey profile | `TN_TRAVELLER_MASTER.GENDER`, `AGE_GRP` | **변경:** 명시적 허용 시 contextual profile candidate. 기본 baseline 필수 feature 아님 | 네 schema는 두 열을 선택 항목으로 정의. 사용자가 서비스에서 제공하는 시점·동의·결측 정책 미정 |
| `Preference.travel_style_1..7` | 선호 context | `TN_TRAVELLER_MASTER.TRAVEL_STYL_1..8` | **변경:** 1–8 열 후보를 보존하되 기존 1–7과 직접 동등시하지 않음 | AI Hub schema는 8개 필드, 코드 범위 1–7. 의미별 문항 대응·normalization 미정 |
| legacy companion fields | trip companion context | `TN_COMPANION_INFO` 관계/성별/연령/상황, `TN_TRAVELLER_MASTER.TRAVEL_STATUS_ACCOMPANY`, `TRAVEL_COMPANIONS_NUM` | **변경:** trip-context 후보. baseline 필수 아님 | 서로 다른 표현 단위가 혼재; 의미 및 serving 입력 매핑 미정 |
| `Preference.regionId` / request region | 요청 지역 context | `TRAVEL_STATUS_DESTINATION`, `TN_VISIT_AREA_INFO.SGG_CD`, `TN_POI_MASTER.SGG_CD`, `TN_POI_MASTER` metadata | **변경:** 명시 요청의 목적지 scope 후보; source region code/ID 일치 규칙 미정 | 필드명만으로 regionId와 AI Hub 코드의 동등성 없음. 권역 밖 검증도 미실시 |
| `Visited(traveler_id, content_id)` | user-item 방문 interaction | `TN_TRAVEL.TRAVELER_ID` + `TRAVEL_ID`; `TN_VISIT_AREA_INFO` 방문 기록 → `POI_ID` 또는 `VISIT_AREA_ID` candidate | **변경:** `(region, TRAVELER_ID)` × 여행 × 방문 기록으로 유지. item identity는 임시 region-scoped `POI_ID` when present; fallback identity 미결정 | `POI_ID`는 canonical PK/FK로 확정되지 않음. EDA에서 POI/visit-area 후보 결측·overlap 관측 |
| legacy `content_id` / `TourSpot.contentId` | TourAPI item identity | AI Hub `POI_ID`, `VISIT_AREA_ID`, POI name/category/region metadata | **폐기/미매핑:** 직접 ID 등가·TourAPI 연결을 하지 않음 | 외부 canonical mapping과 ID 전략 없음. `VISIT_AREA_ID`는 방문 record identifier 후보로 유지 |
| `TourSpot` categories, region/district/theme | item metadata | `TN_POI_MASTER.ASORT_LCLASDC`, `ASORT_MLSFCDC`, `ASORT_SDASDC`, `SGG_CD` 및 visit-area `VISIT_AREA_TYPE_CD`, `SGG_CD` | **변경:** metadata 후보; schema-field availability 확인 전 optional item context로만 취급 | 두 테이블의 분류 체계 동일성 미확인. 정규화·crosswalk 미정 |
| `content_embeddings` | item content representation | SbL `caption.IMG_CAPTION`, `images.LANDMARK`/`VISIT_AREA_NM` 또는 POI metadata 후보 | **폐기:** 기존 artifact 미이식. caption-derived text는 후속 실험만 | 생성법·매핑·품질 미확인; baseline은 raw image 및 image embedding 제외 |
| profile one-hot `gender`, `age_grp`, `start_month` | preprocessing features | `GENDER`, `AGE_GRP`; `TRAVEL_START_YMD` month candidate | **변경:** profile/date context는 availability policy를 통과해야 함; start-month 변환은 확정하지 않음 | legacy preprocessing 구현 사실. 날짜 파생 규칙·제품 필요성 미정 |
| profile 0.7 + visit 0.3 similarity | user-user recommendation score | 해당 없음 | **폐기:** 가중치를 새 baseline으로 전용하지 않음 | legacy 모델 결정이지 AI Hub 기반 실험 근거가 아님 |

## 4. User 정의

**[임시 결정]** 학습 user key는 `(region, TRAVELER_ID)`로 둔다. 네 권역 간 `TRAVELER_ID` uniqueness나 동일 인물 equivalence는 입증되지 않았으므로 region을 포함하고 cross-region identity merge를 가정하지 않는다. 방문 context는 `TRAVEL_ID`로 구분한다. 이 원본 identifiers는 승인된 처리 중 memory-only join/group keys이며, artifacts나 logs에 저장하지 않는다. 모델 feature와 serving payload에도 넣지 않는다. 온라인 요청의 user identity와 AI Hub 식별자는 같다고 간주하지 않는다.

**[추론]** 이 임시 정의는 공개 schema에서 `TN_TRAVEL.TRAVELER_ID`가 여행객 ID이고 `TN_TRAVEL.TRAVEL_ID`가 여행 ID라고 설명하는 데 따른다. EDA는 분석된 각 region/split scope에서 trip-to-traveler mapping이 모호하지 않았다고 기록하지만, 이는 scope 안의 관계만 뒷받침한다. 네 권역 간 traveler ID의 global uniqueness나 같은 사람 여부, 생산 서비스 identity bridge를 입증하지 않는다.

**[제한]** 반복 trip/user 구조가 legacy의 장기 user-history CF를 정당화하는지 결정할 만큼 문서화된 실험 결과는 없다. 신규 온라인 user는 history 없는 cold-start cohort로 따로 취급한다. AI Hub ID를 서비스 계정에 연결하거나 직접 노출하지 않는다.

## 5. Item 정의

**[임시 결정]** 실험상 item 후보는 같은 region scope 안에서 비어 있지 않은 `TN_VISIT_AREA_INFO.POI_ID` 원문 값으로 식별한다. 이 값은 오직 임시 candidate key이며 canonical POI, 공식 primary/foreign key, 권역 간 공통 ID로 선언하지 않는다. `region`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, `TRAVELER_ID` 원본 값은 joins/grouping을 위해 처리 중 memory에만 둘 수 있고 artifacts/logs에 persist하지 않는다. Row-level output이 별도 승인된 필요로 생기는 경우에도 원본 식별자 대신 해당 run에서만 유효한 opaque key를 쓴다.

**[대체 경로 미결정]** `POI_ID`가 비거나 item candidate로 안전하게 사용할 수 없는 방문은 baseline interaction item에서 제외하고 제외 건을 privacy-safe aggregate로 보고한다. `VISIT_AREA_ID`, 이름, 좌표로 대체하거나 canonical mapping을 만들지 않는다. 해당 선택은 coverage를 낮출 수 있다.

**[EDA 관측]** 네 권역 EDA는 `POI_ID`와 visit-area 후보 간 overlap 및 결측, TL/VL 후보 overlap, validation 후보 cold-start를 coarse band로 보고했다. EDA 문서는 이 필드들을 후보 관계로만 다뤘고 canonical identity를 확정하지 않았다. 따라서 canonical item 수, 최종 sparsity, 지역 간 합산 identity는 이 계약에서 산출하지 않는다.

## 6. Interaction 정의

**[결정]** 기본 interaction은 관측된 방문지 행을 통한 implicit positive다. 최소 분석 grain은 `(region, TRAVEL_ID, VISIT_AREA_ID)`이며 memory 안에서 `(region, TRAVELER_ID)`와 연결한다. 평가 item key는 §5의 임시 region-scoped `POI_ID` candidate다. 식별자 원문은 artifacts/logs에 persist하지 않는다.

- 방문 row는 “관측된 방문”을 뜻하며 preference 강도나 추천 의도 자체를 뜻하지 않는다.
- 같은 trip 내 여러 방문 event는 구분된 방문으로 유지한다. 같은 user-item 여러 trip 방문도 원본 event로 보존한다.
- 반복 방문을 하나로 합칠지, interaction weight를 둘지, `VISIT_ORDER`/방문 시간을 sequence feature로 쓸지는 미결정이다. baseline에서는 interaction weight를 만들지 않고 event-level binary positive만 사용한다.
- 방문하지 않은 item은 negative로 취급하지 않는다. negative sampling이 필요하면 sampling universe와 seed를 별도 실험 설정에 명시한다.
- `REVISIT_YN`은 방문 후 속성 후보이며, 방문 event를 중복 제거하는 규칙으로 해석하지 않는다.

schema의 필수 여부 표시는 원문 선언이며 PK/FK·유일성 제약이 아니다.

## 7. Label / Feedback 정의

**[결정]** 방문은 관측 positive, `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`은 분리된 사후 feedback/auxiliary label 후보로 취급한다. 모두 `TN_VISIT_AREA_INFO`의 optional 필드이며 schema는 각 코드 범위를 1–5로 적는다. 방문 후 응답을 추천 시점 입력으로 사용할 수 없다.

| Field | Contract role | Input use | Label use and unresolved interpretation |
| --- | --- | --- | --- |
| `DGSTFN` | 사후 만족도 feedback | 금지 | 별도 auxiliary/graded target 후보. 1–5의 순서 해석은 필드 이름·코드 그룹 설명에만 근거; 결측/인코딩 검증 및 label 방향 의미 추가 확인 필요 |
| `REVISIT_INTENTION` | 사후 재방문 의향 | 금지 | 별도 auxiliary label 후보; 미래 행동이나 실제 재방문으로 해석 금지. ordinal 의미와 결측 처리는 미결정 |
| `RCMDTN_INTENTION` | 사후 추천 의향 | 금지 | 별도 auxiliary label 후보; 다른 두 label과 합산 금지. ordinal 의미와 결측 처리는 미결정 |

EDA에서 feedback 필드의 값 범위와 결측 범주가 관측됐으나, 관측 구조는 serving 유효성이나 세부 응답 semantics를 확정하지 않는다. 세 label은 baseline의 primary target이 아니다. 이들을 쓰는 후속 실험은 별도 target definition과 leakage check가 필요하다.

## 8. Feature Availability Matrix

Availability는 “수집 가능한가 / 사용자에게 물어야 하는가 / 예측 시점에 존재하는가”를 기준으로 했다. **Online available**은 AI Hub 기록에 있다는 이유만으로 부여하지 않았다. serving feature 허용에는 같은 의미의 제품 입력과 시점 확인이 필요하다.

| Feature | AI Hub source candidate | Role | Inference availability | Acquisition / proxy | Baseline treatment / notes |
| --- | --- | --- | --- | --- | --- |
| `AGE_GRP` | `TN_TRAVELLER_MASTER.AGE_GRP` | 사용자 profile | Technically available but product-inappropriate by default | 사용자 명시 제공 및 최소 수집 검토 필요 | 제외; 민감도·공정성·동의 정책 미결정 |
| `GENDER` | `TN_TRAVELLER_MASTER.GENDER` | 사용자 profile | Technically available but product-inappropriate by default | 사용자 명시 제공 외 proxy 금지 | 제외; 코드 semantics·정책 미결정 |
| `TRAVEL_STYL_1`–`TRAVEL_STYL_8` | `TN_TRAVELLER_MASTER` | 장기 preference 후보 | Unavailable as same-value serving input until product collection is defined | 선택 설문이 proxy 후보; legacy는 1–7개 필드여서 직접 등가 미확인 | baseline 필수 입력 아님; 분해·순서·가중치 미결정 |
| `TRAVEL_MOTIVE_1`–`TRAVEL_MOTIVE_3` | `TN_TRAVELLER_MASTER` | trip context | Unavailable until request collection and timing are defined | 현재 여행 설문 proxy 후보 | 제외; 3번째 필드 blank 관측 포함, normalization 미결정 |
| Companion features | `TRAVEL_STATUS_ACCOMPANY`, `TRAVEL_COMPANIONS_NUM`, `TN_COMPANION_INFO` (`REL_CD`, gender/age/situation) | trip context | Derivable from survey/history; online equivalent unresolved | 명시 요청 설문만 proxy 후보 | baseline 제외; aggregate/household/member 의미 미결정 |
| Destination / region | `TRAVEL_STATUS_DESTINATION`; visit/POI `SGG_CD`; region dataset scope | request filter/context or item metadata | Derivable for offline rows; online request region is legacy precedent | User-selected destination/region is serving proxy candidate | Candidate filter may use explicit request scope; mapping/crosswalk and out-of-region behavior unresolved |
| Trip duration | `TN_TRAVEL.TRAVEL_START_YMD`, `TRAVEL_END_YMD` | trip context | Derivable offline; not known for a new request absent dates | Explicit planned dates are a possible serving proxy | Baseline exclude; duration formula, invalid/missing dates and temporal privacy policy unresolved |
| POI category | `TN_POI_MASTER.ASORT_*`; visit `VISIT_AREA_TYPE_CD` | item content metadata | Derivable offline if linked; online only with item catalog metadata | Catalog metadata proxy | Optional candidate metadata; category systems are not assumed equivalent; normalization/crosswalk unresolved |
| POI metadata | `TN_POI_MASTER` names, region, district, category fields; visit-area fields | item content | Derivable offline if candidate linkage is stable | Catalog lookup/proxy | No external lookup; no canonical mapping, normalization, or dedupe |
| SbL caption-derived text | `caption.IMG_CAPTION`; possible `images.LANDMARK`, `VISIT_AREA_NM` | item content candidate | Offline-only in current evidence | Not a serving proxy in this baseline | Excluded from baseline. EDA coverage/linkage is not semantic validation; raw caption/text is not reproduced |
| `DGSTFN` | `TN_VISIT_AREA_INFO.DGSTFN` | post-event label | Offline/post-event only | No valid pre-event proxy | Never input; optional feedback label only |
| `REVISIT_INTENTION` | `TN_VISIT_AREA_INFO.REVISIT_INTENTION` | post-event label | Offline/post-event only | No valid pre-event proxy | Never input; optional feedback label only |
| `RCMDTN_INTENTION` | `TN_VISIT_AREA_INFO.RCMDTN_INTENTION` | post-event label | Offline/post-event only | No valid pre-event proxy | Never input; optional feedback label only |
| `TRAVEL_ID`, `TRAVELER_ID`, `VISIT_AREA_ID` | TN travel / visit tables | row identity / joins | Offline-only IDs | No direct online proxy | Memory-only join/group keys; raw values never persisted to artifacts/logs and never used as model features or serving payload |
| Raw image / image embedding | photo payload / derived artifact | visual feature | Unavailable in baseline | None | Explicitly excluded; no image opening, extraction, embedding, or use |

## 9. Train / Validation / Test split

**[임시 결정]** 첫 offline baseline은 AI Hub의 source role을 보존해 `TL_csv`를 train, `VL_csv`를 validation으로 읽는다. EDA는 이 두 역할의 scope를 구분해 집계하며 overlap/cold-start를 기록한다. source role명을 split으로 사용한다는 것은 임시 실험 규칙이고, 관측 독립성·공식 무작위화·시간 순서가 보장된다는 뜻은 아니다.

**[미결정]** 별도 test 역할은 현재 읽은 근거에서 확인되지 않았다. 검증 결과를 보고 test split을 새로 떼거나 VL을 test로 재명명하지 않는다. 독립 holdout의 출처/승인과 split protocol이 정해질 때까지 test metrics는 생성하지 않는다. 즉 초기 baseline은 train/validation 개발 비교까지만 허용한다.

**Leakage 방지 규칙:** interaction event와 그 trip에 속한 방문/feedback이 서로 다른 partition에 나뉘지 않도록 평가 단위를 여행(`TRAVEL_ID`)로 묶는다. TL/VL source role을 넘는 trip, traveler 또는 POI candidate overlap은 누수 및 cohort 설명에 기록한다. 같은 validation trip의 feedback·방문·metadata를 해당 추천 시점의 input으로 쓰지 않는다. Profile feature는 label 이후에만 관측되는 값이 아닌지 검토하고, 식별자는 feature에서 뺀다.

**[미결정]** “사용자 신규성”과 “미등장 item”을 함께 평가하는 cohort, 시간순 holdout, 지역 간 holdout은 별도 실험이다. EDA에 기록된 TL/VL candidate overlap 및 cold-start bands는 split 보증 또는 독립 test 증거가 아니다.

## 10. Candidate universe

**[임시 결정]** 초기 ranking의 candidate universe는 명시 요청된 destination/region scope가 있을 때 같은 region scope에서 관측·카탈로그화된 nonblank `POI_ID` item candidates다. 요청 목적지의 더 세밀한 행정구역 범위는 AI Hub `SGG_CD`가 명시적 serving scope와 호환됨을 확인한 후에만 적용한다. 명시 region이 없거나 mapping이 모호한 경우 임의로 전국/권역 후보를 바꾸지 않고 해당 평가 케이스를 unresolved 처리한다.

Candidate universe는 모델별로 변경하지 않고 평가 cohort별로 고정·기록한다. 방문하지 않은 후보를 negative label로 보지 않는다. 실제 방문 positive만 ground truth다. 유효 후보 집합 또는 positive가 후보군 밖일 경우 제외 사유를 집계한다.

**제한:** EDA는 POI candidate overlap 및 cold-start를 요약했지만 canonical POI나 경계/crosswalk 정책을 확정하지 않았다. 이 임시 region-scoped universe는 안정된 장소 identity, 실제 서비스 재고, 이용 가능 상태를 보증하지 않는다.

## 11. Leakage, cold start, 데이터 한계

- **사후 label leakage:** `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`은 방문 결과 뒤의 값이므로 입력 금지.
- **행/여행 leakage:** 동일 `TRAVEL_ID`의 방문 event·feedback은 한 partition에 유지. 동일 traveler/item이 partition 사이 공유되는지 별도 식별해 validation 결과에 표시.
- **catalog leakage:** `POI_ID`, names, category, region metadata를 쓰는 경우 validation/test 후보 시점에 실제 이용 가능했던 catalog snapshot을 입증하지 못하면 offline static catalog 실험으로 명시.
- **negative leakage:** unvisited는 negative가 아니다. sampled negative를 쓸 때 sampling이 positive 미래 방문과 충돌하는 위험 및 sampling 설정을 보고.
- **cold-start:** validation POI가 train에 없는 비율은 별도 cohort metric 대상으로 삼을 수 있지만, canonical item 불확실성을 밝혀야 한다. EDA의 TL/VL overlap/cold-start band를 독립 item identity의 검증값으로 보지 않는다.
- **ID와 개인정보:** 원본 traveler IDs, exact dates, exact coordinates, 장소명, 자유 텍스트, captions, 이미지 내용을 결과·로그·공유물에 싣지 않는다. 모델 feature에서도 raw IDs를 제외한다.
- **컬럼/코드 품질:** 네 권역 설명서는 컬럼명, 설명, 선언 자료형·범위를 제공하지만 필수 Y/N은 PK/FK·유일성을 뜻하지 않는다. 일부 코드 필드의 복합 표현은 설명서로 해석되지 않았고 normalization 금지.
- **범위와 선택 편향:** 권역별 TL/VL 구조·coverage는 다를 수 있고, 권역 경계 및 권역 밖 방문은 확인되지 않았다. EDA 숫자는 억제된 coarse buckets/bands라 개별 분포나 사용자 적합성 결론을 대신하지 않는다.
- **이미지/SbL:** raw image, image embedding 및 caption-derived text는 baseline에서 제외. 구조적 존재나 candidate linkage만으로 내용의 정확성·item 연결·서비스 사용 가능성을 입증하지 않는다.

## 12. 미결정 사항과 필요한 근거

| 미결정 사항 | 왜 지금 정하지 않는가 | 필요한 근거 / 다음 판단 |
| --- | --- | --- |
| Canonical POI key 및 `POI_ID`와 `VISIT_AREA_ID` 관계 | schema 설명만으로 PK/FK·identity 안정성 미확인; EDA도 후보 관계로만 처리 | 승인 범위 내 source documentation / key semantics 및 검토된 linkage 진단 |
| Region scoping 및 지역 간 ID collision | 경계 자료·지역 key uniqueness 검증 없음 | 공식 region mapping/경계, 안전한 충돌 집계 |
| `POI_ID` 결측 item fallback | name/address/coordinates 조합은 추정 identity를 만들게 됨 | 승인된 canonical mapping/확정된 business rule |
| TL/VL split의 설계·독립성 및 공식 test source | 문서화된 split guarantee를 확인하지 못함 | AI Hub split description 및 test data 권한/절차 |
| profile/context의 serving 재현 가능성·허용 | dataset availability는 제품 수집·동의·시점과 다름 | serving request contract, data minimization/privacy 결정 |
| 코드 복합표현, 결측·invalid 처리 | 설명서가 구분자/정규화 정의 안 함; EDA unknown은 invalid를 뜻하지 않음 | field owner/codebook clarification 및 승인된 의미 검증 |
| 반복 방문 집계·visit sequence·interaction weight | 현재 계약은 weight를 두지 않음; 도메인 의미/알고리즘 실험 미정 | 별도 experimental protocol과 metric 목적 |
| Feedback ordinal semantics 및 threshold | 선언된 1–5 range만으로 응답 방향/label utility 미확정 | 공식 codebook/questionnaire wording, label validation |
| SbL caption text usage | baseline 제외; content linkage/quality 검증 없음 | text-use permission, data handling review, semantic validation, serving parity |
| baseline metrics, negative sampling, exact candidate snapshot | Issue #17 data contract이지 algorithm/metric design issue가 아님 | 후속 experiment issue가 protocol·seed·catalog snapshot을 정함 |

## 13. Baseline 실험 계약

후속 baseline은 이 문서와 구체 실험 설정만으로 재현 가능한 정의를 남긴다.

1. **Input boundary:** 승인된 네 권역 2023 TL/VL tabular source와 tracked schema/EDA docs. raw images, image embeddings, raw IDs as features, external TourAPI 조회, ignored results/artifacts는 입력·출력으로 사용하지 않는다.
2. **Entity rows:** memory 안에서 `(region, TRAVELER_ID)`와 `TRAVEL_ID`로 여행 context를 잡고, `TN_VISIT_AREA_INFO`의 `(region, TRAVEL_ID, VISIT_AREA_ID)` 방문 event를 연결한다. 실제 join/key uniqueness는 실행 시 검증하되 문서의 필수 표기를 FK 증거로 사용하지 않는다. 원본 identifier는 artifacts/logs에 persist하지 않는다.
3. **User:** `(region, TRAVELER_ID)` provisional grouping key, not model feature; cross-region identity merge is not assumed. serving account mapping은 불가정.
4. **Item:** 비어 있지 않은 region-scoped `TN_VISIT_AREA_INFO.POI_ID` 임시 item candidate. missing/unusable candidates는 identity를 추정하지 않고 제외 집계. 이 baseline은 canonical item 평가가 아니다.
5. **Positive/labels:** 방문은 binary observed-positive event, unvisited is unknown. Repeated events remain event-level with no weight. Feedback columns are separate optional post-event targets only, never features.
6. **Features:** item-popularity baseline may use only train-partition event counts within the fixed candidate universe. Contextual feature ablation is a separate run and may add only request-time-equivalent fields with recorded availability. Demographics, styles/motives, companions, duration, POI category/metadata and SbL caption are not silently presumed available.
7. **Split:** TL source role = train, VL source role = validation (provisional). Group interactions by trip; report traveler/item overlap and cold-start cohort. No test score until a separately authorized and documented test source/protocol exists.
8. **Candidate universe:** explicit destination/region scope mapped to same-region candidate catalog only; candidate definition held constant across compared models. No inferred cross-region/canonical joins.
9. **Sampling and metrics:** unvisited is not a negative; if sampling/metric choices are required, document them as experiment-specific decisions, with seed, candidate snapshot, cohort, and positive coverage. This contract does not prescribe weights or algorithm.
10. **Reproducibility/privacy:** record dataset identifiers/version and file roles without original rows/IDs, code revision, config, seed, split, field allowlist, safe aggregate coverage and run outcome. Keep data/derived artifacts in approved ignored paths; do not log source IDs, raw caption, coordinates, exact dates, or small-cohort values.

**Limitation:** 이 계약은 data semantics와 비교 가능한 경계를 정한 것이지, 현재 로컬 자료로 수행 가능한 모델 성능이나 온라인 유효성을 보증하지 않는다. item identity, test split, serving feature availability가 unresolved인 상태에서는 결과를 해당 임시 설정 범위 안에서만 해석한다.

## Decision log

| Decision | Status | Rationale |
| --- | --- | --- |
| `(region, TRAVELER_ID)` grouping; retain `TRAVEL_ID` context; raw IDs are memory-only and not features | Provisional | Schema roles are documented; cross-region uniqueness, serving identity bridge, and long-term history utility are not |
| Region-scoped nonblank `POI_ID` as temporary item candidate | Provisional | Enables bounded experiment without claiming canonical identity; no fallback mapping |
| Visit event as binary implicit positive; no weight; unvisited unknown | Decided for baseline | Matches observed visit structure while avoiding invented preference strength/negative labels |
| Feedback fields are post-event labels only | Decided | Their schema location/role is post-visit; leakage otherwise |
| TL train, VL validation; no test metric | Provisional | Preserves source role split and does not invent test independence/source |
| Same-region requested candidate scope | Provisional | Bounded scope; official region/ID crosswalk still unresolved |
| Exclude raw images and image embeddings | Decided | Explicit baseline boundary; no image pipeline or raw image EDA |
| Exclude caption text from baseline | Decided | Coverage/linkage evidence is not semantic, permission, or serving-parity evidence |
| Do not transfer legacy 0.7/0.3 weights, one-hot encoding or TourAPI IDs | Decided | Implementation facts are not validated AI Hub transformation rules |

## Appendix A. Public legacy source references

Code evidence refers to the published repository files below. The links establish implementation locations; they do not prove AI Hub field semantics, model quality, or an external data license.

| Evidence | Exact public source path |
| --- | --- |
| Preference/profile + `content_id` visit pivot; user similarity | [`travelmate-model/app/preprocessing.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/preprocessing.py) |
| Similar-user visits and `content_embeddings` recommendation use | [`travelmate-model/app/recommendation.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/recommendation.py) |
| Model Preference / Visited schema | [`travelmate-model/app/schema.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/schema.py), [`travelmate-model/app/models.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/models.py) |
| Backend `Preference`, `Visited`, and `TourSpot` entities | [`travelmate-backend/src/main/java/travelmate/backend/entity/Preference.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/Preference.java), [`Visited.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/Visited.java), [`TourSpot.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/TourSpot.java) |
| Request DTO / recommend flow | [`travelmate-backend/src/main/java/travelmate/backend/dto/PreferenceDTO.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/dto/PreferenceDTO.java), [`RecommendController.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/controller/RecommendController.java) |
| Save-visited persistence flow | [`travelmate-backend/src/main/java/travelmate/backend/service/RecommendationService.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/service/RecommendationService.java) |

**Source verification:** the legacy source tree and cited file contents were checked at backend commit `0f63c6ec9a754aafc5cb8b1eb847209f034f37cb` and model commit `097fca72b9c4299f70bdec30730ba7342710bbf7`; Appendix A links are pinned to those revisions.
