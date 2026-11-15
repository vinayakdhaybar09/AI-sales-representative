"""app/agent/runner.py — one customer message through the salesperson agent.

`run_turn` is an async generator of UI events (the SSE endpoint forwards them,
`collect` folds them into the classic envelope):

    {"event": "status", "text": "Searching the catalog…"}
    {"event": "token",  "text": "..."}          streamed reply text
    {"event": "reset"}                          drop streamed text (a tool round followed)
    {"event": "revise", "text": "..."}          guard rewrote the reply; replace it
    {"event": "final",  "body": {...}}          the full ChatResponseBody (authoritative)
    {"event": "error",  "code", "message"}

Flow: load session → LLM (streams) ⇄ tools (≤ N rounds) → guard (one rewrite,
then scrub) → build cards/table/bundle/form in Python → save session + log turn.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncIterator

from app.agent import guard, retrieval, sessions
from app.agent.budget import parse_budget
from app.agent.llm_client import LLMUnavailableError, stream_chat
from app.agent.prompt import build_system_prompt, detect_language
from app.agent.tools import (TOOL_SCHEMAS, TurnContext, apply_profile_updates, build_cards, run_tool, support_form,
                             summarize)
from app.core.config import get_settings
from app.db.connection import get_pool
from app.response.comparison_table import build_comparison_table
from app.schemas.chat import Bundle, ChatResponseBody, ChatEnvelope, ComparisonTable
from app.schemas.specialist import SpecialistOutput
from app.response.envelope import success_envelope, error_envelope

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    "search_products": "Looking through the catalog…", "get_product": "Checking product details…",
    "compare_products": "Comparing them…", "search_knowledge": "Checking our guides and policies…",
    "get_offers": "Finding the best deals…", "build_routine": "Putting your routine together…",
    "handoff_to_human": "Preparing the support form…",
}
INTENT_ORDER = ["support_handoff", "policy", "comparison", "routine", "deals", "recommendation",
                "product_question", "grooming_advice"]
_LANG_SUFFIX = {"hinglish": "\n[reply in Hinglish, Roman script]", "hindi": "\n[reply in Hindi, Devanagari script]"}
_CATALOG_CACHE: dict[str, Any] = {"text": "", "until": 0.0}
_RED_FLAGS = re.compile(r"bleed|blood|infect|\bpus\b|severe|painful|cystic|swollen|swelling|burning|rash|eczema|psoriasis|allerg|wound|boil|ulcer|bumps? (?:that )?(?:hurt|won'?t)", re.I)
_REFERRAL = re.compile(r"dermatolog|doctor|physician|medical professional|skin specialist", re.I)
_SUPPORT_RULES = [   # (pattern, form category): checked in order
    (re.compile(r"damag|broken|defect|faulty|stopped working|not working|dead on arrival", re.I), "defective"),
    (re.compile(r"wrong (item|product|perfume|razor|trimmer|order|size)|sent me the wrong|different (item|product)", re.I), "wrong_item"),
    (re.compile(r"missing (item|product|from)|item (is )?missing|only .{0,20}(arrived|delivered|received)", re.I), "missing_item"),
    (re.compile(r"(never|not) (arrived|received|delivered)|haven'?t received|not delivered", re.I), "delivery"),
    (re.compile(r"(my|want (a )?|need (a )?|get (my )?)refund|refund (me|my)|money back", re.I), "return_refund"),
]
_LEAK = re.compile(r"search_products|get_product|compare_products|search_knowledge|get_offers|build_routine|handoff_to_human|"
                   r"\bremember\(|CATALOG MAP|WHAT YOU KNOW|\[\[chips|tool_call|function_call|system prompt (is|says|reads)", re.I)
_LEAK_REPLY = ("I can't go into how I work behind the scenes, but I'm happy to help with grooming. "
               "What are you looking for today: a trimmer, razor, skincare, a fragrance or a gift?")
_POLICY_RX = re.compile(r"refund|return|exchange|replac|cancel|shipping|delivery|deliver|dispatch|track|warranty|payment|\bcod\b|"
                        r"cash on delivery|invoice|order status|kitne din|wapas|paisa wapas", re.I)
_ROUTINE_RX = re.compile(r"routine|regimen|\bkit\b|\bset\b|combo|bundle|complete (shav|groom|care)|full (shav|groom|care)", re.I)
_CHIPS = re.compile(r"\[\[\s*chips\s*:\s*(.*?)\]\]", re.S | re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S)


class _ChipFilter:
    """Hides the trailing [[chips: …]] line from the live stream and parses it at the end."""

    def __init__(self) -> None:
        self.buf, self.sent = "", 0

    def feed(self, text: str) -> str:
        self.buf += text
        cuts = [i for i in (self.buf.find("[["), self.buf.find("<tool_call"), self.buf.find("<function=")) if i >= 0]
        cut = min(cuts) if cuts else -1
        end = cut if cut >= 0 else len(self.buf) - (1 if self.buf.endswith(("[", "<")) else 0)
        out = self.buf[self.sent:max(end, self.sent)]
        self.sent = max(self.sent, end)
        return out

    def result(self) -> tuple[str, list[str]]:
        text = _THINK.sub("", self.buf)
        m = _CHIPS.search(text)
        chips = [c.strip() for c in m.group(1).split("|") if c.strip()][:3] if m else []
        clean = text[:text.find("[[")] if "[[" in text else text
        clean = re.split(r"<tool_call|<function=", clean)[0]
        return clean.strip(), [c[:40] for c in chips]


async def _catalog_map() -> str:
    if _CATALOG_CACHE["until"] < time.monotonic():
        async with get_pool().connection() as conn:
            _CATALOG_CACHE["text"] = await retrieval.catalog_map(conn)
        _CATALOG_CACHE["until"] = time.monotonic() + 600
    return _CATALOG_CACHE["text"]


def scrub(reply: str, issues: list[str]) -> str:
    """Last resort when a rewrite still fails: drop the sentences that carry the flagged tokens."""
    flagged = set(re.findall(r"₹\s?[\d,.]+|https?://\S+|[\w.+-]+@[\w.-]+", " ".join(issues)))
    parts = re.split(r"(?<=[.!?])\s+|\n+", reply)
    kept = [p for p in parts if not any(f.replace("₹", "").strip() in p for f in flagged if f)
            and not guard._ORDER_CLAIM.search(p) and not guard._MEDICAL.search(p)]
    text = " ".join(kept).strip()
    return text if len(text) > 25 else ("I want to be accurate here, so let me point you to the products below "
                                        "and our care team (care@bombayshavingcompany.com) for the exact details.")


def _compact(text: str) -> str:
    """Lowercase letters/digits only, so '264 g' and '264g', or '|' vs '-', never block a name match."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _intent(ctx: TurnContext) -> str:
    for k in INTENT_ORDER:
        if k in ctx.kinds_used:
            return k
    return "chitchat"


async def run_turn(conversation_id: str, message: str) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    t0 = time.monotonic()
    first_token_ms: int | None = None
    tokens = 0
    model_used = None
    error: str | None = None
    ctx: TurnContext | None = None
    reply, chips, issues_log = "", [], []

    async def db_phase_load():
        async with get_pool().connection() as conn:
            sess = await sessions.load_session(conn, conversation_id, settings.session_ttl_minutes)
            shown_rows = await retrieval.get_many(conn, sess["shown_ids"][-6:])
        return sess, shown_rows

    try:
        sess, shown_rows = await db_phase_load()
        catalog = await _catalog_map()
        logger.info("timing: session+catalog ready at %d ms", (time.monotonic() - t0) * 1000)
        system = build_system_prompt(sess["profile"], catalog, [summarize(r) for r in shown_rows], detect_language(message))
        history = sess["messages"][-settings.agent_history_messages:]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history,
                                          {"role": "user", "content": message + _LANG_SUFFIX.get(detect_language(message), "")}]
        user_texts = [m["content"] for m in history if m["role"] == "user"] + [message]
        ctx = TurnContext(profile=sess["profile"])
        # Products from earlier turns may be discussed again: their facts (name, price, stock) are in the prompt.
        ctx.seen.update({str(r["id"]): r for r in shown_rows})
        ctx.result_text.append(" ".join(json.dumps(summarize(r), ensure_ascii=False) for r in shown_rows))
        if _POLICY_RX.search(message):
            # Policy questions always get the policy sources, fetched here so the answer cannot skip them.
            policy = await run_tool(ctx, "search_knowledge", {"query": message, "kind": "policy"})
            messages[0]["content"] += ("\n\nPOLICY SOURCES for this message (answer policy questions only from these; "
                                       "if they disagree, say so and point to care@bombayshavingcompany.com): " + policy)
        filt = _ChipFilter()
        nudged = False
        for round_no in range(settings.agent_max_rounds):
            last_round = round_no == settings.agent_max_rounds - 1
            filt = _ChipFilter()
            streamed_any = False
            done: dict[str, Any] = {}
            async for ev in stream_chat(messages, None if last_round else TOOL_SCHEMAS):
                if ev["type"] == "delta":
                    out = filt.feed(ev["text"])
                    if out:
                        if first_token_ms is None:
                            first_token_ms = round((time.monotonic() - t0) * 1000)
                        streamed_any = True
                        yield {"event": "token", "text": out}
                else:
                    done = ev
            tokens += done.get("usage", 0)
            logger.info("timing: round %d done at %d ms (model=%s, tokens=%s, tool_calls=%d)", round_no,
                        (time.monotonic() - t0) * 1000, done.get("model"), done.get("usage"), len(done.get("tool_calls") or []))
            model_used = done.get("model")
            calls = done.get("tool_calls") or []
            if not calls or last_round:
                if not calls and not last_round and not ctx.tool_log and not nudged:
                    # The model answered from memory. If that draft has ungrounded facts, send it back to look things up.
                    draft, _ = filt.result()
                    async with get_pool().connection() as conn:
                        draft_names = [r["name"] for r in (await retrieval.catalog(conn)).values()]
                    draft_issues = guard.check(draft, ctx, user_texts, draft_names)
                    if draft_issues:
                        nudged = True
                        logger.info("Draft answered without lookups (%s); sending it back to search", "; ".join(draft_issues)[:160])
                        if streamed_any:
                            yield {"event": "reset"}
                        messages.append({"role": "assistant", "content": draft})
                        messages.append({"role": "user", "content": (
                            "[system check] That answer used facts you did not look up. Search now (keep the customer's budget "
                            "and what they want from the conversation), then answer using only the results. Name only products the search returns.")})
                        continue
                break
            if streamed_any:
                yield {"event": "reset"}
            messages.append({"role": "assistant", "content": filt.buf or None, "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                for i, c in enumerate(calls)]})
            for status in dict.fromkeys(STATUS_TEXT.get(c["name"], "Thinking…") for c in calls):
                yield {"event": "status", "text": status}
            # Tool calls of one step are independent: run them concurrently, keep the model's order for results.
            results = await asyncio.gather(*(run_tool(ctx, c["name"], c["arguments"]) for c in calls))
            logger.info("timing: %d tool(s) done at %d ms", len(calls), (time.monotonic() - t0) * 1000)
            for i, (c, result) in enumerate(zip(calls, results)):
                messages.append({"role": "tool", "tool_call_id": c["id"] or f"call_{i}", "content": result})
        reply, chips = filt.result()
        if not reply.strip():
            # Glitchy or rate-limited model produced no text after its tools ran: ask once more, text only.
            messages.append({"role": "user", "content": (
                "[system] Answer the customer now in plain text using the tool results above. No tool calls. "
                "End with the [[chips: …]] line.")})
            redo = _ChipFilter()
            async for ev in stream_chat(messages, None, temperature=0.3):
                if ev["type"] == "delta":
                    out = redo.feed(ev["text"])
                    if out:
                        yield {"event": "token", "text": out}
            reply, chips = redo.result()

        # ── guard: one rewrite, then scrub ──
        async with get_pool().connection() as conn:
            all_names = [r["name"] for r in (await retrieval.catalog(conn)).values()]
        issues = guard.check(reply, ctx, user_texts, all_names)
        if issues:
            issues_log = list(issues)
            logger.info("Guard issues (%d): %s", len(issues), "; ".join(issues)[:300])
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": (
                "[system check] Rewrite your last reply fixing these problems, using only data from your tool results "
                "and keeping the same language and tone: " + "; ".join(issues) + ". End with the [[chips: …]] line.")})
            redo = _ChipFilter()
            try:
                async for ev in stream_chat(messages, None, temperature=0.2):
                    if ev["type"] == "delta":
                        redo.feed(ev["text"])
            except LLMUnavailableError:
                logger.warning("Rewrite unavailable; cleaning the reply with the rule-based scrub instead")
            new_reply, new_chips = redo.result()
            if new_reply:
                reply, chips = new_reply, new_chips or chips
                issues = guard.check(reply, ctx, user_texts, all_names)
            if issues:
                reply = scrub(reply, issues)
            yield {"event": "revise", "text": reply}

        if not reply:
            reply = "Sorry, I lost my train of thought there. Could you say that once more?"
            yield {"event": "revise", "text": reply}

        if _LEAK.search(reply):
            # Never let internal tool names or prompt text reach a customer, whatever the model was talked into.
            reply, chips = _LEAK_REPLY, ["Suggest a trimmer", "Gift ideas", "Today's deals"]
            yield {"event": "revise", "text": reply}

        # Safety net (plain Python): red-flag symptoms always get a dermatologist referral, even if a
        # rewrite or scrub removed the model's own.
        if _RED_FLAGS.search(message) and not _REFERRAL.search(reply):
            reply += "\n\nBecause this sounds persistent or painful, please also check with a dermatologist before trying anything new."
            yield {"event": "revise", "text": reply}

        # ── build the structured parts in Python ──
        if not ctx.bundle and not ctx.compare_ids:
            # Cards = the products the reply names, in the order it names them (so tray and prose always agree).
            low = _compact(reply)
            named = sorted((r for r in ctx.seen.values() if _compact(r["name"]) in low),
                           key=lambda r: low.find(_compact(r["name"])))
            ctx.shown_ids = [r["id"] for r in named][:3]
        # Cards must respect the budget the customer stated (a product mentioned as "just over your limit" gets no card).
        limit = None
        for text in reversed(user_texts[-4:]):
            parsed = parse_budget(text)
            if parsed:
                limit = parsed[0] * (1.1 if parsed[1] else 1.0)
                break
        if limit is None and isinstance(ctx.profile.get("budget_max"), (int, float)):
            limit = float(ctx.profile["budget_max"])
        if limit:
            ctx.shown_ids = [i for i in ctx.shown_ids if float(ctx.seen[i]["price"]) <= limit]
        # A routine / kit request always gets the routine card: build it from the products the reply names.
        if (not ctx.bundle and not ctx.compare_ids and any(_ROUTINE_RX.search(t) for t in user_texts[-3:])):
            picks = [ctx.seen[i] for i in ctx.shown_ids if ctx.seen[i]["availability"] == "in_stock"][:6]
            if len(picks) >= 2:
                from app.agent.tools import cart_url
                ctx.bundle = {"title": "Your routine", "steps": [
                    {"label": r["category"], "product_id": str(r["id"])} for r in picks],
                    "total": round(sum(float(r["price"]) for r in picks), 2), "cart_url": cart_url(picks)}
                ctx.shown_ids = [str(r["id"]) for r in picks]
                # The reply may state a vague or wrong total ("around ₹1,500-1,700"): replace it with the real sum.
                kept = [x for x in re.split(r"(?<=[.!?])\s+|\n+", reply) if not (re.search(r"\btotal\b", x, re.I) and "₹" in x)]
                reply = "\n".join(kept).strip() + f"\n\nTotal for these {len(picks)}: ₹{ctx.bundle['total']:,.0f}."
                yield {"event": "revise", "text": reply}
        table: ComparisonTable | None = None
        if len(ctx.compare_ids) >= 2:
            rows = [ctx.seen[i] for i in ctx.compare_ids if i in ctx.seen]
            table = build_comparison_table(SpecialistOutput(
                specialist="comparison", status="success", data={"products": rows}))
        if ctx.form_prefill is None:
            # Safety net: clear complaints always get the prefilled support form, even if the model skipped the tool.
            for rx, category in _SUPPORT_RULES:
                if rx.search(message):
                    ctx.form_prefill = {"category": category, "description": message[:500]}
                    ctx.kinds_used.add("support_handoff")
                    break
        form = support_form(ctx)
        cards = [] if table else build_cards(ctx)
        bundle = Bundle(**ctx.bundle) if ctx.bundle else None
        rtype = ("comparison" if table else "support" if form else "recommendation" if (cards or bundle)
                 else "knowledge" if ctx.kinds_used & {"policy", "grooming_advice"} else "conversation")
        if not chips:   # a rewrite or cleanup can drop the model's chips line
            chips = ({"hindi": ["और विकल्प दिखाइए", "ऑफ़र क्या हैं?"], "hinglish": ["aur options dikhao", "offers kya hain?"]}
                     .get(detect_language(message), ["Show me other options", "What's on offer?"]))
        body = ChatResponseBody(type=rtype, markdown=reply, product_tray=cards, comparison_table=table,
                                suggested_prompts=chips, form=form, bundle=bundle)

        # ── persist ──
        profile = apply_profile_updates(sess["profile"], ctx.profile_updates)
        new_msgs = [*sess["messages"], {"role": "user", "content": message},
                    {"role": "assistant", "content": reply}]
        shown = [*sess["shown_ids"], *[i for i in ctx.shown_ids if i not in sess["shown_ids"]]][-12:]
        async with get_pool().connection() as conn:
            await sessions.save_session(conn, conversation_id, new_msgs[-24:], profile, shown)
        yield {"event": "final", "body": body.model_dump(mode="json")}
    except LLMUnavailableError as exc:
        error = f"llm_unavailable: {exc}"
        logger.error("All LLMs unavailable: %s", exc)
        body = await _degraded_body(message, [m["content"] for m in (sess["messages"] if "sess" in locals() else []) if m["role"] == "user"])
        reply = body.markdown
        yield {"event": "final", "body": body.model_dump(mode="json")}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("Agent turn failed (conversation_id=%s)", conversation_id)
        yield {"event": "error", "code": "internal_error",
               "message": "Something went wrong on our side. Please try again."}
    finally:
        try:
            async with get_pool().connection() as conn:
                await sessions.log_turn(
                    conn, conversation_id=conversation_id, user_message=message, reply=reply,
                    intent=_intent(ctx) if ctx else "error", tools=ctx.tool_log if ctx else [],
                    products_shown=ctx.shown_ids if ctx else [], unmet_queries=ctx.unmet if ctx else [],
                    guard_issues=issues_log, handoff=bool(ctx and ctx.form_prefill is not None),
                    model=model_used, first_token_ms=first_token_ms,
                    total_ms=round((time.monotonic() - t0) * 1000), tokens=tokens or None, error=error)
        except Exception:
            logger.warning("Could not write the turn log")


async def _degraded_body(message: str, recent_user_texts: list[str] | None = None) -> ChatResponseBody:
    """No LLM available: still help, from search alone (cards + a fixed sentence)."""
    try:
        async with get_pool().connection() as conn:
            parsed = parse_budget(message)
            budget = parsed[0] if parsed else None
            # A bare follow-up like "Under 2000" means nothing alone: search with the recent customer messages.
            context = " ".join([*(recent_user_texts or [])[-3:], message])
            parsed = parse_budget(context) if budget is None else parsed
            budget = parsed[0] if parsed else budget
            res = await retrieval.hybrid_search(conn, context, max_price=budget, limit=3)
        from app.agent.tools import card
        cards = [card(p) for p in res["products"]]
    except Exception:
        cards = []
    text = ("My assistant brain is busy for a moment, so I can't chat properly right now. "
            + ("These are the closest matches from our catalog for what you asked." if cards else
               "Please try again in a minute, or write to care@bombayshavingcompany.com."))
    # With cards the reply is shown as a recommendation so the UI draws them; without, as a plain fallback
    # (the UI adds its own "Try again" button to fallbacks).
    return ChatResponseBody(type="recommendation" if cards else "fallback", markdown=text, product_tray=cards,
                            suggested_prompts=["Show me trimmers", "Shipping policy"])


async def collect(conversation_id: str, message: str) -> ChatEnvelope:
    """Non-streaming adapter: the classic POST /api/chat envelope (used by evals and old clients)."""
    async with asyncio.timeout(get_settings().request_timeout_seconds):
        async for ev in run_turn(conversation_id, message):
            if ev["event"] == "final":
                return success_envelope(conversation_id, ChatResponseBody(**ev["body"]))
            if ev["event"] == "error":
                return error_envelope(conversation_id, ev["code"], ev["message"])
    return error_envelope(conversation_id, "internal_error", "No response was produced.")
