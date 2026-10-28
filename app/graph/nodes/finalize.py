import logging

from app.graph import conversation_store
from app.graph.state import ChatState
from app.response.chips import build_chips

logger = logging.getLogger(__name__)


async def finalize(state: ChatState) -> dict:
    """Save this turn (history, shown products, pending clarification)."""
    history = list(state.get("history", []))
    history.append({"role": "user", "content": state["message"]})
    history.append({"role": "assistant", "content": state["response"].markdown})
    # Tray product IDs become "previously mentioned" for the next turn.
    shown = [card.product_id for card in state["response"].product_tray]
    previous = shown or state.get("previous_product_ids", [])
    await conversation_store.save(
        state["conversation_id"], history, previous, state.get("pending_clarification"), state.get("profile")
    )
    logger.debug("node=finalize conversation_id=%s", state["conversation_id"])

    response = state["response"]
    if not response.suggested_prompts:   # fixed replies (greeting, fallback...) bring their own
        chips = build_chips(response, state)
        if chips:
            return {"response": response.model_copy(update={"suggested_prompts": chips})}
    return {}
