"""Public SDK for Stepyard plugins.

For plugin authors the recommended import pattern is::

    from stepyard.sdk import node, trigger, NodeContext, NodeResult

Testing utilities are available in :mod:`stepyard.sdk.testing`::

    from stepyard.sdk.testing import invoke_node, fake_context, run_node
"""

from stepyard.sdk.hooks import StepExecutionHook
from stepyard.sdk.inputs import InputCollector, InputRequest, input_collector
from stepyard.sdk.node import NodeContext, NodeResult, NodeStatus, node
from stepyard.sdk.trigger import trigger

__all__ = [
    "InputCollector",
    "InputRequest",
    "NodeContext",
    "NodeResult",
    "NodeStatus",
    "StepExecutionHook",
    "input_collector",
    "node",
    "trigger",
]
