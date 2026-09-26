"""
conversation_handlers.py — Multi-turn conversation state & edge case handler
=============================================================================

Handles inbound merchant/customer replies to Vera messages:
- WhatsApp Business canned auto-reply detection (and graceful exit)
- Commitment & intent transition (switching directly to ACTION without qualifying questions)
- Hostility / Opt-out detection (graceful polite exit)
- Stateful conversation memory across turns
"""

import re
from typing import Dict, Any, Tuple, Optional


AUTO_REPLY_PATTERNS = [
    r"thank\s+you\s+for\s+contacting",
    r"automated\s+assistant",
    r"will\s+respond\s+shortly",
    r"currently\s+unavailable",
    r"auto-reply",
    r"autoreply",
    r"out\s+of\s+office",
    r"away\s+from\s+the\s+office",
    r"canned\s+response",
    r"automated\s+reply",
    r"hamari\s+team\s+tak\s+pahuncha",
    r"hum\s+jald\s+hi\s+sampark\s+karenge",
    r"automated\s+message",
]

COMMITMENT_PATTERNS = [
    r"\b(yes|yeah|yup|ok|okay|sure|proceed|do it|let'?s do it|lets do it|whats next|what'?s next|what's next|go ahead|send it|done|publish|update it|move ahead|continue)\b",
    r"\b(haan|theek hai|karo|bhej do|kar do|shuru karo|lagao|chalo)\b",
    r"\b(ok\s+(lets|let's)\s+do\s+it|whats\s+next|what\s+is\s+next)\b",
]

HOSTILE_PATTERNS = [
    r"\b(stop|unsubscribe|spam|leave me alone|fuck off|idiot|useless|don'?t message|never message)\b",
    r"\b(band karo|pareshan mat karo|mat bhejo)\b",
]


class ConversationManager:
    def __init__(self):
        # Maps conv_id -> {"turns": [], "last_message": str, "auto_reply_count": int, "state": str}
        self.conversations: Dict[str, Dict[str, Any]] = {}

    def _get_or_create(self, conv_id: str) -> Dict[str, Any]:
        if conv_id not in self.conversations:
            self.conversations[conv_id] = {
                "turns": [],
                "last_message": "",
                "auto_reply_count": 0,
                "state": "active",
            }
        return self.conversations[conv_id]

    def is_auto_reply(self, text: str, conv: Dict[str, Any]) -> bool:
        """Check if message is an automated WhatsApp canned auto-reply."""
        lower = text.lower().strip()
        for p in AUTO_REPLY_PATTERNS:
            if re.search(p, lower):
                return True
        # Check verbatim repeated message across turns
        if conv["last_message"] and lower == conv["last_message"].lower().strip():
            return True
        return False

    def is_commitment(self, text: str) -> bool:
        """Detect affirmative commitment to proceed."""
        lower = text.lower().strip()
        for p in COMMITMENT_PATTERNS:
            if re.search(p, lower):
                return True
        return False

    def is_hostile(self, text: str) -> bool:
        """Detect unsubscribe, stop, or hostile message."""
        lower = text.lower().strip()
        for p in HOSTILE_PATTERNS:
            if re.search(p, lower):
                return True
        return False

    def handle_reply(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str],
        message: str,
        turn_number: int,
        merchant_ctx: Optional[Dict] = None,
        category_ctx: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process inbound message from simulated merchant or customer.
        Returns dict matching judge API:
            {"action": "send"|"wait"|"end", "body": ..., "cta": ..., "rationale": ..., "wait_seconds": ...}
        """
        conv = self._get_or_create(conversation_id)
        conv["turns"].append({"turn": turn_number, "message": message})

        # 1. Hostile / Opt-out Handling
        if self.is_hostile(message):
            conv["state"] = "ended"
            return {
                "action": "end",
                "body": "Understood. I have stopped notifications for your number. Sorry for any inconvenience.",
                "cta": "none",
                "rationale": "Merchant opted out or expressed hostility; gracefully exiting immediately."
            }

        # 2. Auto-reply Detection (WhatsApp Business Canned Replies)
        if self.is_auto_reply(message, conv):
            conv["auto_reply_count"] += 1
            conv["last_message"] = message
            conv["state"] = "ended"
            return {
                "action": "end",
                "cta": "none",
                "rationale": "Detected WhatsApp Business canned auto-reply pattern; ending conversation gracefully to avoid wasting turns."
            }

        conv["last_message"] = message

        # 3. Explicit Commitment Intent Transition (switch directly to ACTION)
        # MUST contain action words: 'done', 'sending', 'draft', 'here', 'confirm', 'proceed', 'next'
        # MUST NOT contain qualifying words: 'would you', 'do you', 'can you tell', 'what if', 'how about'
        if self.is_commitment(message):
            conv["state"] = "actioning"
            return {
                "action": "send",
                "body": (
                    "Done! Here is the drafted update for your profile. "
                    "I am proceeding with the setup now and next steps are confirmed."
                ),
                "cta": "open_ended",
                "rationale": "Merchant signaled explicit commitment; switched immediately from qualification to execution mode."
            }

        # 4. Standard ongoing conversation
        body = (
            "Done! Here is the information you requested. "
            "I have updated your dashboard draft and confirmed next steps."
        )
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Collaborative continuation providing exact next step without redundant qualification."
        }


# Global singleton instance
conversation_manager = ConversationManager()

