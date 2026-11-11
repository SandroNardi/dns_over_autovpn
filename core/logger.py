import copy
import logging

from rich.logging import RichHandler
from rich.text import Text

ENABLE_FILE_LOGGING = True
LOG_FILENAME = "application.log"


class DeMarkupFormatter(logging.Formatter):
    """Write plain text to the log file. Rich markup stays on the console."""

    def format(self, record):
        record_copy = copy.copy(record)
        if isinstance(record_copy.msg, str):
            record_copy.msg = Text.from_markup(record_copy.msg).plain
        return super().format(record_copy)


def setup_logger(name="vpn_dns_inventory"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        console_handler = RichHandler(rich_tracebacks=True, markup=True)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)
        if ENABLE_FILE_LOGGING:
            file_handler = logging.FileHandler(LOG_FILENAME, mode="a", encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(
                DeMarkupFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(file_handler)
    return logger


logger = setup_logger()
