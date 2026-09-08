"""
SIP Automation Platform.

This package contains the data preparation and calculation components for
the Sales Incentive Plan automation system.
"""

__version__ = "0.1.0"

from sip_automation.application import (
    SIPApplication,
    create_application,
)
from sip_automation.container import ApplicationContainer

__all__ = [
    "ApplicationContainer",
    "SIPApplication",
    "create_application",
]