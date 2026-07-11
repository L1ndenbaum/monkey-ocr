"""Cross-cutting contracts shared by backend interfaces."""

from .api import ApiEnvelope, InternalStatusCode
from .errors import BusinessError

__all__ = ["ApiEnvelope", "BusinessError", "InternalStatusCode"]
