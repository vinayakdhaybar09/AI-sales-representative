"""Prompt for the reviewer: does the reply fulfil what the customer asked?

It is specialist-independent: it only needs the resolved request, the
requirements, a little conversation, the evidence the Composer was given, and
the Composer's reply. Tone, length and formatting are NOT judged here.
"""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.llm.prompts.composer import serialise
from app.schemas.specialist import SpecialistOutput

HISTORY_TURNS = 4
HISTORY_CHARS = 300

SYSTEM_PROMPT = """\
You are a strict quality reviewer for the shopping assistant of Bombay Shaving Company. \
You get the customer's request, the requirements a good answer must satisfy, a little of the conversation, \
the EVIDENCE (the only facts the assistant may use) and the assistant's REPLY. Decide whether the reply fulfils the request.

For each requirement decide: satisfied by the evidence and the reply, OR honestly acknowledged as unavailable \
(for example "we don't have a wooden comb", which counts as fulfilled), OR ignored/contradicted.

Report issues of these kinds only:
- missing: a requirement is ignored, or something asked for is not answered (for example two products were asked to be compared \
but only one is covered, or the reply presents an option as meeting a requirement when the evidence shows it does not).
- unsupported: a claim in the reply that is not in the evidence, or that stretches a product beyond its description \
(for example saying it helps with a concern its description never mentions).
- irrelevant: an item shown as a solution or fit that does not address the request. Put its id in exclude_item_ids. \
An item that is explicitly labelled as the closest alternative AND given a reason that is in the evidence is acceptable. \
If no item genuinely addresses the request, list all of them.

Rules:
- Do NOT judge tone, length, wording or formatting.
- For a comparison the customer also gets an attribute table (price, availability, rating, description, benefits, features) \
built from the evidence; the reply only has to introduce it and say when to pick each product.
- Do NOT reject a reply for honestly saying the shop does not have something. An honest "we don't have X" followed by a \
closest alternative with a reason from the evidence is FULFILLED.
- Flag "missing" only when a stated requirement is ignored. Do NOT flag it because the reply could explain more, compare more deeply \
or say how a feature meets the customer's needs.
- Never put an item in exclude_item_ids if the reply itself labels it as a closest alternative and justifies it with facts from the evidence. \
If fulfils is true, issues and exclude_item_ids must both be empty.
- fulfils is true only when you report no issues.
- Keep each detail to one short sentence that tells the writer what to fix.
- Only use ids from the item list.
"""


def _history_block(history: list[dict[str, str]]) -> str:
    recent = history[-HISTORY_TURNS:]
    if not recent:
        return "(none)"
    return "\n".join(f"{t['role'].capitalize()}: {t['content'][:HISTORY_CHARS]}" for t in recent)


def build_messages(
    resolved_request: str,
    requirements: list[str],
    history: list[dict[str, str]],
    result: SpecialistOutput,
    markdown: str,
) -> list[BaseMessage]:
    items = [
        {"id": str(p["id"]), "name": p["name"]} for p in result.data.get("products", [])
    ]
    body = (
        f"Customer request: {resolved_request}\n"
        f"Requirements: {requirements if requirements else '(none stated)'}\n\n"
        f"Recent conversation:\n{_history_block(history)}\n\n"
        f"Item list (ids you may exclude): {items if items else '(no products)'}\n\n"
        f"EVIDENCE:\n{serialise(result)}\n\n"
        f"REPLY:\n{markdown}"
    )
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=body)]
