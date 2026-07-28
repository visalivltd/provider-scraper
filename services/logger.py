import sys
from loguru import logger
from config import LOG_FILE

# Configure logger
logger.remove()

# Console handler (clean formatting)
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{message}</cyan>"
)

# File handler
logger.add(
    LOG_FILE,
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8"
)

__all__ = ["logger"]
