---
name: add-graph-node
description: Add or modify a LangGraph node, edge, or conditional route in the BSC chatbot workflow. Use when the task touches app/graph/ (state, builder, nodes) or changes routing between handlers, specialists, composer, or validator.
---

# Add or change a graph node

1. Read `docs/ARCHITECTURE.md` (request flow + diagram) and `docs/CONTRACTS.md` (state and output shapes).
2. Check current LangGraph docs for the exact API (StateGraph, conditional edges, compile) before writing code. Do not rely on memory.
3. Put each node in its own file under `app/graph/nodes/`. A node is `async def node(state) -> dict` returning only the state keys it updates.
4. Add new state keys to `app/graph/state.py` only if needed, and keep them typed.
5. Routing decisions (out_of_scope, sufficient/insufficient, which specialist, retry vs fallback) live in small plain-Python router functions, not in prompts.
6. Nodes call specialists/repositories/LLM module; they never contain SQL or build models inline.
7. Wire the node in `app/graph/builder.py`. Keep the graph shape identical to the diagram unless the owner approves a change.
8. Verify with `curl` against `/api/chat` for every branch the node affects; log node entry at DEBUG with `conversation_id`, never message content at INFO.
9. Update `docs/ARCHITECTURE.md` if the flow changed.
