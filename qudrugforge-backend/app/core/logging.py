import logging
import sys
from app.core.config import settings

def configure_logging():
    """
    Sets up python logging configuration, setting formats and streaming 
    outputs to stdout for uvicorn runtime logs tracking.
    """
    log_level = logging.DEBUG if settings.APP_DEBUG else logging.INFO
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Silence excessive third-party network library logging to prevent output pollution
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    logger = logging.getLogger("qudrugforge-logging")
    logger.info(f"Logging setup complete. Active level: {logging.getLevelName(log_level)}")
