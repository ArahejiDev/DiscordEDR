"""
Dynamic rule engine. Unlike detection.py (fixed join/raid rules), this
engine stores its configuration in an editable JSON file (data/rules.json)
and can be updated on the fly from Discord commands, without restarting
the bot or touching any code.

Supported rule types:
  - keywords:       fires an alert if a message contains a given word/phrase
  - link_detection:  fires an alert if a message contains a URL (with an optional whitelist)
  - load_rules:     fires an alert if there are too many messages within a
                     time window (per user or per channel) -> detects flooding/mass spam
"""
import re
import time
import json
import os
import uuid
from collections import defaultdict, deque

from bot.config import RULES_PATH
from bot.db.database import log_alert
from bot.logger import log

URL_REGEX = re.compile(r'(https?://\S+|www\.\S+)', re.IGNORECASE)

DEFAULT_RULES = {
    "keywords": [],
    "link_detection": {
        "enabled": False,
        "severity": "low",
        "delete_message": False,
        "whitelist_domains": []
    },
    "load_rules": []
}


def load_rules():
    if not os.path.exists(RULES_PATH):
        save_rules(DEFAULT_RULES)
        return json.loads(json.dumps(DEFAULT_RULES))
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_rules(rules):
    directory = os.path.dirname(RULES_PATH)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


class RuleEngine:
    def __init__(self):
        self.rules = load_rules()
        # In-memory history for load rules: rule_id -> entity -> deque[timestamps]
        self._user_history = defaultdict(lambda: defaultdict(deque))
        self._channel_history = defaultdict(lambda: defaultdict(deque))

    def reload(self):
        self.rules = load_rules()

    # ---------------------------------------------------------------
    # Watched-keyword management
    # ---------------------------------------------------------------
    def add_keyword(self, word, severity="medium", whole_word=True,
                     case_sensitive=False, delete_message=False):
        rule = {
            "id": uuid.uuid4().hex[:8],
            "word": word,
            "whole_word": whole_word,
            "case_sensitive": case_sensitive,
            "severity": severity,
            "delete_message": delete_message,
        }
        self.rules["keywords"].append(rule)
        save_rules(self.rules)
        return rule

    def remove_keyword(self, rule_id):
        before = len(self.rules["keywords"])
        self.rules["keywords"] = [r for r in self.rules["keywords"] if r["id"] != rule_id]
        save_rules(self.rules)
        return len(self.rules["keywords"]) < before

    def list_keywords(self):
        return self.rules["keywords"]

    # ---------------------------------------------------------------
    # Link-detection management
    # ---------------------------------------------------------------
    def set_link_detection(self, enabled=None, severity=None, delete_message=None):
        ld = self.rules["link_detection"]
        if enabled is not None:
            ld["enabled"] = enabled
        if severity is not None:
            ld["severity"] = severity
        if delete_message is not None:
            ld["delete_message"] = delete_message
        save_rules(self.rules)
        return ld

    def add_whitelist_domain(self, domain):
        domain = domain.lower().strip()
        if domain not in self.rules["link_detection"]["whitelist_domains"]:
            self.rules["link_detection"]["whitelist_domains"].append(domain)
            save_rules(self.rules)
        return self.rules["link_detection"]["whitelist_domains"]

    def remove_whitelist_domain(self, domain):
        domain = domain.lower().strip()
        wl = self.rules["link_detection"]["whitelist_domains"]
        if domain in wl:
            wl.remove(domain)
            save_rules(self.rules)
        return wl

    # ---------------------------------------------------------------
    # Load-rule (flood) management
    # ---------------------------------------------------------------
    def add_load_rule(self, scope, max_messages, window_seconds, severity="medium"):
        assert scope in ("user", "channel"), "scope must be 'user' or 'channel'"
        rule = {
            "id": uuid.uuid4().hex[:8],
            "scope": scope,
            "max_messages": max_messages,
            "window_seconds": window_seconds,
            "severity": severity,
        }
        self.rules["load_rules"].append(rule)
        save_rules(self.rules)
        return rule

    def remove_load_rule(self, rule_id):
        before = len(self.rules["load_rules"])
        self.rules["load_rules"] = [r for r in self.rules["load_rules"] if r["id"] != rule_id]
        save_rules(self.rules)
        return len(self.rules["load_rules"]) < before

    def list_load_rules(self):
        return self.rules["load_rules"]

    # ---------------------------------------------------------------
    # Evaluate a message against every active rule
    # ---------------------------------------------------------------
    async def evaluate_message(self, message):
        """
        Evaluates a message against every configured rule.
        Returns a list of dicts: {rule_type, severity, description, delete_message}

        Reloads the rules from disk before evaluating, so changes made from
        another process (e.g. the desktop panel) apply immediately without
        restarting the bot.
        """
        self.reload()
        triggered = []
        content = message.content or ""

        # --- Watched keywords ---
        for rule in self.rules["keywords"]:
            word = rule["word"]
            text = content if rule["case_sensitive"] else content.lower()
            target = word if rule["case_sensitive"] else word.lower()

            if rule["whole_word"]:
                found = re.search(r"\b" + re.escape(target) + r"\b", text) is not None
            else:
                found = target in text

            if found:
                desc = f"{message.author} used the watched keyword '{word}' in #{message.channel}"
                self._log(message, "keyword", rule["severity"], desc)
                triggered.append({
                    "rule_type": "keyword", "severity": rule["severity"],
                    "description": desc, "delete_message": rule.get("delete_message", False)
                })

        # --- Link detection ---
        ld = self.rules["link_detection"]
        if ld.get("enabled"):
            urls = URL_REGEX.findall(content)
            whitelist = ld.get("whitelist_domains", [])
            flagged = [u for u in urls if not any(dom in u.lower() for dom in whitelist)]
            if flagged:
                desc = f"{message.author} posted a link ({flagged[0]}) in #{message.channel}"
                self._log(message, "link", ld["severity"], desc)
                triggered.append({
                    "rule_type": "link", "severity": ld["severity"],
                    "description": desc, "delete_message": ld.get("delete_message", False)
                })

        # --- Load rules (flood) ---
        for rule in self.rules["load_rules"]:
            if rule["scope"] == "user":
                dq = self._user_history[rule["id"]][message.author.id]
            else:
                dq = self._channel_history[rule["id"]][message.channel.id]

            dq.append(time.time())
            self._prune(dq, rule["window_seconds"])

            if len(dq) >= rule["max_messages"]:
                scope_label = "user" if rule["scope"] == "user" else "channel"
                desc = (f"High message load ({scope_label}): {len(dq)} messages in "
                        f"{rule['window_seconds']}s — triggered by {message.author} in #{message.channel}")
                self._log(message, "load", rule["severity"], desc)
                triggered.append({
                    "rule_type": "load", "severity": rule["severity"],
                    "description": desc, "delete_message": False
                })
                dq.clear()  # avoid re-alerting on every message for the duration of the spike

        return triggered

    @staticmethod
    def _prune(dq, window_seconds):
        now = time.time()
        while dq and now - dq[0] > window_seconds:
            dq.popleft()

    @staticmethod
    def _log(message, rule_type, severity, desc):
        log.warning(f"[ALERT][{rule_type.upper()}] {desc}")
        log_alert(rule_type, message.guild.id if message.guild else None,
                   message.author.id, str(message.author), desc, severity=severity)


# Single instance shared across the whole bot
rule_engine = RuleEngine()