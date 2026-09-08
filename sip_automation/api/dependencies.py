from __future__ import annotations

from functools import lru_cache

from sip_automation import create_application
from sip_automation.application import SIPApplication


@lru_cache(maxsize=1)
def get_application() -> SIPApplication:
    return create_application()
