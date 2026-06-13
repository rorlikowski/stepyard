"""
Stepyard trigger implementations using APScheduler.

Maps flow trigger configurations from YAML into APScheduler BaseTrigger instances.
"""

import inspect
import logging

from stepyard.plugin import CapabilityProvider, discover_capabilities

logger = logging.getLogger("stepyard.scheduler.triggers")


def build_apscheduler_trigger(
    trigger_model,
    project_dir: str | None = None,
    registry: CapabilityProvider | None = None,
) -> tuple[object, str] | None:
    """Construct an APScheduler trigger instance from a ``TriggerModel``.

    Returns a tuple of (APSchedulerTrigger, trigger_type_string), or None.
    """
    uses = trigger_model.uses
    cfg = trigger_model.with_config

    if registry is None:
        if project_dir is None:
            raise ValueError("project_dir is required when registry is not provided")
        registry = discover_capabilities(project_dir)
    custom_trigger = registry.get_trigger(uses)
    if custom_trigger:
        try:
            # Validate configuration using Pydantic model
            validated_cfg = custom_trigger.__stepyard_input_model__(**cfg).model_dump()
            trigger_instance = custom_trigger(**validated_cfg)
            if inspect.isasyncgen(trigger_instance):
                return trigger_instance, uses
            return trigger_instance, uses
        except Exception as exc:
            logger.error("Failed to build custom trigger '%s': %s", uses, exc)
            return None

    logger.warning("Unsupported trigger type: '%s'", uses)
    return None
