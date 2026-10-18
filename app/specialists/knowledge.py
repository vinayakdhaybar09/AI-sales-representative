"""Knowledge specialist: blog chunks (+ product info when a product is named)."""

import logging

import psycopg

from app.db.repositories.products import find_products_by_name
from app.retrieval.search import search
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput
from app.specialists.products import to_record

logger = logging.getLogger(__name__)

TOP_K = 5
MIN_SCORE = 0.68   # off-topic queries score ~0.6 against blog chunks


async def run(
    conn: psycopg.AsyncConnection, query: QueryUnderstanding, search_text: str
) -> SpecialistOutput:
    warnings: list[str] = []
    hits = [h for h in await search(conn, search_text, "blog", TOP_K) if h.score >= MIN_SCORE]
    chunks = [
        {
            "source_id": h.source_id,
            "title": h.metadata.get("title"),
            "heading": h.metadata.get("heading"),
            "category": h.metadata.get("category"),
            "url": h.metadata.get("url"),
            "content": h.content,
            "score": round(h.score, 3),
        }
        for h in hits
    ]

    products: dict[str, dict] = {}
    for name in query.entities.products:
        rows, _ = await find_products_by_name(conn, name, 2)
        for row in rows:
            products.setdefault(row["id"], to_record(row))

    if not chunks and not products:
        return SpecialistOutput(specialist="knowledge", status="empty",
                                warnings=["no_relevant_articles"])
    if not chunks:
        warnings.append("no_relevant_articles")
    return SpecialistOutput(
        specialist="knowledge",
        status="success",
        data={"chunks": chunks, "products": list(products.values())},
        sources=[{"type": "blog", "title": c["title"], "heading": c["heading"], "url": c["url"]}
                 for c in chunks],
        warnings=warnings,
    )
