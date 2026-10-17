import logging

from app.core.config import get_settings


def setup_logging() -> None:
    level = get_settings().log_level
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries can be very chatty at INFO; keep them quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)