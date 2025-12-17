from __future__ import annotations

import logging
from os import getenv


def setup_logging(*, level: str | None = None) -> None:
    level_name = (level or getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

