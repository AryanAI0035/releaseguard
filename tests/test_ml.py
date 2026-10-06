import json

import numpy as np
import pytest

from releaseguard.ml import features, fit_model, load_model, predict, profile_key
from scripts.evaluate import metrics
from scripts.train import validate_manifest

CONFIG = {
    "concurrency": 5,
    "probes_per_window": 25,
    "timeout_seconds": 0.3,
    "load": 1.0,
    "contract_version": "1",
}


def healthy_stats():
    return {
        "counts": {
            "OK": 25,
            "HTTP_ERROR": 0,
            "TIMEOUT": 0,
            "NETWORK_ERROR": 0,
            "CONTRACT_FAILURE": 0,
        },
        "p50_ms": 15.0,
        "p95_ms": 20.0,
        "spread_ms": 3.0,
    }


def test_ml_abstains_for_censored_or_insufficient_samples():
    stats = healthy_stats()
    assert features(stats) is not None
    stats["counts"]["TIMEOUT"] = 1
    assert features(stats) is None
    stats["counts"]["TIMEOUT"] = 0
    stats["counts"]["OK"] = 5
    assert features(stats) is None


def test_artifact_round_trip_and_score_semantics(tmp_path):
    rng = np.random.default_rng(42)
    training = rng.normal([2.8, 3.0, 1.4], 0.04, (40, 3))
    validation = rng.normal([2.8, 3.0, 1.4], 0.04, (10, 3))
    bundle = fit_model(
        training,
        validation,
        "/products",
        CONFIG,
        tmp_path,
        {"training": list(range(10)), "validation": [11, 12]},
    )
    loaded = load_model("/products", CONFIG, tmp_path)
    assert loaded["version"] == bundle["version"]
    result = predict(loaded, healthy_stats())
    assert result["raw_ml"] == (result["score"] > loaded["threshold"])
    assert result["anomaly"] == (result["raw_ml"] and result["meaningful_change"])
    assert result["anomaly"] is False  # Healthy reference is inside the practical budget.
    assert load_model("/products", {**CONFIG, "concurrency": 1}, tmp_path) is None
    metadata = json.loads((tmp_path / f"{profile_key('/products', CONFIG)}.json").read_text())
    (tmp_path / metadata["file"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_model("/products", CONFIG, tmp_path)


def test_fault_labels_and_release_names_are_not_features():
    assert profile_key("/products", CONFIG) == profile_key(
        "/products", {**CONFIG, "variant": "broken", "seed": 123, "severity": 3}
    )


def test_partition_overlap_and_faulty_training_are_rejected():
    with pytest.raises(ValueError, match="disjoint"):
        validate_manifest(
            {
                "experiments": [
                    {"run_id": 1, "partition": "training", "variant": "healthy"},
                    {"run_id": 1, "partition": "test", "variant": "healthy"},
                ]
            }
        )
    with pytest.raises(ValueError, match="healthy"):
        validate_manifest(
            {
                "experiments": [
                    {"run_id": 1, "partition": "training", "variant": "slow-query"},
                ]
            }
        )


def test_metrics_include_abstentions_and_false_alert_denominator():
    result = metrics(
        [
            {"fault": True, "ml": True},
            {"fault": False, "ml": True},
            {"fault": False, "ml": False},
            {"fault": True, "ml": None},
        ],
        "ml",
    )
    assert result["abstained"] == 1
    assert result["precision"] == 0.5
    assert result["healthy_false_alert_rate"] == 0.5
