#!/usr/bin/env python3
"""
VKV Grammar Assistant Bot
- Monitors group messages
- Sends private grammar corrections
- Admin controls
- SQLite logging
- Webhook support
"""

import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from groq import Groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

DB_PATH = "grammar_bot.db"

# ─── Database Setup ────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            sensitivity TEXT DEFAULT 'normal',
            show_explanations INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS known_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            original TEXT,
            corrected TEXT,
            mistake_type TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()

def get_group_settings(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"enabled": bool(row[1]), "sensitivity": row[2], "show_explanations": bool(row[3])}
    return {"enabled": True, "sensitivity": "normal", "show_explanations": True}

def save_group_settings(chat_id, enabled=None, sensitivity=None, show_explanations=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
    if enabled is not None:
        c.execute("UPDATE group_settings SET enabled=? WHERE chat_id=?", (int(enabled), chat_id))
    if sensitivity is not None:
        c.execute("UPDATE group_settings SET sensitivity=? WHERE chat_id=?", (sensitivity, chat_id))
    if show_explanations is not None:
        c.execute("UPDATE group_settings SET show_explanations=? WHERE chat_id=?", (int(show_explanations), chat_id))
    conn.commit()
    conn.close()

def is_known_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM known_users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_known_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO known_users (user_id, username, first_seen) VALUES (?,?,?)",
        (user_id, username, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def log_correction(user_id, chat_id, original, corrected, mistake_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO corrections (user_id, chat_id, original, corrected, mistake_type, timestamp) VALUES (?,?,?,?,?,?)",
        (user_id, chat_id, original, corrected, mistake_type, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_stats(chat_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if chat_id:
        c.execute("SELECT COUNT(*) FROM corrections WHERE chat_id=?", (chat_id,))
    else:
        c.execute("SELECT COUNT(*) FROM corrections")
    total = c.fetchone()[0]

    if chat_id:
        c.execute("""
            SELECT mistake_type, COUNT(*) as cnt FROM corrections
            WHERE chat_id=? GROUP BY mistake_type ORDER BY cnt DESC LIMIT 5
        """, (chat_id,))
    else:
        c.execute("""
            SELECT mistake_type, COUNT(*) as cnt FROM corrections
            GROUP BY mistake_type ORDER BY cnt DESC LIMIT 5
        """)
    common = c.fetchall()

    today = datetime.now().strftime("%Y-%m-%d")
    if chat_id:
        c.execute("SELECT COUNT(*) FROM corrections WHERE chat_id=? AND timestamp LIKE ?", (chat_id, f"{today}%"))
    else:
        c.execute("SELECT COUNT(*) FROM corrections WHERE timestamp LIKE ?", (f"{today}%",))
    today_count = c.fetchone()[0]

    conn.close()
    return {"total": total, "common": common, "today": today_count}

# ─── AI Grammar Check ──────────────────────────────────────────────────────────

GRAMMAR_PROMPT = """You are an expert English grammar assistant for a school environment.

Analyze the given message and respond ONLY in JSON format like this:
{{
  "has_errors": true or false,
  "is_english": true or false,
  "is_too_short": true or false,
  "corrected": "corrected version of the message",
  "mistake_type": "grammar / punctuation / structure / vocabulary / none",
  "tip": "brief explanation of the main mistake",
  "vocabulary_suggestion": "optional vocabulary improvement (or empty string)",
  "tone_suggestion": "optional tone/formality improvement for teachers (or empty string)"
}}

Rules:
- Set is_too_short=true if the message is only emojis, a single word, or fewer than 4 words
- Set is_english=false if the message is not in English
- Set has_errors=false if the message is grammatically correct
- Do NOT correct lists, bullet points, or non-sentence fragments
- Always use formal language appropriate for a school setting
- For vocabulary_suggestion: suggest formal alternatives (e.g., "students" instead of "kids")
- Respond ONLY with the JSON object, no extra text
"""

async def analyze_grammar(text: str, sensitivity: str = "normal") -> dict:
    try:
        prompt = GRAMMAR_PROMPT
        if sensitivity == "strict":
            prompt += "\n- Be strict: flag minor punctuation and style issues too."
        elif sensitivity == "relaxed":
            prompt += "\n- Be relaxed: only flag clear grammatical errors, ignore minor issues."

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Analyze this message:\n\n{text}"}
            ],
            max_tokens=500,
            temperature=0.2
        )

        import json
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    except Exception as e:
        logger.error(f"Grammar analysis error: {e}")
        return None

# ─── Command Handlers ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_known_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "I am your *English Grammar Assistant* 📝\n\n"
        "I monitor your group messages and will *privately* suggest grammar corrections "
        "whenever I detect a mistake — so no one else sees it!\n\n"
        "You are now registered. I will start sending you private suggestions. ✅\n\n"
        "Your writing will improve every day! 🚀",
        parse_mode="Markdown"
    )

async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("This command is for groups only.")
        return
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⚠️ Only group admins can use this command.")
        return
    save_group_settings(chat.id, enabled=True)
    await update.message.reply_text("✅ Grammar Assistant is now *enabled* for this group.", parse_mode="Markdown")

async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("This command is for groups only.")
        return
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⚠️ Only group admins can use this command.")
        return
    save_group_settings(chat.id, enabled=False)
    await update.message.reply_text("🔴 Grammar Assistant is now *disabled* for this group.", parse_mode="Markdown")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("This command is for groups only.")
        return
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⚠️ Only group admins can use this command.")
        return

    keyboard = [
        [
            InlineKeyboardButton("🟢 Relaxed", callback_data=f"sens_{chat.id}_relaxed"),
            InlineKeyboardButton("🟡 Normal", callback_data=f"sens_{chat.id}_normal"),
            InlineKeyboardButton("🔴 Strict", callback_data=f"sens_{chat.id}_strict"),
        ],
        [
            InlineKeyboardButton("✅ Explanations ON", callback_data=f"exp_{chat.id}_on"),
            InlineKeyboardButton("❌ Explanations OFF", callback_data=f"exp_{chat.id}_off"),
        ]
    ]
    settings = get_group_settings(chat.id)
    await update.message.reply_text(
        f"⚙️ *Group Settings*\n\n"
        f"Status: {'✅ Enabled' if settings['enabled'] else '🔴 Disabled'}\n"
        f"Sensitivity: {settings['sensitivity'].capitalize()}\n"
        f"Explanations: {'ON' if settings['show_explanations'] else 'OFF'}\n\n"
        "Adjust settings below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("sens_"):
        _, chat_id, level = data.split("_")
        save_group_settings(int(chat_id), sensitivity=level)
        await query.edit_message_text(f"✅ Sensitivity set to *{level.capitalize()}*.", parse_mode="Markdown")

    elif data.startswith("exp_"):
        _, chat_id, value = data.split("_")
        save_group_settings(int(chat_id), show_explanations=(value == "on"))
        await query.edit_message_text(f"✅ Explanations turned *{'ON' if value == 'on' else 'OFF'}*.", parse_mode="Markdown")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        stats = get_stats()
    else:
        stats = get_stats(chat.id)

    common_text = ""
    for mistake, count in stats["common"]:
        common_text += f"  • {mistake}: {count}\n"

    await update.message.reply_text(
        f"📊 *Grammar Bot Statistics*\n\n"
        f"Total corrections: {stats['total']}\n"
        f"Today's corrections: {stats['today']}\n\n"
        f"Most common mistakes:\n{common_text or '  No data yet'}",
        parse_mode="Markdown"
    )

# ─── Group Message Handler ─────────────────────────────────────────────────────

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ["group", "supergroup"]:
        return

    # Check group settings
    settings = get_group_settings(chat.id)
    if not settings["enabled"]:
        return

    text = message.text.strip()

    # Skip very short messages or commands
    if len(text.split()) < 4 or text.startswith("/"):
        return

    # Check if user is known, send onboarding if not
    if not is_known_user(user.id):
        bot_info = await context.bot.get_me()
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"👋 Hello {user.first_name}!\n\n"
                    "I am your *English Grammar Assistant* 📝\n\n"
                    "I noticed you sent a message in the group. I can help improve your English "
                    "by sending you *private grammar suggestions* — only you will see them!\n\n"
                    f"Please click the button below or start a chat with @{bot_info.username} "
                    "and send /start to activate private suggestions. ✅"
                ),
                parse_mode="Markdown"
            )
            add_known_user(user.id, user.username or user.first_name)
        except Exception:
            # Bot can't message user yet — they haven't started the bot
            pass
        return

    # Analyze grammar
    result = await analyze_grammar(text, settings["sensitivity"])
    if not result:
        return

    # Skip if not English, too short, or no errors
    if not result.get("is_english") or result.get("is_too_short") or not result.get("has_errors"):
        return

    corrected = result.get("corrected", "")
    tip = result.get("tip", "")
    vocab = result.get("vocabulary_suggestion", "")
    tone = result.get("tone_suggestion", "")
    mistake_type = result.get("mistake_type", "general")

    # Build private message
    private_msg = (
        f"✏️ *Grammar Suggestion*\n\n"
        f"*Original Message:*\n_{text}_\n\n"
        f"*Suggested Correction:*\n{corrected}\n"
    )

    if settings["show_explanations"] and tip:
        private_msg += f"\n💡 *Tip:* {tip}\n"

    if vocab:
        private_msg += f"\n📚 *Vocabulary:* {vocab}\n"

    if tone:
        private_msg += f"\n🎓 *Formal Writing:* {tone}\n"

    private_msg += "\n_Keep writing! Every correction helps you improve. 🌟_"

    # Send private message
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=private_msg,
            parse_mode="Markdown"
        )
        log_correction(user.id, chat.id, text, corrected, mistake_type)
        logger.info(f"Correction sent to user {user.id} in group {chat.id}")
    except Exception as e:
        logger.warning(f"Could not send private message to {user.id}: {e}")

# ─── Announce Command ─────────────────────────────────────────────────────────

async def announce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("This command is for groups only.")
        return

    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⚠️ Only group admins can use this command.")
        return

    bot_info = await context.bot.get_me()
    bot_username = bot_info.username

    announcement = (
        "👋 *Hello everyone!*\n\n"
        "I am your *English Grammar Assistant* 🎓\n\n"
        "I silently monitor messages in this group and will *privately* send you grammar "
        "suggestions whenever I spot a mistake — no one else in the group will see it!\n\n"
        "✅ *To activate private suggestions, please take 10 seconds to do this:*\n\n"
        f"1️⃣ Click here 👉 @{bot_username}\n"
        "2️⃣ Press the *Start* button\n"
        "3️⃣ That's it — I'll begin helping you right away!\n\n"
        "🔒 _Your corrections are completely private. Only you will see them._\n\n"
        "💡 _This bot is here to help, not to judge. Happy writing!_ ✍️"
    )

    await update.message.reply_text(announcement, parse_mode="Markdown")

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set!")
    if not os.environ.get("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY not set!")

    init_db()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("enable", enable_cmd))
    app.add_handler(CommandHandler("disable", disable_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("announce", announce_cmd))
    app.add_handler(CallbackQueryHandler(settings_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Starting with webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            webhook_url=webhook_url
        )
    else:
        logger.info("Starting with polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
