from string import Template
from typing import Any

from stepyard.sdk.node import node


@node(name="text.template")
def text_template(template: str, variables: dict[str, Any]) -> str:
    """Renders a string template substituting variables safely.

    Args:
        template: The template string (using $var or ${var} notation).
        variables: Dictionary of variable names and their values.

    Outputs:
        Returns the interpolated string.
    """
    str_vars = {k: str(v) for k, v in variables.items()}
    return Template(template).safe_substitute(str_vars)


@node(name="text.replace")
def text_replace(text: str, old: str, new: str) -> str:
    """Replaces all occurrences of old with new in text.

    Args:
        text: The original text.
        old: The substring to find.
        new: The string to replace it with.

    Outputs:
        Returns the modified string.
    """
    return text.replace(old, new)


__all__ = ["text_replace", "text_template"]
