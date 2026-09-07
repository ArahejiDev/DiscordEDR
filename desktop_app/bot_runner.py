"""
Starts and stops the Discord bot INSIDE the same process as the desktop
panel, on a separate thread with its own asyncio event loop.

Why a thread and not a separate process (subprocess):
- It's what lets everything work with a single double-click once packaged
  with PyInstaller into one .exe: there's no second .exe to launch and no
  "python -m bot.main" path to resolve from inside the executable.
- discord.py can run on a non-main thread as long as you use
  bot.start(token) (not bot.run()) inside your own asyncio loop: run()
  tries to install signal handlers (Ctrl+C) that only work on the main
  thread, start() doesn't.
"""
import asyncio
import threading

import bot.config as config
from bot.logger import log

_thread = None
_loop = None
_start_error = None


def _run(token):
    global _loop, _start_error
    import bot.main as bot_module  # deferred import: builds the Client the first time it's needed

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _start_error = None
    try:
        _loop.run_until_complete(bot_module.bot.start(token))
    except Exception as e:
        _start_error = str(e)
        log.error(f"[BOT] No se pudo iniciar: {e}")
    finally:
        try:
            _loop.run_until_complete(_loop.shutdown_asyncgens())
        except Exception:
            pass
        _loop.close()


def start_bot():
    """Starts the bot on a daemon thread. Returns (ok: bool, message: str)."""
    global _thread
    if is_running():
        return False, "The bot is already running."
    if not config.DISCORD_TOKEN:
        return False, "Missing DISCORD_TOKEN. Set it in the .env file before starting the bot."

    _thread = threading.Thread(target=_run, args=(config.DISCORD_TOKEN,), daemon=True)
    _thread.start()
    return True, "Iniciando bot..."


def stop_bot(timeout=5):
    """Asks the bot to log out cleanly. Returns (ok: bool, message: str)."""
    if not is_running() or _loop is None:
        return False, "The bot is not running."

    import bot.main as bot_module
    try:
        future = asyncio.run_coroutine_threadsafe(bot_module.bot.close(), _loop)
        future.result(timeout=timeout)
    except Exception as e:
        log.warning(f"[BOT] Warning while stopping: {e}")
    _thread.join(timeout=timeout)
    return True, "Bot stopped."


def is_running():
    return _thread is not None and _thread.is_alive()


def status_text():
    """Human-readable text describing the current status, for display in the UI."""
    if not is_running():
        if _start_error:
            return f"Error: {_start_error}"
        return "Stopped"

    import bot.main as bot_module
    try:
        if bot_module.bot.is_ready():
            return f"Connected as {bot_module.bot.user}"
    except Exception:
        pass
    return "Connecting..."