from app.logging_config import configure_logging

from .runner import run_forever

configure_logging()
run_forever()
