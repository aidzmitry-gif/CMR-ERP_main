"""Standalone sales mailbox staging and loopback relay.

The package intentionally has no dependency on the CRM application.  It keeps
mail collection and HTTP delivery in separate, durable stages.
"""

from .config import Config, ConfigError, load_config
from .queue import Queue, QueueError

__all__ = ["Config", "ConfigError", "Queue", "QueueError", "load_config"]
