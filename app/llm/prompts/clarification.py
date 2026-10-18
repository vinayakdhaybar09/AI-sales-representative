"""Prompt for the single clarifying question (the only prose an LLM writes here)."""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM_PROMPT = """\
You are the shopping assistant of Bombay Shaving Company, a men's grooming brand. \
The customer's request is missing one detail. Ask exactly ONE short, friendly question \
that asks for that detail, and nothing else. Only list options when the missing detail is "use_case" \
(beard grooming, body grooming, or both). For any other detail ask openly and do NOT invent options, \
product types or categories. Do not recommend products, do not mention prices, do not ask two questions."""

# Used if the model call fails, so the user still gets one sensible question.
FALLBACK_QUESTIONS = {
    "use_case": "What will you mainly use it for: beard grooming, body grooming, or both?",
    "category": "What kind of product are you looking for?",
    "products": "Which two products would you like to compare?",
    "topic": "What would you like to know about?",
}


def fallback_question(missing_field: str) -> str:
    return FALLBACK_QUESTIONS.get(missing_field, "Could you tell me a bit more about what you need?")


def build_messages(original_query: str, intent: str, missing_field: str) -> list[BaseMessage]:
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=f"Customer request: {original_query}\nIntent: {intent}\nMissing detail: {missing_field}"
        ),
    ]
