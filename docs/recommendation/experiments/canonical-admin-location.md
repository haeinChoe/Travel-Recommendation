# POI canonical administrative location

**관련 Issue:** #41, #79, #81
**현재 상태:** I2 schema와 synthetic reconciliation 완료 / #82 candidate run에서 제한된 Master unresolved 및 candidate geography aggregate 기록 / 전체 source conflict·coverage 감사는 미실행

## 이 문서가 답하려는 질문

AI Hub의 여러 위치 단서를 어떻게 하나의 검증 가능한 행정구역 특성으로 만들고, 위치 충돌과 출처 불확실성을 모델 입력 전에 어떻게 처리할지 정의한다.

## 한눈에 보는 결론

- I2 모델 입력은 `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`다.
- 시도는 2자리, 시군구는 AI Hub `TC_SGG` 코드북에 등록된 5자리이며, 코드북 이름은 설명용 메타데이터다.
- `region`은 `capital`/`west`/`east`/`jeju-islands` 제품 권역이다. 시도·시군구와 request target geography는 각각 다른 의미를 갖는다.
- Master의 정적 SGG와 정적 주소를 코드북에 대조한다. 유일한 근거만 있으면 해결하고, 서로 다른 코드면 null + `conflict`, 모호한 주소는 null + `ambiguous_address`로 보존한다.
- visit SGG/address는 train 입력 범위 안에서 감사만 하며 I2를 채우거나 덮어쓰지 않는다. held-out positive가 자기 feature를 만들 수 없다.
- TN_POI_MASTER 고유 행은 static location evidence의 입력이 될 수 있지만, 이 사실만으로 모두 ranking candidate가 되지는 않는다. Candidate 자격은 모델/실험의 별도 geography 계약을 적용한다. `observed_in_splits=[]`인 train-unseen item은 해당 계약을 통과하고 선택한 정적 특성을 제공하면 후보가 될 수 있다.
- 과거 Issue #69 identity 감사는 AI Hub와 TourAPI 좌표가 WGS84 범위에 든다는 사실과 4,279 regional / 4,686 global anchor 사이의 거리 분포를 독립적으로 확인했다(각각 200m 이내 93.11% / 93.45%). 이는 매칭된 anchor subset에 대한 경험적 결과이며, 공식 CRS·X/Y source contract나 전체 Master inventory 좌표의 의미/coverage를 확립하지 않는다. 이번 I2는 기존 raw coordinate/H3/distance 제외 결정을 따르고, 위치 정제나 ranking에 좌표를 사용하지 않는다. `coordinate_validation_status=subset_validation_only_not_used`로 범위를 표시한다.

## 결정된 필드와 의미

| 필드 | 의미 | 사용 범위 |
|---|---|---|
| `canonical_admin_sido_code` | 코드북으로 확인된 시도 코드 2자리 | 모델 입력 |
| `canonical_admin_sgg_code` | 코드북에 등록된 시군구 코드 5자리 | 모델 입력 |
| `canonical_admin_location_status` | 해결/충돌/모호/미확정 상태 | 모델 입력 |
| `canonical_admin_sido_name`, `canonical_admin_sgg_name` | 같은 `TC_SGG` 행의 이름 | 점검용 메타데이터 |
| `canonical_admin_provenance` | 사용된 정적 출처 종류의 목록 | 감사용; 값·주소 원문 없음 |
| `canonical_admin_conflict_sources` | 해결을 막은 출처 종류 | 감사용; 원시값 없음 |
| `coordinate_validation_status` | 현재 `subset_validation_only_not_used` | 감사용. 과거 anchor subset 검증이 있었으나 전체 정적 inventory를 보증하지 않음 |

행정 granularity는 시도와 시군구다. 시군구명은 일반 행정구역 이름을 codebook 그대로 보존한다. 이 feature는 도로/동 단위 위치, 네 coarse product region, 서비스 요청에서 사용자가 지정한 target region을 뜻하지 않는다. Candidate hard filter는 별도 request geography 계약을 사용한다.

## 증거 우선순위와 충돌 정책

정적 Master SGG와 주소를 각각 `TC_SGG` 코드와 이름에 독립적으로 대응한 뒤 합친다. 입력 코드가 정확히 유효하거나 10자리 표현에서 후행 5자리가 모두 0일 때만 5자리 prefix를 인정한다. 주소는 명시된 SIDO와 SGG 이름이 codebook 한 행에 정확히 대응할 때만 근거로 인정한다. 동명 SGG가 둘 이상이면 모호하다. 느슨한 fuzzy match, 주소 일부 추측, 좌표 추정은 하지 않는다.

`resolve_canonical_admin_location()`의 API는 static Master/TourAPI evidence만 받는다. 방문 SGG/address 인자는 없고, visit 값은 별도 `compare_visit_location()` 진단에서만 비교하므로 interaction evidence가 canonical code/status/provenance를 바꿀 수 없다.

여러 정적 근거가 같은 SGG를 지지하면 해결한다. Master 코드와 주소가 다르거나, 같은 source가 복수 SGG를 가리키거나, 보조 TourAPI 주소/행정 코드가 Master와 다른 코드를 가리키면 `conflict`로 처리하고 canonical 코드를 비운다. 주소 후보가 여러 행정구역에 맞으면 `ambiguous_address`로 처리한다. 유효 위치 근거가 없으면 `unavailable`이다. Persisted `canonical_admin_location_status`는 `resolved_single_source`, `resolved_multi_source`, `conflict`, `ambiguous_address`, `unavailable` 중 하나다. `visit_only_unconfirmed`는 visit corroboration 진단 상태일 뿐 item feature enum에 포함하지 않는다.

TourAPI snapshot의 주소·행정 필드는 generic resolver의 보조 입력으로 허용한다. 그러나 현재 학습 데이터 생성 경로에는 AI Hub item과 TourAPI `contentid` 사이의 승인된 동일 항목 연결을 공급하지 않으므로 실제 item feature에는 병합하지 않는다. `contentid`/주소 유사성만으로 POI identity를 만들지 않는다. 검증된 연결이 후속으로 제공되면 동일한 concordance 정책을 통과해야 한다.

## 누수와 inventory 경계

정적 item feature는 고유 `TN_POI_MASTER` 행의 static evidence를 기준으로 만든다. 전체 Master evidence와 interaction에만 있는 item metadata-only 행을 구분한다. Master가 없는 관측 item은 정적 feature evidence를 만들 수 없으므로 configured-feature candidate로 간주하지 않는다. Master inventory의 행 중 canonical location이나 category가 비어도 다른 선택된 정적 feature를 만들 수는 있으나, 실제 candidate eligibility는 별도 request/ProductRegion 계약을 따른다. Issue #82의 corrected 수도권 runner는 unresolved 또는 수도권 mapping 밖 item을 제외하고, `load_poi_catalog_policy()`의 versioned `product_region_to_ldong_regn_cd`와 resolved `canonical_admin_sido_code`로 geography를 판정한다. Train-observed 여부로 후보를 필터링하지 않는다.

방문 행 SGG/address는 TL에 한정한 비식별 비교 집계에만 사용한다. `canonical_admin_*` 결과와 provenance를 변경하지 않으며 validation row를 검사해 feature를 보완하지 않는다. TL inner-split에서 inner-validation 방문 위치를 집계하면 누수가 생기므로, I2 feature는 static evidence만 사용한다. 따라서 방문 출처의 코드 보강은 하지 않고 그 근거는 현재 감사 범위에 한정한다.

## 실제 데이터 감사 상태

완료된 코드는 run마다 다음 상태별 집계를 `manifest.json`에 기록한다.

- 고유 Master inventory 분모와 static `resolved_single_source`, `resolved_multi_source`, `conflict`, `ambiguous_address`, `unavailable` 수
- TL visit corroboration 분모와 `agrees`, `conflicts_with_static`, `visit_internal_conflict`, `visit_only_unconfirmed` 등 수
- canonical feature에서 visit 값이 사용되지 않았음을 나타내는 boolean

#82의 corrected 수도권 TL candidate run은 승인된 입력 역할을 확인한 뒤 Master에 대해 canonical SIDO 기준 candidate count, unresolved ID 수/rate, 그리고 validation positive coverage를 제한된 privacy-safe aggregate로 기록했다. 이는 한 권역의 candidate geography 범위 확인이며 I2 전체 source별 provenance·conflict rate 또는 전 권역 coverage 감사가 아니다. 해당 상세 감사는 별도 승인된 scope에서 수행한다. synthetic test는 conflict, address ambiguity, visit-only fail-closed, valid-coordinate non-use, train-unseen static inventory를 확인한다.

## 좌표와 privacy

이 코드 경로는 X/Y를 geometry로 해석하지 않고 feature/API에도 내보내지 않는다. Issue #69의 공개 aggregate는 anchor subset에서 좌표가 WGS84 범위에 들고 거리가 일치했음을 보였지만, 전체 Master inventory의 좌표 source contract와 coverage를 확인한 것은 아니다. 그러므로 subset 결과를 전체 정적 item 위치로 일반화하지 않는다. 좌표, H3 cell, 거리, `TN_GPS_COORD`는 ranking feature allowlist에서 차단한다. Manifest와 PR에는 원시 ID, 주소, 좌표, 입력 경로 대신 상태 종류와 안전한 합계만 기록한다.

## 재현 및 검증

```bash
python3 -m unittest tests.test_canonical_admin_location tests.test_training_dataset tests.test_training_data_contract
python3 -m unittest tests.test_catboost_ranking_experiment
```

실제 데이터 경로가 승인되고 source/role 검증이 완료되면 `scripts/recommendation/training_dataset.py`가 `item_features.parquet`와 `manifest.json`을 생성한다. 출력은 Git-ignored 결과 위치에만 두며, 공유 시에도 행/ID/주소/좌표는 포함하지 않는다.
