"""Security layer: capability & consent gating (PRD §21, §39, §55)."""

from luxion.security.capabilities import (
    CAPABILITIES,
    Capability,
    CapabilityDecision,
    CapabilityInfo,
    CapabilityReport,
    CapabilityStore,
    get_capabilities,
    reset_capabilities,
)

__all__ = [
    "CAPABILITIES",
    "Capability",
    "CapabilityDecision",
    "CapabilityInfo",
    "CapabilityReport",
    "CapabilityStore",
    "get_capabilities",
    "reset_capabilities",
]
