import hashlib
import json
import re
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

FEATURE_VERSION = "latency-v2-budget"


def profile_key(path, config):
    # Load is a measured workload control; seed/severity/release are not model inputs.
    profile = {
        key: config[key]
        for key in (
            "concurrency",
            "probes_per_window",
            "timeout_seconds",
            "load",
            "contract_version",
        )
    }
    raw = json.dumps([path, profile, FEATURE_VERSION], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def features(stats):
    if stats["counts"]["OK"] < 20 or sum(stats["counts"].values()) != stats["counts"]["OK"]:
        return None
    return np.log1p([stats["p50_ms"], stats["p95_ms"], stats["spread_ms"]])


def fit_model(training, validation, path, config, destination, run_ids):
    if len(training) < 20 or len(validation) < 5:
        raise ValueError("Need at least 20 healthy training and 5 validation windows")
    train_x = np.asarray(training)
    validation_x = np.asarray(validation)
    model = IsolationForest(n_estimators=100, random_state=42, contamination="auto")
    model.fit(train_x)
    # Higher anomaly value means more unusual. Use a held-out healthy false-alert budget.
    validation_scores = -model.score_samples(validation_x)
    threshold = float(np.quantile(validation_scores, 0.95))
    reference = np.median(train_x, axis=0)
    scale = np.maximum(np.median(np.abs(train_x - reference), axis=0), 0.03)
    baseline_scores = np.max(np.maximum((validation_x - reference) / scale, 0), axis=1)
    baseline_threshold = float(np.quantile(baseline_scores, 0.95))
    key = profile_key(path, config)
    version = hashlib.sha256(json.dumps([run_ids, key], sort_keys=True).encode()).hexdigest()[:12]
    bundle = {
        "model": model,
        "threshold": threshold,
        "baseline_reference": reference,
        "baseline_scale": scale,
        "baseline_threshold": baseline_threshold,
        "reference_p95_ms": float(np.expm1(reference[1])),
        "minimum_increase_ms": 10.0,
        "minimum_increase_ratio": 0.30,
        "version": version,
        "feature_version": FEATURE_VERSION,
        "path": path,
        "profile_key": key,
        "training_run_ids": run_ids["training"],
        "validation_run_ids": run_ids["validation"],
    }
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / f"{key}-{version}.joblib"
    joblib.dump(bundle, artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    # Registry points only to local project-generated artifacts; no upload/deserialization API.
    (folder / f"{key}.json").write_text(
        json.dumps(
            {
                "file": artifact.name,
                "sha256": digest,
                "version": version,
                "feature_version": FEATURE_VERSION,
            },
            indent=2,
        )
    )
    return bundle


def load_model(path, config, destination):
    key = profile_key(path, config)
    folder = Path(destination)
    registry = folder / f"{key}.json"
    if not registry.exists():
        return None
    metadata = json.loads(registry.read_text())
    filename = metadata["file"]
    if not re.fullmatch(r"[a-f0-9]{20}-[a-f0-9]{12}\.joblib", filename):
        raise ValueError("Invalid local model filename")
    artifact = folder / filename
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("Model checksum mismatch")
    bundle = joblib.load(artifact)
    if bundle["profile_key"] != key or bundle["feature_version"] != FEATURE_VERSION:
        raise ValueError("Model profile mismatch")
    return bundle


def predict(bundle, stats):
    vector = features(stats)
    if vector is None:
        return None
    score = float(-bundle["model"].score_samples([vector])[0])
    baseline = float(
        np.max(np.maximum((vector - bundle["baseline_reference"]) / bundle["baseline_scale"], 0))
    )
    # A novelty score alone can overreact to harmless scheduling noise.
    # Apply the same predeclared practical latency budget to both methods.
    reference = bundle["reference_p95_ms"]
    meaningful = stats["p95_ms"] - reference > max(
        bundle["minimum_increase_ms"], reference * bundle["minimum_increase_ratio"]
    )
    raw_ml = score > bundle["threshold"]
    raw_baseline = baseline > bundle["baseline_threshold"]
    return {
        "score": score,
        "raw_ml": raw_ml,
        "raw_baseline": raw_baseline,
        "meaningful_change": meaningful,
        "anomaly": raw_ml and meaningful,
        "baseline_anomaly": raw_baseline and meaningful,
    }
