"""
Minimal PoC: Face Access Decision System

Это демонстрация decision layer архитектуры.
CV-компоненты (quality, liveness и embeddings) замоканы.
В production они заменяются реальными pretrained CV-моделями.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path


# -----------------------------
# Demo configuration
# -----------------------------

ALLOW_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.60
MIN_MARGIN = 0.10
MIN_QUALITY = 0.65
MIN_LIVENESS = 0.80

AUDIT_FILE = Path("access_events.jsonl")


# -----------------------------
# Mock employee database
# -----------------------------

EMPLOYEES = {
    "emp-4821": {
        "embedding": [1.0, 0.0, 0.0],
        "access_allowed": True,
    },
    "emp-1024": {
        "embedding": [0.0, 1.0, 0.0],
        "access_allowed": True,
    },
    "emp-9000": {
        "embedding": [0.0, 0.0, 1.0],
        "access_allowed": False,
    },
}


# -----------------------------
# Utilities
# -----------------------------

def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def search_candidates(query_embedding):
    """
    Mock exact search.

    Production:
    FAISS/HNSW ANN index instead of full scan.
    """
    scores = []

    for employee_id, employee in EMPLOYEES.items():
        score = cosine_similarity(
            query_embedding,
            employee["embedding"],
        )
        scores.append((employee_id, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:2]


def write_audit(event):
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# -----------------------------
# Decision Engine
# -----------------------------

def verify_access(event):
    started_at = datetime.now(timezone.utc)

    event_id = event["event_id"]

    quality = event["quality_score"]
    liveness = event["liveness_score"]
    network = event.get("network", "online")
    cache_age = event.get("cache_age_minutes", 0)

    reasons = []
    degraded_mode = network != "online"

    decision = "manual_review"
    employee_id = None
    match_score = None
    margin = None

    # 1. Quality gate
    if quality < MIN_QUALITY:
        reasons.append("quality_below_threshold")

    # 2. Liveness gate
    elif liveness < MIN_LIVENESS:
        reasons.append("liveness_suspicious")

    # 3. Offline safety
    elif degraded_mode and cache_age > 60:
        reasons.append("offline_cache_too_old")

    else:
        candidates = search_candidates(event["embedding"])

        employee_id, match_score = candidates[0]
        second_score = candidates[1][1]

        margin = match_score - second_score

        employee = EMPLOYEES[employee_id]

        if not employee["access_allowed"]:
            decision = "deny"
            reasons.append("access_policy_denied")

        elif (
            match_score >= ALLOW_THRESHOLD
            and margin >= MIN_MARGIN
        ):
            decision = "allow"
            reasons.extend([
                "quality_ok",
                "liveness_ok",
                "match_above_allow_threshold",
                "margin_ok",
                "access_policy_ok",
            ])

        elif match_score >= REVIEW_THRESHOLD:
            decision = "manual_review"
            reasons.append("ambiguous_match")

        else:
            decision = "deny"
            reasons.append("match_below_review_threshold")

    # Safety rule:
    # only explicit allow may open the turnstile.
    turnstile_command = (
        "open" if decision == "allow" else "keep_closed"
    )

    finished_at = datetime.now(timezone.utc)

    latency_ms = int(
        (finished_at - started_at).total_seconds() * 1000
    )

    result = {
        "event_id": event_id,
        "decision_id": f"decision-{event_id}",
        "decision": decision,
        "employee_id": employee_id,
        "match_score": (
            round(match_score, 4)
            if match_score is not None else None
        ),
        "margin_to_second_best": (
            round(margin, 4)
            if margin is not None else None
        ),
        "quality": {
            "quality_score": quality,
            "liveness_score": liveness,
        },
        "reasons": reasons,
        "turnstile_command": turnstile_command,
        "requires_human_review": decision == "manual_review",
        "degraded_mode": degraded_mode,
        "latency_ms": latency_ms,
        "processed_at": finished_at.isoformat(),
    }

    write_audit(result)

    return result


# -----------------------------
# Demo scenarios
# -----------------------------

def run_demo():

    # Happy path:
    # good quality + live person + confident employee match.
    happy_event = {
        "event_id": "e-happy-001",
        "gate_id": "gate-2",
        "camera_id": "cam-2a",
        "quality_score": 0.91,
        "liveness_score": 0.96,
        "embedding": [0.98, 0.05, 0.01],
        "network": "online",
        "cache_age_minutes": 5,
    }

    # Risky path:
    # network unavailable and employee cache is stale.
    # Even with an excellent face match, automatic access is forbidden.
    risky_event = {
        "event_id": "e-risky-001",
        "gate_id": "gate-1",
        "camera_id": "cam-1a",
        "quality_score": 0.93,
        "liveness_score": 0.97,
        "embedding": [0.99, 0.02, 0.01],
        "network": "offline",
        "cache_age_minutes": 240,
    }

    print("\n=== HAPPY PATH ===")
    happy_result = verify_access(happy_event)
    print(json.dumps(happy_result, indent=2, ensure_ascii=False))

    print("\n=== RISKY / FALLBACK PATH ===")
    risky_result = verify_access(risky_event)
    print(json.dumps(risky_result, indent=2, ensure_ascii=False))

    # Minimal smoke tests
    assert happy_result["decision"] == "allow"
    assert happy_result["turnstile_command"] == "open"

    assert risky_result["decision"] == "manual_review"
    assert risky_result["turnstile_command"] == "keep_closed"
    assert risky_result["requires_human_review"] is True

    print("\nSmoke tests: PASSED")
    print(f"Audit log: {AUDIT_FILE}")


if __name__ == "__main__":
    run_demo()
