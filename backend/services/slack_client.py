"""
Slack notifications for NECRO.

Supports two auth methods (first configured one wins):
  1. SLACK_WEBHOOK_URL  — Incoming Webhook (simplest, just one URL)
  2. SLACK_BOT_TOKEN + SLACK_CHANNEL_ID — Slack SDK bot token

Fires automatically after a scan completes with revival candidates,
and on demand via POST /api/report/notify-slack.
"""

import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(settings.SLACK_WEBHOOK_URL) or bool(
        settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID
    )


async def _send_via_webhook(payload: dict) -> bool:
    """POST a Block Kit payload to a Slack Incoming Webhook URL."""
    import httpx

    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(settings.SLACK_WEBHOOK_URL, json=payload)
        r.raise_for_status()
    return True


async def _send_via_sdk(payload: dict) -> bool:
    """Post using slack-sdk AsyncWebClient."""
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    await client.chat_postMessage(
        channel=settings.SLACK_CHANNEL_ID,
        **payload,
    )
    return True


async def _send(payload: dict) -> bool:
    try:
        if settings.SLACK_WEBHOOK_URL:
            return await _send_via_webhook(payload)
        if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
            return await _send_via_sdk(payload)
    except Exception as e:
        logger.warning("Slack send failed: %s", e)
    return False


# ── Public API ────────────────────────────────────────────────────────────────

async def send_revival_alert(
    project_path: str,
    features: list,
    *,
    count: Optional[int] = None,
) -> bool:
    """
    Send a Slack message when a NECRO scan finds revival candidates.
    Called automatically after every scan that finds ≥1 revive_now feature.
    """
    if not _is_configured():
        logger.debug("Slack not configured — skipping revival alert")
        return False

    revive_now = [
        f for f in features
        if (f.get("viability") or {}).get("recommendation") == "revive_now"
    ]
    investigate = [
        f for f in features
        if (f.get("viability") or {}).get("recommendation") == "investigate_further"
    ]
    total = count if count is not None else len(features)

    # Build Block Kit message
    feature_bullets = []
    for f in revive_now[:5]:
        name = f.get("name", "unknown")
        what = (f.get("viability") or {}).get("what_changed", "")[:80]
        score = (f.get("viability") or {}).get("revival_feasibility", "?")
        line = f"• *{name}* — {what}" if what else f"• *{name}*"
        line += f"  _(feasibility: {score}/10)_"
        feature_bullets.append(line)

    if len(revive_now) > 5:
        feature_bullets.append(f"_…and {len(revive_now) - 5} more_")

    header = (
        f":coffin: *NECRO found {len(revive_now)} feature{'s' if len(revive_now) != 1 else ''} "
        f"ready to revive* in `{project_path}`"
    )
    summary = (
        f"*{len(revive_now)}* revive now · "
        f"*{len(investigate)}* investigate · "
        f"*{total - len(revive_now) - len(investigate)}* keep buried"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "NECRO — Feature Revival Alert", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": summary}]},
    ]
    if feature_bullets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(feature_bullets)},
        })
    blocks.append({
        "type": "actions",
        "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": "View Full Report", "emoji": True},
            "url": settings.APP_URL,
            "style": "primary",
        }],
    })

    payload = {"text": header, "blocks": blocks}
    ok = await _send(payload)
    if ok:
        logger.info("[Slack] Revival alert sent for %s (%d candidates)", project_path, len(revive_now))
    return ok


async def send_issue_created_alert(
    project_path: str,
    feature_name: str,
    issue_url: str,
) -> bool:
    """Notify Slack when a revival issue is created in GitLab."""
    if not _is_configured():
        return False

    header = f":rocket: *Revival issue created* for `{feature_name}`"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Repository: `{project_path}`"},
            {"type": "mrkdwn", "text": f"<{issue_url}|Open GitLab issue>"},
        ]},
    ]
    payload = {"text": header, "blocks": blocks}
    ok = await _send(payload)
    if ok:
        logger.info("[Slack] Issue created alert sent for %s — %s", feature_name, issue_url)
    return ok
