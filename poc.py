import json
import math
from pathlib import Path

ALLOW_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.60
MIN_MARGIN = 0.10
MIN_QUALITY = 0.65
MIN_LIVENESS = 0.80

AUDIT_FILE = Path("access_events.jsonl")

EMPLOYEES = {
    "emp-4821": {"embedding": [1.0, 0.0, 0.0], "access_allowed": True},
    "emp-1024": {"embedding": [0.0, 1.0, 0.0], "access_allowed": True},
}


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb)


def search_candidates(query_embedding):
    scores = []

    for employee_id, data in EMPLOYEES.items():
        score = cosine_similarity(query_embedding, data["embedding"])
        scores.append((employee_id, score))

    return sorted(scores, key=lambda x: x[1], reverse=True)


def write_audit(result):
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def verify_access(event):
    decision = "manual_review"
    employee_id = None
    match_score = None
    margin = None
    reasons = []

    quality = event["quality_score"]
    liveness = event["liveness_score"]

    if quality < MIN_QUALITY:
        reasons.append("low_quality")

    elif liveness < MIN_LIVENESS:
        reasons.append("suspicious_liveness")

    elif (
        event.get("network") == "offline"
        and event.get("cache_age_minutes", 0) > 60
    ):
        reasons.append("offline_cache_too_old")

    else:
        candidates = search_candidates(event["embedding"])

        employee_id = candidates[0][0]
        match_score = candidates[0][1]
        second_score = candidates[1][1]
        margin = match_score - second_score

        if (
            match_score >= ALLOW_THRESHOLD
            and margin >= MIN_MARGIN
            and EMPLOYEES[employee_id]["access_allowed"]
        ):
            decision = "allow"
            reasons.append("confident_match")

        elif match_score >= REVIEW_THRESHOLD:
            decision = "manual_review"
            reasons.append("ambiguous_match")

        else:
            decision = "deny"
            reasons.append("match_too_low")

    result = {
        "event_id": event["event_id"],
        "decision": decision,
        "employee_id": employee_id,
        "match_score": match_score,
        "margin_to_second_best": margin,
        "reasons": reasons,
        "turnstile_command": "open" if decision == "allow" else "keep_closed",
        "requires_human_review": decision == "manual_review",
    }

    write_audit(result)
    return result


def run_demo():
    happy_event = {
        "event_id": "e-happy-001",
        "quality_score": 0.90,
        "liveness_score": 0.95,
        "embedding": [0.99, 0.02, 0.01],
        "network": "online",
        "cache_age_minutes": 5,
    }

    risky_event = {
        "event_id": "e-risky-001",
        "quality_score": 0.92,
        "liveness_score": 0.96,
        "embedding": [0.99, 0.02, 0.01],
        "network": "offline",
        "cache_age_minutes": 240,
    }

    happy = verify_access(happy_event)
    risky = verify_access(risky_event)

    print("=== HAPPY PATH ===")
    print(json.dumps(happy, indent=2, ensure_ascii=False))

    print("\n=== RISKY PATH ===")
    print(json.dumps(risky, indent=2, ensure_ascii=False))

    assert happy["decision"] == "allow"
    assert happy["turnstile_command"] == "open"

    assert risky["decision"] == "manual_review"
    assert risky["turnstile_command"] == "keep_closed"

    print("\nSmoke tests: PASSED")


if __name__ == "__main__":
    run_demo()
