"""
Automatic backups of the SQLite database (data/edr.db).

Called once when the bot starts and, in addition, periodically every
BACKUP_INTERVAL_HOURS while the bot keeps running (see main.py).
Each backup is a timestamped copy; at most BACKUP_KEEP_COUNT copies are
kept, with the oldest ones purged automatically.
"""
import os
import shutil
import glob
from datetime import datetime, timezone

from bot.config import DB_PATH, BACKUP_DIR, BACKUP_KEEP_COUNT
from bot.logger import log

BACKUP_PREFIX = "edr_"
BACKUP_SUFFIX = ".db"


def backup_database():
    """Copy data/edr.db to data/backups/edr_YYYYMMDD_HHMMSS.db and purge
    older backups once BACKUP_KEEP_COUNT is exceeded. Never raises if
    something goes wrong (a failed backup shouldn't crash the bot);
    it's just logged instead."""
    try:
        if not os.path.exists(DB_PATH):
            log.info("[BACKUP] edr.db does not exist yet, skipping initial backup.")
            return None

        os.makedirs(BACKUP_DIR, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_DIR, f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}")

        # copy2 preserves metadata; since SQLite is a single file, it's
        # enough that no write is happening at that exact instant. Worst
        # case is a backup with a half-finished transaction, which is
        # unlikely and acceptable for a safety backup (this isn't a
        # second-by-second critical file).
        shutil.copy2(DB_PATH, dest)
        log.info(f"[BACKUP] Backup created: {dest}")

        _prune_old_backups()
        return dest

    except Exception as e:
        log.error(f"[BACKUP] Error creating backup: {e}")
        return None


def _prune_old_backups():
    pattern = os.path.join(BACKUP_DIR, f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)  # newest first

    for old_backup in backups[BACKUP_KEEP_COUNT:]:
        try:
            os.remove(old_backup)
            log.info(f"[BACKUP] Old backup removed: {old_backup}")
        except Exception as e:
            log.warning(f"[BACKUP] Could not remove old backup {old_backup}: {e}")