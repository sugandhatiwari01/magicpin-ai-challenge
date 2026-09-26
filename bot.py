"""
bot.py — Candidate Bot HTTP Server & Evaluation Service for magicpin AI Challenge
=================================================================================

Implements all 5 testing endpoints:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context
- POST /v1/tick
- POST /v1/reply

Also exports:
    compose(category, merchant, trigger, customer=None) -> dict
"""

import os
import sys
import time
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify

# Import the composition engine and multi-turn conversation manager
from composer import compose as core_compose
from conversation_handlers import conversation_manager

app = Flask(__name__)
START_TIME = time.time()

# Dataset root directory for fallback lookup
BASE_DIR = Path(__file__).parent.resolve()
EXPANDED_DATASET_DIR = BASE_DIR / "dataset" / "expanded"

# In-memory context storage: (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[tuple, Dict[str, Any]] = {}


def compose(category: Dict, merchant: Dict, trigger: Dict, customer: Optional[Dict] = None) -> Dict[str, Any]:
    """Top-level compose interface matching challenge-brief.md §7.1."""
    return core_compose(category, merchant, trigger, customer)


def _get_context(scope: str, context_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve context from in-memory cache, falling back to disk if needed."""
    key = (scope, context_id)
    if key in contexts:
        return contexts[key]["payload"]

    # Fallback to expanded dataset directory
    if EXPANDED_DATASET_DIR.exists():
        sub_dir = {
            "category": "categories",
            "merchant": "merchants",
            "customer": "customers",
            "trigger": "triggers",
        }.get(scope)

        if sub_dir:
            file_path = EXPANDED_DATASET_DIR / sub_dir / f"{context_id}.json"
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        contexts[key] = {"version": 1, "payload": data}
                        return data
                except Exception:
                    pass
    return None


@app.route("/v1/healthz", methods=["GET"])
def healthz():
    """Liveness probe returning counts of loaded contexts."""
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }), 200


@app.route("/v1/metadata", methods=["GET"])
def metadata():
    """Bot identity and technical summary."""
    return jsonify({
        "team_name": "Vera AI Team",
        "team_members": ["Lead Engineer"],
        "model": "vera-hybrid-composer",
        "approach": "4-context modular composer with zero-hallucination specificity anchors, category taboos, and intent state machine",
        "contact_email": "vera@magicpin.in",
        "version": "2.0.0",
        "submitted_at": "2026-04-26T12:00:00Z"
    }), 200


@app.route("/v1/context", methods=["POST"])
def push_context():
    """Receive and store context updates with strict version control."""
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"accepted": False, "reason": "invalid_json"}), 400

    scope = body.get("scope")
    context_id = body.get("context_id")
    version = body.get("version", 1)
    payload = body.get("payload")

    if not scope or not context_id or payload is None:
        return jsonify({"accepted": False, "reason": "missing_required_fields"}), 400

    key = (scope, context_id)
    cur = contexts.get(key)

    if cur:
        if cur["version"] > version:
            return jsonify({
                "accepted": False,
                "reason": "stale_version",
                "current_version": cur["version"]
            }), 409
        # Idempotent re-post of same version
        if cur["version"] == version:
            return jsonify({
                "accepted": True,
                "ack_id": f"ack_{context_id}_{version}",
                "stored_at": datetime.utcnow().isoformat() + "Z"
            }), 200

    # Newer version or first time insertion
    contexts[key] = {
        "version": version,
        "payload": payload,
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }

    return jsonify({
        "accepted": True,
        "ack_id": f"ack_{context_id}_{version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }), 200


@app.route("/v1/tick", methods=["POST"])
def tick():
    """Periodic tick evaluation: compose proactive messages for active triggers."""
    body = request.get_json(force=True, silent=True) or {}
    triggers_list = body.get("available_triggers", [])
    actions = []

    for tid in triggers_list:
        trigger_payload = _get_context("trigger", tid)
        if not trigger_payload:
            continue

        merchant_id = trigger_payload.get("merchant_id") or trigger_payload.get("payload", {}).get("merchant_id")
        customer_id = trigger_payload.get("customer_id") or trigger_payload.get("payload", {}).get("customer_id")

        # Resolve merchant context
        merchant = _get_context("merchant", merchant_id) if merchant_id else {}
        if not merchant and contexts:
            # Fallback to any loaded merchant if testing with mock ids
            for (s, mid), c_data in contexts.items():
                if s == "merchant":
                    merchant = c_data["payload"]
                    merchant_id = mid
                    break

        cat_slug = merchant.get("category_slug", "dentists") if merchant else "dentists"
        category = _get_context("category", cat_slug) or {}

        # Resolve customer context if present
        customer = _get_context("customer", customer_id) if customer_id else None

        # Compose message
        composed = compose(category, merchant, trigger_payload, customer)

        conv_id = f"conv_{tid}_{uuid.uuid4().hex[:6]}"
        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": tid,
            "template_name": f"vera_{cat_slug}_v1",
            "template_params": [composed.get("body", "")],
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "binary_yes_stop"),
            "suppression_key": composed.get("suppression_key", f"supp_{tid}"),
            "rationale": composed.get("rationale", "")
        }
        actions.append(action)

    return jsonify({"actions": actions}), 200


@app.route("/v1/reply", methods=["POST"])
def reply():
    """Multi-turn response handler: auto-reply detection, commitment, and hostility."""
    body = request.get_json(force=True, silent=True) or {}
    conv_id = body.get("conversation_id", "conv_default")
    merchant_id = body.get("merchant_id", "")
    customer_id = body.get("customer_id")
    message = body.get("message", "")
    turn_number = body.get("turn_number", 1)

    result = conversation_manager.handle_reply(
        conversation_id=conv_id,
        merchant_id=merchant_id,
        customer_id=customer_id,
        message=message,
        turn_number=turn_number
    )
    return jsonify(result), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

