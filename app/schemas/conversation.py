"""app/schemas/conversation.py — what the conversation node asks the model for."""

from typing import Literal

from pydantic import BaseModel, Field


class ConversationReply(BaseModel):
    kind: Literal["chat", "off_topic"] = Field(
        description="chat = greeting, small talk, thanks, goodbye or a question about the assistant; "
        "off_topic = a question unrelated to Bombay Shaving Company's products, grooming or orders."
    )
    reply: str = Field(description="The reply to the customer: 1-3 short sentences of plain text.")
