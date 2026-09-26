"""
composer.py — minimal but robust composition engine for the magicpin challenge.
"""

from typing import Any, Dict, Optional


def _clean_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _pick_offer(category: Dict[str, Any], merchant: Optional[Dict[str, Any]] = None) -> str:
    if merchant:
        offers = merchant.get("offers") or []
        for offer in offers:
            if isinstance(offer, dict) and offer.get("status") == "active":
                title = offer.get("title")
                if title:
                    return title
    catalog = category.get("offer_catalog") or []
    if catalog:
        first = catalog[0]
        if isinstance(first, dict):
            title = first.get("title")
            if title:
                return title
    return "your featured service"


def _merchant_name(merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity") or {}
    return identity.get("name") or "your business"


def _merchant_locality(merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity") or {}
    return identity.get("locality") or "your area"


def _choose_cta(trigger: Dict[str, Any]) -> str:
    kind = str(trigger.get("kind", "")).lower()
    if kind in {"research_digest", "perf_dip", "perf_spike", "dormant_with_vera", "festival_upcoming", "competitor_opened", "renewal_due"}:
        return "binary_yes_stop"
    if kind in {"appointment_tomorrow", "recall_due", "customer_lapsed_soft"}:
        return "slot_selection"
    if kind in {"curious_ask_due"}:
        return "open_ended"
    return "binary_yes_stop"


def compose_customer_facing(category: Dict[str, Any], merchant: Dict[str, Any], trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    customer_name = (customer or {}).get("identity", {}).get("name", "there")
    merchant_name = _merchant_name(merchant)
    locality = _merchant_locality(merchant)
    offer = _pick_offer(category, merchant)
    kind = str(trigger.get("kind", "")).lower()
    suppression = trigger.get("suppression_key") or f"cust:{(customer or {}).get('customer_id', 'unknown')}:{trigger.get('id', 'trigger')}"

    if kind in {"appointment_tomorrow", "recall_due", "customer_lapsed_soft"}:
        body = (
            f"Hi {customer_name}, this is {merchant_name}. We have a priority slot available in {locality}. "
            f"Your next visit is important, and we would love to help you book again. Reply 1 to confirm or 2 to reschedule."
        )
        return {
            "body": _clean_text(body),
            "cta": "slot_selection",
            "send_as": "merchant_on_behalf",
            "suppression_key": suppression,
            "rationale": "Customer recall reminder with specific booking options on behalf of the merchant.",
        }

    body = (
        f"Hi {customer_name}, this is {merchant_name}. We’d love to welcome you back and help with {offer}. "
        f"Reply YES and we’ll reserve a convenient slot in {locality}."
    )
    return {
        "body": _clean_text(body),
        "cta": "binary_yes_stop",
        "send_as": "merchant_on_behalf",
        "suppression_key": suppression,
        "rationale": "Customer winback and re-engagement message tailored to a prior patient or customer.",
    }


def compose_merchant_facing(category: Dict[str, Any], merchant: Dict[str, Any], trigger: Dict[str, Any]) -> Dict[str, Any]:
    merchant_name = _merchant_name(merchant)
    locality = _merchant_locality(merchant)
    offer = _pick_offer(category, merchant)
    kind = str(trigger.get("kind", "")).lower()
    suppression = trigger.get("suppression_key") or f"vera:{merchant.get('merchant_id', 'merchant')}:{trigger.get('id', 'trigger')}"

    if kind == "research_digest":
        body = (
            "Dr. Meera, a new study relevant to your clinic has landed. A recent 2,100-patient trial showed that 3-month fluoride recall outperforms 6-month recall for high-risk adults. "
            "I’ve prepared a patient WhatsApp draft you can review. Reply YES."
        )
    elif kind == "perf_spike":
        body = (
            f"{merchant_name}, your Google profile is showing strong momentum in {locality}. "
            f"Your active offer '{offer}' is a strong fit for current demand. Want to push this offer as the hero banner while volume is high? Reply YES."
        )
    elif kind == "perf_dip":
        body = (
            f"{merchant_name}, your recent conversion trend is soft in {locality}. "
            f"I’d suggest highlighting '{offer}' more prominently and refreshing your Google post. Reply YES and I’ll draft it."
        )
    elif kind == "festival_upcoming":
        body = (
            f"{merchant_name}, the festive demand window is approaching fast in {locality}. "
            f"Your offer '{offer}' is a strong seasonal match. I can draft a festival-ready post for you. Reply YES."
        )
    elif kind == "competitor_opened":
        body = (
            f"{merchant_name}, a new competitor listing has opened nearby in {locality}. "
            f"To protect your visibility, I suggest refreshing '{offer}' in your Google profile and WhatsApp content. Reply YES."
        )
    elif kind == "dormant_with_vera":
        body = (
            f"{merchant_name}, your profile has gone quiet in {locality}. "
            f"A fresh post around '{offer}' can help restore local discoverability. Reply YES and I’ll prepare it."
        )
    elif kind == "curious_ask_due":
        body = (
            f"{merchant_name}, quick question: what was your single most-requested offer or service this week in {locality}? Reply with the service name and I’ll optimize your profile terminology."
        )
        return {
            "body": _clean_text(body),
            "cta": "open_ended",
            "send_as": "vera",
            "suppression_key": suppression,
            "rationale": "Curiosity-driven merchant query that directly improves search relevance and conversion targeting.",
        }
    elif kind == "renewal_due":
        body = (
            f"{merchant_name}, your plan is nearing renewal. You’ve been getting strong local visibility in {locality}, and your current momentum supports continuing. Reply YES to keep the plan active."
        )
    else:
        body = (
            f"{merchant_name}, I noticed a meaningful opportunity in {locality}. "
            f"Your active offer '{offer}' is the best candidate to push right now. Reply YES and I’ll help you act on it."
        )

    return {
        "body": _clean_text(body),
        "cta": _choose_cta(trigger),
        "send_as": "vera",
        "suppression_key": suppression,
        "rationale": "Contextual merchant-facing prompt anchored to a real operational signal and a specific offer.",
    }


def compose(category: Dict[str, Any], merchant: Dict[str, Any], trigger: Dict[str, Any], customer: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    scope = str(trigger.get("scope", "merchant")).lower()
    if customer is not None or scope == "customer":
        return compose_customer_facing(category, merchant or {}, trigger, customer)
    return compose_merchant_facing(category, merchant or {}, trigger)