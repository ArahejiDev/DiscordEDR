"""
Message-related events: creation, edit, and deletion.
"""
from bot.db.database import log_event
from bot.logger import log
from bot.detection import check_message_spam, check_mass_mentions, check_invite_link, check_fast_poster
from bot.rule_engine import rule_engine


async def handle_message(message, bot):
    if message.author.bot:
        return  # ignore messages from other bots (avoids noise/loops)

    log_event(
        event_type="message_create",
        guild_id=message.guild.id if message.guild else None,
        channel_id=message.channel.id,
        user_id=message.author.id,
        username=str(message.author),
        content=message.content,
    )
    log.info(f"[MSG] #{message.channel} | {message.author}: {message.content[:200]}")

    # Fixed detection rules (spam, mass mentions, Discord invites,
    # a freshly-joined account posting a link)
    await check_message_spam(message)
    await check_mass_mentions(message)
    await check_invite_link(message)
    await check_fast_poster(message)

    # User-configurable rules (keywords, generic links, load)
    triggered = await rule_engine.evaluate_message(message)

    # If any rule asks for the message to be deleted, delete it (requires
    # the "Manage Messages" permission)
    if any(t["delete_message"] for t in triggered):
        try:
            await message.delete()
        except Exception as e:
            log.warning(f"Could not delete message from {message.author}: {e}")


async def handle_message_edit(before, after, bot):
    if after.author.bot:
        return

    log_event(
        event_type="message_edit",
        guild_id=after.guild.id if after.guild else None,
        channel_id=after.channel.id,
        user_id=after.author.id,
        username=str(after.author),
        content=after.content,
        extra=f"before: {before.content[:300]}",
    )
    log.info(f"[EDIT] #{after.channel} | {after.author}: '{before.content}' -> '{after.content}'")


async def handle_message_delete(message, bot):
    if message.author.bot:
        return

    log_event(
        event_type="message_delete",
        guild_id=message.guild.id if message.guild else None,
        channel_id=message.channel.id,
        user_id=message.author.id,
        username=str(message.author),
        content=message.content,
    )
    log.info(f"[DELETE] #{message.channel} | {message.author}: {message.content[:200]}")