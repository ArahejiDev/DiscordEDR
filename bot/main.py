"""
Discord EDR — entry point.

Run with: python -m bot.main
(from the project root, with the virtual environment activated)
"""
from datetime import timedelta

import discord
from discord.ext import commands

from bot.config import (
    DISCORD_TOKEN, ALERT_CHANNEL_ID,
    ACTION_MAX_RETRIES, ACTION_RETRY_BASE_SECONDS, ACTION_RETRY_MAX_SECONDS,
    BACKUP_INTERVAL_HOURS,
)
from bot.db.database import (
    init_db, upsert_member, fetch_pending_actions, resolve_action, schedule_retry, log_alert,
)
from bot.backup import backup_database
from bot.logger import log
from discord.ext import commands, tasks
from bot.events.message_events import handle_message, handle_message_edit, handle_message_delete
from bot.events.member_events import (
    handle_member_join, handle_member_remove, handle_member_ban, handle_member_update
)
from bot.rule_engine import rule_engine

# --- Intents: we need message content and members (enable in the Dev Portal) ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True  # for ban events

bot = commands.Bot(command_prefix="!edr ", intents=intents)

# Limit imposed by Discord's own API for a timeout: 28 days.
MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60


def _is_retryable_error(e):
    """Decides whether a failure deserves a later retry or is final.
    Rate limits (429) and server/network errors (5xx, timeouts) are
    transient; insufficient permissions, already-missing resources, etc.
    won't fix themselves no matter how many times they're retried."""
    if isinstance(e, discord.HTTPException):
        return e.status == 429 or e.status >= 500
    if isinstance(e, (TimeoutError, ConnectionError)):
        return True
    return False


async def _fail_or_retry(action, e, label):
    """Single error-handling point for process_pending_actions: if the
    failure is recoverable and the retry budget isn't exhausted, reschedule
    the action with exponential backoff instead of marking it as an error."""
    action_id = action["id"]
    retry_count = action["retry_count"] or 0

    if _is_retryable_error(e) and retry_count < ACTION_MAX_RETRIES:
        delay = min(ACTION_RETRY_BASE_SECONDS * (2 ** retry_count), ACTION_RETRY_MAX_SECONDS)
        schedule_retry(action_id, retry_count + 1, delay, error=str(e))
        log.warning(f"[{label}] Recoverable failure on action {action_id} "
                    f"(attempt {retry_count + 1}/{ACTION_MAX_RETRIES}), "
                    f"retrying in {delay}s: {e}")
    else:
        resolve_action(action_id, "error", str(e))
        log.error(f"[{label}] Final error on action {action_id} (no more retries): {e}")


@tasks.loop(seconds=5)
async def process_pending_actions():
    """Polls the pending_actions table (populated by the desktop panel via
    queue_action) and executes kick/ban/warn/timeout actions using the
    bot's live Discord connection and permissions."""
    for action in fetch_pending_actions():  # no filter: picks up kick, ban, warn and timeout
        action_type = action["action_type"]
        guild = bot.get_guild(int(action["guild_id"])) if action["guild_id"] else None
        if not guild:
            resolve_action(action["id"], "error", "Server not found")
            continue

        member = guild.get_member(int(action["user_id"]))

        if action_type == "kick":
            if not member:
                resolve_action(action["id"], "error", "Member not found (may have already left the server)")
                continue
            try:
                await member.kick(reason=action["reason"] or "Kicked from the EDR panel")
                resolve_action(action["id"], "done")
                log.warning(f"[KICK] {member} kicked from the desktop panel (reason: {action['reason']})")
                log_alert("manual_kick", guild.id, member.id, str(member),
                           f"{member} was manually kicked from the desktop panel", severity="high")
            except Exception as e:
                await _fail_or_retry(action, e, "KICK")

        elif action_type == "ban":
            # Banning doesn't require the member to still be in the server,
            # so we skip the `member` check and use user_id directly.
            try:
                user = await bot.fetch_user(int(action["user_id"]))
                await guild.ban(user, reason=action["reason"] or "Banned from the EDR panel",
                                 delete_message_seconds=0)
                resolve_action(action["id"], "done")
                log.warning(f"[BAN] {user} banned from the desktop panel (reason: {action['reason']})")
                log_alert("manual_ban", guild.id, user.id, str(user),
                           f"{user} was manually banned from the desktop panel", severity="critical")
            except Exception as e:
                await _fail_or_retry(action, e, "BAN")

        elif action_type == "warn":
            if not member:
                resolve_action(action["id"], "error", "Member not found (may have already left the server)")
                continue
            reason = action["reason"] or "No reason specified"
            try:
                await member.send(
                    f"⚠️ You received a warning in **{guild.name}**.\nReason: {reason}"
                )
                dm_sent = True
            except Exception:
                # The user may have DMs closed; not a fatal error, the
                # warning is still recorded in the history either way.
                dm_sent = False

            resolve_action(action["id"], "done")
            log.warning(f"[WARN] {member} warned from the desktop panel (reason: {reason})")
            log_alert("manual_warn", guild.id, member.id, str(member),
                       f"{member} received a manual warning from the panel"
                       f"{'' if dm_sent else ' (DM could not be sent)'}: {reason}",
                       severity="medium")

        elif action_type == "timeout":
            if not member:
                resolve_action(action["id"], "error", "Member not found (may have already left the server)")
                continue

            duration = action["duration_seconds"] or 600  # 10 minutes by default if not specified
            duration = min(duration, MAX_TIMEOUT_SECONDS)
            reason = action["reason"] or "Timeout applied from the EDR panel"
            try:
                until = discord.utils.utcnow() + timedelta(seconds=duration)
                await member.timeout(until, reason=reason)
                resolve_action(action["id"], "done")
                mins = duration // 60
                log.warning(f"[TIMEOUT] {member} muted for {mins} min from the desktop "
                            f"panel (reason: {reason})")
                log_alert("manual_timeout", guild.id, member.id, str(member),
                           f"{member} was manually muted for {mins} minutes from the panel: {reason}",
                           severity="medium")
            except Exception as e:
                await _fail_or_retry(action, e, "TIMEOUT")

        else:
            resolve_action(action["id"], "error", f"Unknown action type: {action_type}")


@process_pending_actions.before_loop
async def before_process_pending_actions():
    await bot.wait_until_ready()


@tasks.loop(hours=BACKUP_INTERVAL_HOURS)
async def periodic_backup():
    backup_database()


@periodic_backup.before_loop
async def before_periodic_backup():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    # Backup BEFORE init_db: this keeps a copy of the previous state in
    # case a schema migration (new columns, etc.) runs into trouble.
    backup_database()
    init_db()
    log.info(f"EDR connected as {bot.user} (id: {bot.user.id})")
    log.info(f"Watching {len(bot.guilds)} server(s): {[g.name for g in bot.guilds]}")
    if ALERT_CHANNEL_ID:
        channel = bot.get_channel(ALERT_CHANNEL_ID)
        if channel:
            await channel.send(" **Discord EDR** active and monitoring.")

    if not process_pending_actions.is_running():
        process_pending_actions.start()
    if not periodic_backup.is_running():
        periodic_backup.start()

@bot.event
async def on_message(message):
    await handle_message(message, bot)
    await bot.process_commands(message)  # keeps text commands working


@bot.event
async def on_message_edit(before, after):
    await handle_message_edit(before, after, bot)


@bot.event
async def on_message_delete(message):
    await handle_message_delete(message, bot)


@bot.event
async def on_member_join(member):
    await handle_member_join(member, bot)


@bot.event
async def on_member_remove(member):
    await handle_member_remove(member, bot)


@bot.event
async def on_member_ban(guild, user):
    await handle_member_ban(guild, user, bot)


@bot.event
async def on_member_update(before, after):
    await handle_member_update(before, after, bot)


# --- Basic lookup commands (optional, handy for checking things from Discord itself) ---
@bot.command(name="alertas")
@commands.has_permissions(administrator=True)
async def alertas(ctx, limite: int = 10):
    """Shows the last N recorded alerts. Usage: !edr alertas 15"""
    from bot.db.database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()

    if not rows:
        await ctx.send("No hay alertas registradas.")
        return

    lines = [f"`{r['timestamp']}` [{r['severity'].upper()}] {r['rule_name']}: {r['description']}"
              for r in rows]
    await ctx.send("\n".join(lines)[:1900])


# =====================================================================
# Rule-management commands (all require administrator permission)
# =====================================================================

@bot.command(name="addword")
@commands.has_permissions(administrator=True)
async def add_word(ctx, palabra: str, severidad: str = "medium", borrar: str = "no"):
    """Adds a watched keyword. Usage: !edr addword <word> [low|medium|high|critical] [si|no]"""
    if severidad not in ("low", "medium", "high", "critical"):
        await ctx.send("Severidad inválida. Usa: low, medium, high o critical.")
        return
    delete_message = borrar.lower() in ("si", "sí", "yes", "true")
    rule = rule_engine.add_keyword(palabra, severity=severidad, delete_message=delete_message)
    await ctx.send(f"✅ Palabra vigilada añadida (id `{rule['id']}`): '{palabra}' "
                    f"[{severidad}]{' + borrado automático' if delete_message else ''}")


@bot.command(name="delword")
@commands.has_permissions(administrator=True)
async def del_word(ctx, rule_id: str):
    """Removes a watched keyword by its id. Usage: !edr delword <id>"""
    ok = rule_engine.remove_keyword(rule_id)
    await ctx.send("✅ Eliminada." if ok else "❌ No se encontró esa regla.")


@bot.command(name="words")
@commands.has_permissions(administrator=True)
async def list_words(ctx):
    """Lists the currently watched keywords."""
    rules = rule_engine.list_keywords()
    if not rules:
        await ctx.send("No hay palabras vigiladas configuradas.")
        return
    lines = [f"`{r['id']}` '{r['word']}' [{r['severity']}]"
             f"{' 🗑️borra' if r['delete_message'] else ''}" for r in rules]
    await ctx.send("\n".join(lines)[:1900])


@bot.command(name="links")
@commands.has_permissions(administrator=True)
async def toggle_links(ctx, estado: str, severidad: str = "low"):
    """Enables/disables link detection. Usage: !edr links on|off [severity]"""
    if estado.lower() not in ("on", "off"):
        await ctx.send("Uso: !edr links on|off [severidad]")
        return
    ld = rule_engine.set_link_detection(enabled=(estado.lower() == "on"), severity=severidad)
    await ctx.send(f"✅ Detección de links: {'activada' if ld['enabled'] else 'desactivada'} "
                    f"[{ld['severity']}]")


@bot.command(name="whitelist")
@commands.has_permissions(administrator=True)
async def whitelist_domain(ctx, accion: str, dominio: str):
    """Manages the allowed-domain whitelist. Usage: !edr whitelist add|del youtube.com"""
    if accion.lower() == "add":
        wl = rule_engine.add_whitelist_domain(dominio)
    elif accion.lower() == "del":
        wl = rule_engine.remove_whitelist_domain(dominio)
    else:
        await ctx.send("Uso: !edr whitelist add|del <dominio>")
        return
    await ctx.send(f"Whitelist actual: {', '.join(wl) if wl else '(vacía)'}")


@bot.command(name="addload")
@commands.has_permissions(administrator=True)
async def add_load(ctx, scope: str, max_mensajes: int, ventana_segundos: int, severidad: str = "medium"):
    """Adds a load (flood) rule. Usage: !edr addload user|channel 6 8 [severity]"""
    if scope not in ("user", "channel"):
        await ctx.send("El scope debe ser 'user' o 'channel'.")
        return
    rule = rule_engine.add_load_rule(scope, max_mensajes, ventana_segundos, severity=severidad)
    await ctx.send(f"✅ Regla de carga añadida (id `{rule['id']}`): máx {max_mensajes} "
                    f"mensajes / {ventana_segundos}s por {scope} [{severidad}]")


@bot.command(name="delload")
@commands.has_permissions(administrator=True)
async def del_load(ctx, rule_id: str):
    """Removes a load rule by its id. Usage: !edr delload <id>"""
    ok = rule_engine.remove_load_rule(rule_id)
    await ctx.send("✅ Eliminada." if ok else "❌ No se encontró esa regla.")


@bot.command(name="loads")
@commands.has_permissions(administrator=True)
async def list_loads(ctx):
    """Lists the currently configured load rules."""
    rules = rule_engine.list_load_rules()
    if not rules:
        await ctx.send("No hay reglas de carga configuradas.")
        return
    lines = [f"`{r['id']}` {r['scope']}: máx {r['max_messages']} msg / {r['window_seconds']}s "
             f"[{r['severity']}]" for r in rules]
    await ctx.send("\n".join(lines)[:1900])


@bot.command(name="reglas")
@commands.has_permissions(administrator=True)
async def show_rules_summary(ctx):
    """Summary of all currently active configurable rules."""
    ld = rule_engine.rules["link_detection"]
    resumen = [
        f"**Palabras vigiladas:** {len(rule_engine.rules['keywords'])}",
        f"**Detección de links:** {'ON' if ld['enabled'] else 'OFF'} [{ld['severity']}]",
        f"**Whitelist de dominios:** {', '.join(ld['whitelist_domains']) or '(vacía)'}",
        f"**Reglas de carga:** {len(rule_engine.rules['load_rules'])}",
    ]
    await ctx.send("\n".join(resumen))


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit(
            "Missing DISCORD_TOKEN. Copy .env.example to .env and add your bot token."
        )
    bot.run(DISCORD_TOKEN)