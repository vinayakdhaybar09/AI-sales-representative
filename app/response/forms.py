"""app/response/forms.py — the form registry and the fixed reply for the query_submission specialist.

A specialist returns data only ({form_id, prefill}). This module turns that data
into the form component the frontend renders. No LLM is involved: the text and
the fields are fixed, so there is nothing to hallucinate.
"""

from app.schemas.chat import ChatResponseBody, FormField, FormOption, FormSpec
from app.schemas.specialist import SpecialistOutput

SUPPORT_QUERY = "support_query"

CATEGORIES = [
    FormOption(value="defective", label="Defective or damaged product"),
    FormOption(value="wrong_item", label="Wrong item received"),
    FormOption(value="missing_item", label="Item missing from my order"),
    FormOption(value="delivery", label="Delivery problem"),
    FormOption(value="return_refund", label="Return, refund or exchange"),
    FormOption(value="payment", label="Payment issue"),
    FormOption(value="cancellation", label="Order cancellation"),
    FormOption(value="usage", label="Product usage or quality"),
    FormOption(value="other", label="Something else"),
]

_ORDER_RELATED = ["defective", "wrong_item", "missing_item", "delivery", "return_refund", "payment", "cancellation"]
_PRODUCT_RELATED = ["defective", "wrong_item", "missing_item", "return_refund", "usage"]
_RESOLUTION = ["defective", "wrong_item", "missing_item", "return_refund"]
_PHOTOS = ["defective", "wrong_item", "missing_item", "other"]


def support_query_form(prefill: dict[str, str] | None = None) -> FormSpec:
    """The in-chat support query form. Fields appear and disappear with the issue type."""
    fields = [
        FormField(key="category", label="What is this about?", type="select", options=CATEGORIES, required=True),
        FormField(
            key="description", label="What happened?", type="textarea", required=True,
            placeholder="Tell us what went wrong, in your own words.",
        ),
        FormField(
            key="order_id", label="Order ID", type="text", required=True, required_unless="no_order_id",
            placeholder="e.g. #BSC12345", show_if={"category": _ORDER_RELATED},
            hint="You can find it in your order confirmation email or SMS.",
        ),
        FormField(
            key="no_order_id", label="I don't have my order ID", type="checkbox", show_if={"category": _ORDER_RELATED}
        ),
        FormField(
            key="product", label="Which product?", type="text", placeholder="Product name",
            show_if={"category": _PRODUCT_RELATED},
        ),
        FormField(
            key="received_date", label="When did you receive it?", type="date",
            show_if={"category": ["defective", "wrong_item", "missing_item", "return_refund"]},
            hint="Report defective or incorrect items within 2 working days of delivery.",
        ),
        FormField(
            key="product_used", label="Have you used the product?", type="radio",
            options=[FormOption(value="yes", label="Yes"), FormOption(value="no", label="No")],
            show_if={"category": ["defective"]},
        ),
        FormField(
            key="resolution", label="What would you like us to do?", type="select",
            options=[
                FormOption(value="refund", label="Refund"),
                FormOption(value="replacement", label="Replacement"),
                FormOption(value="not_sure", label="Not sure"),
            ],
            show_if={"category": _RESOLUTION},
        ),
        FormField(
            key="expected_date", label="Expected delivery date", type="date", show_if={"category": ["delivery"]}
        ),
        FormField(
            key="tracking_id", label="Tracking or AWB number", type="text", show_if={"category": ["delivery"]}
        ),
        FormField(
            key="transaction_id", label="Transaction or reference ID", type="text", show_if={"category": ["payment"]},
            hint="Please don't share card or bank account numbers.",
        ),
        FormField(key="amount", label="Amount (₹)", type="number", show_if={"category": ["payment"]}),
        FormField(
            key="images", label="Photos (optional)", type="images", max_files=3, max_mb=5,
            show_if={"category": _PHOTOS},
            hint="For a defective or incorrect item, a photo of the product and of the outer box with the shipping label helps.",
        ),
        FormField(key="name", label="Your name", type="text", required=True),
        FormField(key="email", label="Email", type="text", placeholder="you@example.com"),
        FormField(key="phone", label="Phone number", type="text", placeholder="10-digit mobile number"),
    ]
    return FormSpec(
        form_id=SUPPORT_QUERY,
        title="Raise a query",
        submit_label="Submit query",
        fields=fields,
        require_one_of=[["email", "phone"]],
        prefill={k: v for k, v in (prefill or {}).items() if v},
    )


FORMS = {SUPPORT_QUERY: support_query_form}

INTROS = [
    "Sorry about that. Fill in the details below and I'll log it as a query for our support team.",
    "I'm sorry you ran into this. Share a few details below and I'll submit it as a query.",
]


def query_form_reply(result: SpecialistOutput, seed: str = "") -> ChatResponseBody:
    """The fixed reply for a query_submission result: one short line plus the form."""
    form_id = result.data.get("form_id", SUPPORT_QUERY)
    build = FORMS.get(form_id, support_query_form)
    intro = INTROS[sum(ord(c) for c in seed) % len(INTROS)]
    return ChatResponseBody(
        type="query_submission",
        markdown=intro,
        product_tray=[],
        suggested_prompts=[],
        form=build(result.data.get("prefill")),
    )


def check_form_reply(response: ChatResponseBody, result: SpecialistOutput) -> list[str]:
    """Deterministic checks for a query_submission reply (critical issues; empty = fine)."""
    issues: list[str] = []
    if response.type != "query_submission":
        issues.append(f"response type '{response.type}' does not match the 'query_submission' specialist")
    form = response.form
    if form is None:
        issues.append("the reply has no form")
    elif form.form_id != result.data.get("form_id", SUPPORT_QUERY) or form.form_id not in FORMS:
        issues.append("the form does not match the one the specialist asked for")
    if response.product_tray or response.comparison_table:
        issues.append("a form reply must not carry products")
    if not response.markdown.strip():
        issues.append("markdown is empty")
    return issues
