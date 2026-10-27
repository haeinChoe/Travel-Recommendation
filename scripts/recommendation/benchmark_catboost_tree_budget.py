"""Synthetic-only reproducible study; never opens AI Hub inputs."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from scripts.recommendation.catboost_ranking_experiment import (
    ExperimentConfig, PreparedItemCatalog, fit_catboost,
    materialize_inner_train_item_features,
)
from scripts.recommendation.tree_budget import run_tree_budget_sweep


def main():
    config = ExperimentConfig(
        ('Q4_TEMPORAL', 'I2_ADMINISTRATIVE_LOCATION', 'I3_POPULARITY', 'I4_HISTORICAL_POI'),
        seed=20261025, iterations=1000, k_values=(5, 10, 20),
    )
    owners = {f'q{n}': f'u{n}' for n in range(40)}
    items = [{
        'item_id': f'i{n:05}', 'region': 'capital',
        'canonical_admin_sido_code': '11', 'canonical_admin_sgg_code': str(n % 20),
        'canonical_admin_location_status': 'resolved_single_source',
    } for n in range(2048)]
    interactions = [{'TRAVEL_ID': q, 'POI_ID': f'i{n:05}',
                     'observed_positive': 1, 'source_split': 'TL'}
                    for n, q in enumerate(owners)]
    events = [{**row, 'VISIT_AREA_TYPE_CD': '1'} for row in interactions]
    materialized = materialize_inner_train_item_features(
        trip_owner=owners, item_features=items, positive_interactions=interactions,
        visit_events=events, split_seed=20261025,
    )
    catalog = PreparedItemCatalog.from_materialization(materialized, config, region='capital')
    by_item = {row['item_id']: row for row in materialized.item_features}
    contexts = {q: {'region': 'capital', 'start_month': str(n % 12 + 1), 'elapsed_days': n % 5 + 1}
                for n, q in enumerate(owners)}
    rows, truths = [], []
    for n, q in enumerate(owners):
        positive = f'i{n:05}'
        if materialized.partition_by_trip[q] == 'inner-validation':
            truths.append((q, (positive,)))
            continue
        for item, label in ((positive, 1), (f'i{n+100:05}', 0)):
            rows.append({**dict(by_item[item]), **contexts[q],
                         'trip_id': q, 'group': q, 'label': label})
    model = fit_catboost(
        pd.DataFrame(rows), label_column='label', group_column='group', config=config,
        train_derived_source_scope='inner-train', inner_train_materialization=materialized,
    )
    output = Path('results/issue-82/tree-budget/synthetic-profile.json')
    if subprocess.run(['git', 'check-ignore', '-q', str(output)], check=False).returncode:
        raise RuntimeError('Output must be Git ignored')
    result = {'scope': 'synthetic_only_not_actual_TL', 'catboost_version': '1.2.10',
              'runs': run_tree_budget_sweep(model, catalog, lambda: iter(truths),
                                           query_features=contexts, config=config)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    verified = json.loads(output.read_text())
    assert len(verified['runs']) == 5
    for row in verified['runs']:
        assert len(row['metrics']) == 12 and row['scored_rows'] == 2048 * len(truths)
        print(json.dumps(row))


if __name__ == '__main__':
    main()
