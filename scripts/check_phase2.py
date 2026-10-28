"""scripts/check_phase2.py — offline checks (no LLM, no DB) for the Phase 2 logic.

Usage:  python -m scripts.check_phase2
Covers: profile carry-over rules, suggested chips, greeting routing, validator fixes.
"""

import sys
from types import SimpleNamespace

from app.graph.profile import apply_profile, describe, detect_audience, update_profile
from app.graph.routers import after_query_understanding
from app.response.chips import build_chips
from app.response.tray import build_tray
from app.response.validator import _has_order_claim, validate
from app.schemas.chat import ChatResponseBody
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def q(intent="recommendation", **kw) -> QueryUnderstanding:
    return QueryUnderstanding.model_validate({"intent": intent, "scope": "in_scope", **kw})


# ── profile ──────────────────────────────────────────────────────────────
profile = update_profile({}, q(entities={"category": "face wash"}, filters={"skin_type": ["oily"]}))
follow_up = q(filters={"budget_max": 200})                      # "something under ₹200"
apply_profile(follow_up, profile)
check("follow-up inherits category and skin type", follow_up.entities.category == "face wash"
      and follow_up.filters.skin_type == ["oily"] and follow_up.filters.budget_max == 200)

profile = update_profile(profile, follow_up)
pick_one = q(context={"wants_single_pick": True})               # "recommend one"
apply_profile(pick_one, profile)
check("'recommend one' keeps category, budget and skin type", pick_one.entities.category == "face wash"
      and pick_one.filters.budget_max == 200 and pick_one.filters.skin_type == ["oily"])

new_topic = q(entities={"category": "razor"})
apply_profile(new_topic, profile)
check("a new category does not inherit the old budget", new_topic.filters.budget_max is None
      and new_topic.entities.category == "razor")

beard = q(entities={"body_area": ["beard"]})
apply_profile(beard, profile)
check("a message with its own subject does not inherit the category", beard.entities.category is None)

knowledge = q("knowledge", entities={"attributes": ["patchy beard"]})
apply_profile(knowledge, profile)
check("knowledge questions are not changed by the profile", knowledge.filters.skin_type == [])

women = update_profile({}, q(filters={"gender": "her"}))
check("audience is normalised", women.get("audience") == "women")
check("profile description mentions budget", "up to ₹200" in describe(profile))

check("'for my wife' names women", detect_audience("I need a razor for my wife") == "women")
check("'for my brother' names men", detect_audience("a gift for my brother") == "men")
check("'for myself' names nobody", detect_audience("I'm looking for a body razor for myself") is None)
check("'hair' is not 'her'", detect_audience("something for dry hair") is None)
check("both sides name nobody", detect_audience("a gift for my wife and my brother") is None)

# ── routing ──────────────────────────────────────────────────────────────
hi = SimpleNamespace(query=q("knowledge", context={"smalltalk": "greeting"}), get=lambda k, d=None: None)
state = {"query": hi.query}
check("greeting is routed to the greeting node", after_query_understanding(state) == "greeting")
check("normal message goes to sufficiency", after_query_understanding({"query": q()}) == "sufficiency")

# ── chips ────────────────────────────────────────────────────────────────
P = [{"id": str(i), "name": n, "price": 100.0, "availability": a, "url": "u", "image_url": "i", "details": {},
      "rating": 4.5, "review_count": 3, "original_price": 100.0}
     for i, (n, a) in enumerate([("Pro Beard Trimmer", "in_stock"), ("Combat Beard Trimmer", "in_stock"),
                                 ("Old Trimmer", "out_of_stock")])]
rec = SpecialistOutput(specialist="recommendation", status="success", data={"products": P})
body = ChatResponseBody(type="recommendation", markdown="x", product_tray=build_tray(rec))
chips = build_chips(body, {"query": q(entities={"category": "trimmer"}), "specialist_result": rec, "message": "trimmer"})
check("trimmer chips name the products", any("Compare Pro Beard Trimmer" in c for c in chips))
check("no order-tracking chip in a trimmer chat", not any("order" in c.lower() for c in chips) and len(chips) <= 3)

sup = SpecialistOutput(specialist="support", status="success", data={"items": []})
sup_body = ChatResponseBody(type="support", markdown="x")
sup_chips = build_chips(sup_body, {"query": q("support", entities={"attributes": ["track order"]}),
                                   "specialist_result": sup, "message": "where is my order"})
check("support chats offer related support questions", bool(sup_chips))

# ── validator ────────────────────────────────────────────────────────────
check("'whether ... has been packed' is guidance, not a claim",
      not _has_order_claim("Tracking shows whether your order has been packed or shipped."))
check("'already been packed' is a claim", _has_order_claim("Since your order has already been packed, you can't change it."))
check("conditional guidance still allowed", not _has_order_claim("If it has already been shipped, refuse delivery."))
md = "Here is a link: https://www.example.com/a\nNote."          # data text will contain a JSON-escaped \n
res = SpecialistOutput(specialist="support", status="success",
                       data={"items": [{"kind": "faq", "category": "x", "content": "see https://www.example.com/a\nthen wait"}]})
ok = validate(ChatResponseBody(type="support", markdown=md), res, [], "").valid
check("a URL followed by a newline in the data is recognised", ok)

from app.response.sanitize import sanitize_markdown

check("stray <br> and comments are removed",
      sanitize_markdown("| a<br>b |\n<!-- note -->\n**Wash** --> ok") == "| a b |\n\n**Wash**  ok")
check("normal Markdown is untouched", sanitize_markdown("**Pro** costs ₹649 - a < b") == "**Pro** costs ₹649 - a < b")

res2 = SpecialistOutput(specialist="knowledge", status="success", data={"chunks": []})
body2 = ChatResponseBody(type="knowledge", markdown="The **Full Body Trimmer** is great.")
body3 = ChatResponseBody(type="knowledge", markdown="It costs ₹700.")
check("a product already in the conversation may be named again",
      validate(body2, res2, ["Full Body Trimmer"], "Tell me about the Full Body Trimmer").valid)
check("an unrelated catalog product is still caught",
      not validate(body2, res2, ["Full Body Trimmer"], "hello").valid)
check("a price quoted earlier in the conversation may be repeated",
      validate(body3, res2, ["Full Body Trimmer"], "Full Body Trimmer ₹700 earlier reply").valid)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
