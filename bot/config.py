"""
Central configuration for the Discord EDR.
Reads variables from the .env file (never commit your real token to a public repo).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot token (create one at https://discord.com/developers/applications)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ID of the channel where real-time alerts are posted (optional)
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0")) or None

# Path to the local SQLite database
DB_PATH = os.getenv("DB_PATH", "data/edr.db")

# Path to the plain-text log file (in addition to the database)
LOG_FILE = os.getenv("LOG_FILE", "logs/edr.log")

# Path to the JSON file holding the configurable rules (keywords, links, load)
RULES_PATH = os.getenv("RULES_PATH", "data/rules.json")

# --- Log rotation ---
# Once edr.log exceeds this size it gets rotated (edr.log.1, edr.log.2...).
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MB by default
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))  # how many old .log.N files to keep

# --- Retries for moderation actions (pending_actions) ---
# If an action fails for a recoverable reason (rate limit, network timeout...)
# it's retried with exponential backoff instead of being marked as an error
# on the first failure.
ACTION_MAX_RETRIES = int(os.getenv("ACTION_MAX_RETRIES", "5"))
ACTION_RETRY_BASE_SECONDS = int(os.getenv("ACTION_RETRY_BASE_SECONDS", "10"))  # backoff: base * 2^attempt
ACTION_RETRY_MAX_SECONDS = int(os.getenv("ACTION_RETRY_MAX_SECONDS", "600"))  # cap of 10 min between retries

# --- Automatic database backups ---
BACKUP_DIR = os.getenv("BACKUP_DIR", "data/backups")
BACKUP_KEEP_COUNT = int(os.getenv("BACKUP_KEEP_COUNT", "14"))  # how many copies to keep
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "24"))  # periodic backup, on top of the startup one

# Simple detection rules (feel free to extend these)
DETECTION_RULES = {
    # Number of messages within the time window that counts as spam
    "spam_message_threshold": 6,
    "spam_time_window_seconds": 8,

    # Number of mentions in a single message considered suspicious
    "mass_mention_threshold": 5,

    # Flag messages containing invite links to external servers
    "invite_link_flag": True,

    # Number of new-account joins in a short time -> possible raid
    "raid_join_threshold": 5,
    "raid_join_window_seconds": 30,
    "new_account_days_threshold": 7,  # accounts created less than N days ago

    # Account that posts a link/invite seconds after joining
    "fast_post_enabled": True,
    "fast_post_window_seconds": 30,
}