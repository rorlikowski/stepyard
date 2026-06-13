"""Plugin infrastructure for Stepyard."""

from stepyard.plugins.host import (
    CapabilityInfo,
    CapabilityProvider,
    CapabilityRegistry,
    PluginHost,
    discover_capabilities,
)
from stepyard.plugins.invoker import NodeInvocationService, NodeInvoker
from stepyard.plugins.manager import PluginManager

__all__ = [
    "CapabilityInfo",
    "CapabilityProvider",
    "CapabilityRegistry",
    "NodeInvocationService",
    "NodeInvoker",
    "PluginHost",
    "PluginManager",
    "discover_capabilities",
]
