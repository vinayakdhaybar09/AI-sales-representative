"""scripts/try_replies.py — see how the Composer sounds, and whether the validator still accepts it.

Usage:
    python -m scripts.try_replies            # one pass over the fixtures
    python -m scripts.try_replies --runs 3   # repeat each fixture (measures validator rejections at temperature 0.3)

Calls the real chat model (no database). Each fixture is a fake specialist
output plus optional chat history; the reply is built with the real Composer
prompt, then checked by the REAL deterministic validator and a few style rules.
Read the printed replies and judge the tone yourself.
"""

import argparse
import asyncio
import re
import sys

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.llm.models import get_chat_model
from app.llm.prompts.composer import build_messages
from app.llm.retry import ainvoke_with_retry
from app.response.conversation import _EMOJI
from app.response.tray import build_tray
from app.response.validator import validate
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput
from scripts.check_reviewer import COMB, RAZORS, SKIN, out, product

CATALOG = [p["name"] for p in SKIN + COMB + RAZORS]

KNOWLEDGE = SpecialistOutput(
    specialist="knowledge", status="success",
    data={"products": [], "chunks": [{
        "source_id": "b1", "title": "6 Reasons Why Your Dandruff Treatment Isn't Working", "heading": "Common mistakes",
        "category": "hair", "url": "https://www.bombayshavingcompany.com/blogs/grooming/dandruff-treatment", "score": 0.8,
        "content": "Skipping shampoo does not moisturise the scalp; it lets sebum and yeast build up and worsens flakes. Shampoo when your scalp "
                   "feels greasy, followed by a lightweight conditioner, about once every three days. Oils like coconut or olive oil may "
                   "reduce flakes briefly but can make dandruff worse in the long run. Stress raises sebum production, so manage stress and "
                   "eat enough B vitamins. For beard dandruff, use a gentle face wash and keep the skin hydrated with a beard oil or balm."}]},
    sources=[{"type": "blog", "id": "b1", "title": "6 Reasons Why Your Dandruff Treatment Isn't Working"}],
)
SUPPORT = SpecialistOutput(
    specialist="support", status="success",
    data={"items": [{"source_id": "s1", "kind": "faq", "category": "orders", "score": 0.8,
                     "content": "Once your order is shipped you will receive an SMS and an email with the tracking details. Use the tracking page to see the latest status."}],
          "contact_info": {"tracking_url": "https://www.bombayshavingcompany.com/pages/track-order", "care_email": "care@bombayshavingcompany.com"},
          "live_order_data_available": False},
)
FINAL_1 = SpecialistOutput(
    specialist="product_finalization", status="success",
    data={"products": [dict(SKIN[4], rank=1, selection_reasons=["rated 4.5/5 from 50 reviews", "₹189, within your ₹200 budget", "fits your need: oily skin", "in stock"])],
          "criteria_applied": ["product type: face wash", "budget up to ₹200", "skin type: oily"], "requested": 1},
)
FINAL_2 = SpecialistOutput(
    specialist="product_finalization", status="success",
    data={"products": [dict(RAZORS[0], rank=1, selection_reasons=["rated 4.7/5 from 300 reviews", "₹199", "in stock"]),
                       dict(RAZORS[1], rank=2, selection_reasons=["rated 4.5/5 from 120 reviews", "₹299", "in stock"])],
          "criteria_applied": ["product type: razor", "skin type: sensitive"], "requested": 2},
)
NONE_FOUND = SpecialistOutput(specialist="recommendation", status="success", data={"products": []}, warnings=["no_suitable_products"])
ALT = out("recommendation", COMB)
ALT.warnings.append("category_not_matched")
FACE_HISTORY = [{"role": "user", "content": "My skin gets really oily by noon"},
                {"role": "assistant", "content": "Oily skin usually does best with a gentle cleanser twice a day."}]
DANDRUFF_HISTORY = [{"role": "user", "content": "i have so much dandruff, how can i get rid off?"},
                    {"role": "assistant", "content": "Shampoo regularly and avoid over-oiling. Read the full article."}]
RAZOR_HISTORY = [{"role": "user", "content": "suggest a razor"},
                 {"role": "assistant", "content": "Showed products: Sensi Smart 3 Razor (₹199), Legend Razor (₹299)"}]

# (label, request, history, specialist output)
FIXTURES = [
    ("recommendation", "Suggest a face wash under 200", [], out("recommendation", [SKIN[3], SKIN[4]])),
    ("recommendation + history", "Suggest a face wash for oily skin", FACE_HISTORY, out("recommendation", [SKIN[3], SKIN[4]])),
    ("recommendation, 1 product", "Do you have a body soap?", [], out("recommendation", [SKIN[2]])),
    ("closest alternative", "Show a wooden hair comb", [], ALT),
    ("no suitable product", "Suggest a product for dandruff", DANDRUFF_HISTORY, NONE_FOUND),
    ("comparison", "Compare Sensi Smart 3 Razor and Legend Razor", RAZOR_HISTORY, out("comparison", RAZORS, comparable_fields=["price", "rating", "details.features"], unresolved=[])),
    ("knowledge", "I have so much dandruff, how can I get rid of it?", [], KNOWLEDGE),
    ("support", "Where is my order?", [], SUPPORT),
    ("support, worried", "My order is late and I'm really frustrated, where is it??", [], SUPPORT),
    ("finalization, 1 pick", "Suggest the best one face wash for me", FACE_HISTORY, FINAL_1),
    ("finalization, 2 picks", "Narrow it down to the top two razors", RAZOR_HISTORY, FINAL_2),
]


def style_flags(text: str) -> list[str]:
    flags = []
    if text.count("!") > 1:
        flags.append(f"{text.count('!')} exclamation marks")
    if _EMOJI.search(text):
        flags.append("emoji")
    if re.match(r"\s*(here are|here is|here's)\b", text, re.IGNORECASE):
        flags.append("generic 'Here are…' opener")
    return flags


async def compose(request, history, result) -> str:
    model = get_chat_model(get_settings().composer_temperature)
    reply = await ainvoke_with_retry(model, build_messages(request, result, None, None, history))
    return reply.content.strip() if isinstance(reply.content, str) else ""


async def main(runs: int) -> int:
    print(f"Composer temperature: {get_settings().composer_temperature}\n")
    total = rejected = styled = 0
    for label, request, history, result in FIXTURES:
        for run in range(runs):
            text = await compose(request, history, result)
            body = ChatResponseBody(type=result.specialist, markdown=text, product_tray=build_tray(result))
            check = validate(body, result, CATALOG, request)
            flags = style_flags(text)
            total += 1
            rejected += not check.valid
            styled += bool(flags)
            print(f"━━ {label}" + (f" (run {run + 1})" if runs > 1 else "") + f"   request: {request!r}")
            print(text)
            print(f"   validator: {'OK' if check.valid else 'REJECTED: ' + '; '.join(check.critical)}"
                  + (f"   style: {', '.join(flags)}" if flags else "") + "\n")
    print(f"{total} replies: {total - rejected} accepted by the validator, {rejected} rejected; {styled} with style flags.")
    return 0


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    sys.exit(asyncio.run(main(parser.parse_args().runs)))
