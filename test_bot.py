"""
test_bot.py — Comprehensive Automated Test Suite for Vera Candidate Bot
========================================================================

Tests:
1. /v1/healthz endpoint
2. /v1/metadata endpoint
3. /v1/context ingestion (category, merchant, customer, trigger) and version conflicts
4. /v1/tick proactive generation and compose verification
5. /v1/reply multi-turn handling:
   - Auto-reply detection and graceful exit
   - Commitment / intent transition to ACTION mode (zero qualifying words)
   - Hostility and opt-out handling
6. submission.jsonl validation (30 canonical pairs)
"""

import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Ensure Windows terminal doesn't crash on Rupee sign ₹
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOT_URL = "http://localhost:8080"


def http_req(method: str, path: str, data: dict = None):
    url = f"{BOT_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_suite():
    passed = 0
    failed = 0

    print("\n--- 1. TESTING /v1/healthz ---")
    status, data = http_req("GET", "/v1/healthz")
    assert status == 200, f"Expected 200, got {status}"
    assert data["status"] == "ok"
    print(f"[PASS] healthz returned: {data}")
    passed += 1

    print("\n--- 2. TESTING /v1/metadata ---")
    status, data = http_req("GET", "/v1/metadata")
    assert status == 200, f"Expected 200, got {status}"
    assert "team_name" in data and "model" in data
    print(f"[PASS] metadata returned team: {data['team_name']}, model: {data['model']}")
    passed += 1

    print("\n--- 3. TESTING /v1/context INGESTION & VERSIONING ---")
    # Ingest category
    cat_payload = {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
    status, data = http_req("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": cat_payload, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert status == 200 and data["accepted"] is True
    print("[PASS] Category context ingested")
    passed += 1

    # Stale version test (expect 409)
    status, data = http_req("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 0,
        "payload": cat_payload, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert status == 409 and data["accepted"] is False and data["reason"] == "stale_version"
    print("[PASS] Stale version correctly rejected with 409")
    passed += 1

    # Idempotent re-post of same version (expect 200)
    status, data = http_req("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": cat_payload, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert status == 200 and data["accepted"] is True
    print("[PASS] Idempotent version re-post accepted with 200")
    passed += 1

    print("\n--- 4. TESTING /v1/tick & PROACTIVE COMPOSITION ---")
    # Ingest merchant and trigger
    merchant_payload = {
        "merchant_id": "m_test_dentist",
        "category_slug": "dentists",
        "identity": {"name": "Test Dental Care", "owner_first_name": "Meera", "locality": "Lajpat Nagar", "languages": ["en"]},
        "performance": {"views": 1500, "calls": 20, "ctr": 0.025, "delta_7d": {"views_pct": 0.25}},
        "offers": [{"id": "o1", "title": "Dental Cleaning @ ₹299", "status": "active"}]
    }
    http_req("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_test_dentist", "version": 1,
        "payload": merchant_payload, "delivered_at": "2026-04-26T10:00:00Z"
    })

    trigger_payload = {
        "id": "trg_test_spike",
        "scope": "merchant",
        "kind": "perf_spike",
        "merchant_id": "m_test_dentist",
        "payload": {"delta_pct": 0.25},
        "urgency": 2,
        "suppression_key": "supp_test_spike"
    }
    http_req("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_test_spike", "version": 1,
        "payload": trigger_payload, "delivered_at": "2026-04-26T10:00:00Z"
    })

    status, data = http_req("POST", "/v1/tick", {"now": "2026-04-26T10:00:00Z", "available_triggers": ["trg_test_spike"]})
    assert status == 200
    actions = data.get("actions", [])
    assert len(actions) == 1
    action = actions[0]
    print(f"[PASS] Action generated: send_as={action['send_as']}, cta={action['cta']}")
    print(f"       Body: {action['body']}")
    passed += 1

    print("\n--- 5. TESTING /v1/reply (AUTO-REPLY, INTENT, HOSTILE) ---")
    # 5a. Auto-reply hell
    auto_reply_msg = "Thank you for contacting us! Our team will respond shortly."
    status, data = http_req("POST", "/v1/reply", {
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_dentist",
        "message": auto_reply_msg,
        "turn_number": 1
    })
    assert data["action"] == "end", f"Expected 'end', got {data.get('action')}"
    print(f"[PASS] Auto-reply correctly ended: {data}")
    passed += 1

    # 5b. Intent transition to action (must have action words, NO qualifying words)
    commitment_msg = "Ok lets do it. Whats next?"
    status, data = http_req("POST", "/v1/reply", {
        "conversation_id": "conv_intent_test",
        "merchant_id": "m_test_dentist",
        "message": commitment_msg,
        "turn_number": 2
    })
    assert data["action"] == "send"
    body_lower = data.get("body", "").lower()
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    assert any(w in body_lower for w in actioning), "Missing action words in commitment response"
    assert not any(w in body_lower for w in qualifying), "Qualifying words found after commitment"
    print(f"[PASS] Intent transition switched to ACTION mode: {data['body']}")
    passed += 1

    # 5c. Hostile message handling
    hostile_msg = "Stop messaging me. This is useless spam."
    status, data = http_req("POST", "/v1/reply", {
        "conversation_id": "conv_hostile_test",
        "merchant_id": "m_test_dentist",
        "message": hostile_msg,
        "turn_number": 1
    })
    assert data["action"] == "end"
    print(f"[PASS] Hostile message correctly ended: {data}")
    passed += 1

    print("\n--- 6. VALIDATING submission.jsonl ---")
    sub_path = Path("submission.jsonl")
    assert sub_path.exists(), "submission.jsonl not found!"
    lines = [line.strip() for line in sub_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    assert len(lines) == 30, f"Expected 30 lines, found {len(lines)}"

    required_keys = {"test_id", "body", "cta", "send_as", "suppression_key", "rationale"}
    for idx, line in enumerate(lines, start=1):
        obj = json.loads(line)
        assert required_keys.issubset(obj.keys()), f"Missing keys in line {idx}: {obj}"
        assert obj["test_id"] == f"T{idx:02d}", f"Expected T{idx:02d}, got {obj['test_id']}"
        assert len(obj["body"]) > 20, f"Body too short in T{idx:02d}"
        assert obj["send_as"] in ["vera", "merchant_on_behalf"], f"Invalid send_as in T{idx:02d}"

    print(f"[PASS] submission.jsonl is 100% valid with all 30 canonical test cases (T01 - T30)!")
    passed += 1

    print(f"\n==========================================")
    print(f" ALL {passed} TESTS PASSED SUCCESSFULLY! ")
    print(f"==========================================\n")


if __name__ == "__main__":
    test_suite()
