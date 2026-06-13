"""Custom nodes for the example plugin.

A node is just a function decorated with ``@node``. Its parameters become the
step's ``with:`` inputs (validated with pydantic), and whatever it returns
becomes ``${{ steps.<id>.output }}``.
"""

from __future__ import annotations

import json
import os
import urllib.request

from stepyard.sdk import NodeResult, NodeStatus, node


@node(name="text.wordcount")
def wordcount(text: str) -> dict[str, int]:
    """Count words and characters in a string.

    Outputs:
        words: number of whitespace-separated words.
        chars: number of characters.
    """
    return {"words": len(text.split()), "chars": len(text)}


@node(name="slack.notify")
def slack_notify(text: str, webhook_url: str | None = None) -> NodeResult:
    """Post a message to a Slack incoming webhook.

    Args:
        text: The message body.
        webhook_url: Override the webhook URL. Defaults to the ``SLACK_WEBHOOK``
            environment variable.
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK")
    if not url:
        return NodeResult(
            status=NodeStatus.FAILED,
            error="slack.notify needs `webhook_url` or the SLACK_WEBHOOK env var.",
        )

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - url is operator-provided
        return NodeResult(status=NodeStatus.SUCCESS, output={"status": resp.status})


__all__ = ["slack_notify", "wordcount"]
