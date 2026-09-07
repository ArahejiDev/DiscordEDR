"""
Very simple rule-based (heuristic) detection engine, inspired by how an
endpoint EDR flags anomalous behavior, but applied to Discord server events.

Everything lives in memory (dicts of deques with timestamps) — no external
services involved.
"""
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from bot.config import DETECTION_RULES
from bot.db.database import log_alert
from bot.logger import log

# In-memory history: user_id -> deque[message timestamps]
_message_history = defaultdict(deque)

# History of joins per server: guild_id -> deque[timestamps]
_join_history = defaultdict(deque)

# Default values for the "fast post right after joining" detection.
# These can be overridden by adding the same keys to DETECTION_RULES in
# bot/config.py; if they're absent, these defaults are used and there's no
# need to touch config.py.
FAST_POST_WINDOW_SECONDS_DEFAULT = 30
FAST_POST_ENABLED_DEFAULT = True


def _prune(dq: deque, window_seconds: int):
    now = time.time()
    while dq and now - dq[0] > window_seconds:
        dq.popleft()


async def check_message_spam(message):
    """Flags a user sending too many messages in a short time window."""
    user_id = message.author.id
    dq = _message_history[user_id]
    dq.append(time.time())
    _prune(dq, DETECTION_RULES["spam_time_window_seconds"])

    if len(dq) >= DETECTION_RULES["spam_message_threshold"]:
        desc = (f"{message.author} sent {len(dq)} messages in "
                f"{DETECTION_RULES['spam_time_window_seconds']}s in #{message.channel}")
        log.warning(f"[ALERT][SPAM] {desc}")
        log_alert("message_spam", message.guild.id if message.guild else None,
                   user_id, str(message.author), desc, severity="medium")
        return True
    return False


async def check_mass_mentions(message):
    """Flags a single message that pings an unusually large number of
    users/roles at once (common in spam/troll messages)."""
    total_mentions = len(message.mentions) + len(message.role_mentions)
    if total_mentions >= DETECTION_RULES["mass_mention_threshold"]:
        desc = f"{message.author} mentioned {total_mentions} users/roles in a single message"
        log.warning(f"[ALERT][MASS_MENTION] {desc}")
        log_alert("mass_mention", message.guild.id if message.guild else None,
                   message.author.id, str(message.author), desc, severity="high")
        return True
    return False


async def check_invite_link(message):
    """Flags messages containing a Discord invite link to another server."""
    if not DETECTION_RULES["invite_link_flag"]:
        return False
    content = message.content.lower()
    if "discord.gg/" in content or "discord.com/invite/" in content:
        desc = f"{message.author} posted an invite link in #{message.channel}"
        log.info(f"[ALERT][INVITE_LINK] {desc}")
        log_alert("invite_link", message.guild.id if message.guild else None,
                   message.author.id, str(message.author), desc, severity="low")
        return True
    return False


async def check_fast_poster(message):
    """Detects the typical scam/nitro-bot pattern: the account joins the
    server and, seconds later, is already posting a link or invite.
    A legitimate user usually says hi or takes a bit before posting
    anything with a link, so requiring the combination (just joined + link)
    keeps false positives low compared to only looking at account age
    (which check_raid_join already covers on the join event)."""
    if not DETECTION_RULES.get("fast_post_enabled", FAST_POST_ENABLED_DEFAULT):
        return False

    member = message.author
    joined_at = getattr(member, "joined_at", None)
    if joined_at is None:
        return False  # not a guild Member (e.g. a DM) or no join data available

    window = DETECTION_RULES.get("fast_post_window_seconds", FAST_POST_WINDOW_SECONDS_DEFAULT)
    seconds_since_join = (datetime.now(timezone.utc) - joined_at).total_seconds()
    if seconds_since_join < 0 or seconds_since_join > window:
        return False

    content = message.content.lower()
    has_link = ("http://" in content or "https://" in content
                or "discord.gg/" in content or "www." in content)
    if not has_link:
        return False

    desc = (f"{member} posted a link {int(seconds_since_join)}s after joining "
            f"the server in #{message.channel} (typical scam/nitro-bot pattern)")
    log.warning(f"[ALERT][FAST_POST_LINK] {desc}")
    log_alert("fast_post_link", message.guild.id if message.guild else None,
               member.id, str(member), desc, severity="high")
    return True


async def check_raid_join(member):
    """Flags a burst of member joins in a short window (possible raid), and
    separately flags any join from a very recently created account."""
    guild_id = member.guild.id
    dq = _join_history[guild_id]
    dq.append(time.time())
    _prune(dq, DETECTION_RULES["raid_join_window_seconds"])

    account_age_days = (datetime.now(timezone.utc) - member.created_at).days
    is_new_account = account_age_days < DETECTION_RULES["new_account_days_threshold"]

    if len(dq) >= DETECTION_RULES["raid_join_threshold"]:
        desc = (f"{len(dq)} joins in {DETECTION_RULES['raid_join_window_seconds']}s "
                f"(possible raid). Latest: {member} (account created {account_age_days} days ago)")
        log.warning(f"[ALERT][RAID_JOIN] {desc}")
        log_alert("raid_join", guild_id, member.id, str(member), desc, severity="critical")
        return True

    if is_new_account:
        desc = f"{member} joined with a very new account ({account_age_days} days old)"
        log.info(f"[ALERT][NEW_ACCOUNT] {desc}")
        log_alert("new_account_join", guild_id, member.id, str(member), desc, severity="low")

    return False