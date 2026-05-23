"""
Slack notifications for NECRO — fires when revival candidates are found.
Uses the Slack Web API (slack-sdk) with a bot token.
"""

import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


async def send_revival_alert(project_path: str, count: int, features: list) -> bool:
    """Send a Slack message when new revival candidates are found."""
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_CHANNEL_ID:
        logger.debug("Slack not configured — skipping notification")
        return False

    try:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)

        feature_lines = []
        for f in features[:3]:
            name = f.name if hasattr(f, "name") else f.get("name", "unknown")
            what = ""
            if hasattr(f, "viability") and f.viability:
                what = f.viability.get("what_changed", "")[:80] if isinstance(f.viability, dict) else ""
            feature_lines.append(f"• *{name}* — {what}" if what else f"• *{name}*")

        text = (
            f":coffin: *NECRO found {count} new revival candidate{'s' if count != 1 else ''}* "
            f"in `{project_path}`\n\n"
            + "\n".join(feature_lines)
            + f"\n\nView the full graveyard report at {settings.APP_URL}/#{project_path}"
        )

        await client.chat_postMessage(channel=settings.SLACK_CHANNEL_ID, text=text)
        logger.info("[Slack] Revival alert sent for %s (%d candidates)", project_path, count)
        return True

    except Exception as e:
        logger.warning("Slack send failed: %s", e)
        return False


async def send_issue_created_alert(project_path: str, feature_name: str, issue_url: str) -> bool:
    """Notify Slack when a revival issue is created in GitLab."""
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_CHANNEL_ID:
        return False

    try:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
        text = (
            f":rocket: *Revival issue created* for `{feature_name}` in `{project_path}`\n"
            f"GitLab issue: {issue_url}"
        )
        await client.chat_postMessage(channel=settings.SLACK_CHANNEL_ID, text=text)
        return True

    except Exception as e:
        logger.warning("Slack issue alert failed: %s", e)
        return False
