"""Plugin infrastructure internals for Stepyard.

For plugin *authors*, use ``stepyard.sdk`` - that is the stable public API::

    from stepyard.sdk import node, trigger, NodeContext, NodeResult

This module (``stepyard.plugin``) exposes the internal registry and host
classes used by the engine and CLI.  Its API may change across minor versions.
"""

from stepyard.plugins.host import (
    CapabilityInfo,
    CapabilityProvider,
    CapabilityRegistry,
    DiscoveryError,
    DiscoveryReport,
    PluginHost,
    discover_capabilities,
)
from stepyard.plugins.invoker import NodeInvocationService, NodeInvoker
from stepyard.plugins.manager import PluginManager

__all__ = [
    "CapabilityInfo",
    "CapabilityProvider",
    "CapabilityRegistry",
    "DiscoveryError",
    "DiscoveryReport",
    "NodeInvocationService",
    "NodeInvoker",
    "PluginHost",
    "PluginManager",
    "discover_capabilities",
]
