"""
Member-related events: join, leave, ban, nickname/role changes.
"""
from bot.db.database import log_event, upsert_member, mark_member_left
from bot.logger import log
from bot.detection import check_raid_join


async def handle_member_join(member, bot):
    upsert_member(
        user_id=member.id,
        username=str(member),
        guild_id=member.guild.id,
        joined_at=member.joined_at.isoformat() if member.joined_at else None,
        account_created_at=member.created_at.isoformat(),
    )
    log_event(
        event_type="member_join",
        guild_id=member.guild.id,
        user_id=member.id,
        username=str(member),
    )
    log.info(f"[JOIN] {member} joined {member.guild.name}")

    await check_raid_join(member)


async def handle_member_remove(member, bot):
    mark_member_left(member.id)
    log_event(
        event_type="member_leave",
        guild_id=member.guild.id,
        user_id=member.id,
        username=str(member),
    )
    log.info(f"[LEAVE] {member} left {member.guild.name}")


async def handle_member_ban(guild, user, bot):
    log_event(
        event_type="member_ban",
        guild_id=guild.id,
        user_id=user.id,
        username=str(user),
    )
    log.warning(f"[BAN] {user} was banned from {guild.name}")


async def handle_member_update(before, after, bot):
    # Detects nickname or role changes
    changes = []
    if before.nick != after.nick:
        changes.append(f"nick: '{before.nick}' -> '{after.nick}'")
    if set(before.roles) != set(after.roles):
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added:
            changes.append(f"roles added: {[r.name for r in added]}")
        if removed:
            changes.append(f"roles removed: {[r.name for r in removed]}")

    if changes:
        detail = "; ".join(changes)
        log_event(
            event_type="member_update",
            guild_id=after.guild.id,
            user_id=after.id,
            username=str(after),
            extra=detail,
        )
        log.info(f"[UPDATE] {after}: {detail}")