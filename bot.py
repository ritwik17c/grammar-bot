#!/usr/bin/env python3
"""
VKV Grammar Assistant Bot
- Monitors group messages
- Sends private grammar corrections
- Admin controls
- SQLite logging
- /report command
- Webhook support
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta
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

# ─── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS group_settings (
        chat_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1,
        sensitivity TEXT DEFAULT 'normal', show_explanations INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS known_users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER,
        original TEXT, corrected TEXT, mistake_type TEXT, timestamp TEXT)""")
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
    c.execute("INSERT OR IGNORE INTO known_users (user_id, username, first_seen) VALUES (?,?,?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_correction(user_id, chat_id, original, corrected, mistake_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO corrections (user_id, chat_id, original, corrected, mistake_type, timestamp) VALUES (?,?,?,?,?,?)",
              (user_id, chat_id, original, corrected, mistake_type, datetime.now().isoformat()))
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
        c.execute("SELECT mistake_type, COUNT(*) cnt FROM corrections WHERE chat_id=? GROUP BY mistake_type ORDER BY cnt DESC LIMIT 5", (chat_id,))
    else:
        c.execute("SELECT mistake_type, COUNT(*) cnt FROM corrections GROUP BY mistake_type ORDER BY cnt DESC LIMIT 5")
    common = c.fetchall()

    today = datetime.now().strftime("%Y-%m-%d")
    if chat_id:
        c.execute("SELECT COUNT(*) FROM corrections WHERE chat_id=? AND timestamp LIKE ?", (chat_id, f"{today}%"))
    else:
        c.execute("SELECT COUNT(*) FROM corrections WHERE timestamp LIKE ?", (f"{today}%",))
    today_count = c.fetchone()[0]

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if chat_id:
        c.execute("SELECT COUNT(*) FROM corrections WHERE chat_id=? AND timestamp >= ?", (chat_id, week_ago))
    else:
        c.execute("SELECT COUNT(*) FROM corrections WHERE timestamp >= ?", (week_ago,))
    week_count = c.fetchone()[0]

    if chat_id:
        c.execute("SELECT DATE(timestamp) day, COUNT(*) cnt FROM corrections WHERE chat_id=? AND timestamp >= ? GROUP BY day ORDER BY day DESC", (chat_id, week_ago))
    else:
        c.execute("SELECT DATE(timestamp) day, COUNT(*) cnt FROM corrections WHERE timestamp >= ? GROUP BY day ORDER BY day DESC", (week_ago,))
    daily = c.fetchall()

    if chat_id:
        c.execute("SELECT k.username, COUNT(*) cnt FROM corrections co LEFT JOIN known_users k ON co.user_id=k.user_id WHERE co.chat_id=? GROUP BY co.user_id ORDER BY cnt DESC LIMIT 5", (chat_id,))
    else:
        c.execute("SELECT k.username, COUNT(*) cnt FROM corrections co LEFT JOIN known_users k ON co.user_id=k.user_id GROUP BY co.user_id ORDER BY cnt DESC LIMIT 5")
    top_users = c.fetchall()

    conn.close()
    return {"total": total, "common": common, "today": today_count, "week": week_count, "daily": daily, "top_users": top_users}

# ─── AI Grammar Check ──────────────────────────────────────────────────────────

GRAMMAR_PROMPT = """You are an expert English grammar and punctuation assistant for a school environment.

Analyze the given message and respond ONLY in JSON format like this:
{
  "has_errors": true or false,
  "is_english": true or false,
  "is_too_short": true or false,
  "corrected": "corrected version of the message",
  "mistake_type": "grammar / punctuation / structure / vocabulary / none",
  "tip": "brief explanation of the main mistake",
  "vocabulary_suggestion": "optional vocabulary improvement (or empty string)",
  "tone_suggestion": "optional tone/formality improvement for teachers (or empty string)"
}

Rules:
- Set is_too_short=true if the message is only emojis, a single word, or fewer than 4 words
- Set is_english=false if the message is not in English
- Set has_errors=false ONLY if the message is perfectly correct in grammar AND punctuation
- Set has_errors=true for ANY of these punctuation issues:
  * Missing capital letter at the start of a sentence
  * Missing full stop, question mark, or exclamation mark at the end
  * Missing comma where required (e.g. after introductory phrases, before conjunctions)
  * Incorrect use of apostrophes (e.g. its vs it's, dont vs don't)
  * Missing or extra spaces around punctuation
  * Incorrect use of exclamation marks or question marks
- Do NOT correct lists, bullet points, or non-sentence fragments
- Always use formal language appropriate for a school setting
- For vocabulary_suggestion: suggest formal alternatives (e.g., "students" instead of "kids")
- Respond ONLY with the JSON object, no extra text"""

async def analyze_grammar(text, sensitivity="normal"):
    try:
        prompt = GRAMMAR_PROMPT
        if sensitivity == "strict":
            prompt += "\n- Be strict: flag minor punctuation and style issues too."
        elif sensitivity == "relaxed":
            prompt += "\n- Be relaxed: only flag clear grammatical errors, ignore minor issues."

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": prompt},
                      {"role": "user", "content": f"Analyze this message:\n\n{text}"}],
            max_tokens=500, temperature=0.2)

        import json
        raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Grammar analysis error: {e}")
        return None

# ─── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_known_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "I am your *English Grammar Assistant* 📝\n\n"
        "Here is what I can do for you:\n\n"
        "📌 *In the group:* I silently monitor messages and send you *private* grammar suggestions whenever I spot a mistake\n\n"
        "📌 *Right here privately:* Just send me any sentence or paragraph and I will instantly check it for grammar errors!\n\n"
        "You are now registered. ✅\n\n"
        "Try it now — send me any English sentence! 🚀",
        parse_mode="Markdown")

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
        [InlineKeyboardButton("🟢 Relaxed", callback_data=f"sens_{chat.id}_relaxed"),
         InlineKeyboardButton("🟡 Normal", callback_data=f"sens_{chat.id}_normal"),
         InlineKeyboardButton("🔴 Strict", callback_data=f"sens_{chat.id}_strict")],
        [InlineKeyboardButton("✅ Explanations ON", callback_data=f"exp_{chat.id}_on"),
         InlineKeyboardButton("❌ Explanations OFF", callback_data=f"exp_{chat.id}_off")]
    ]
    settings = get_group_settings(chat.id)
    await update.message.reply_text(
        f"⚙️ *Group Settings*\n\n"
        f"Status: {'✅ Enabled' if settings['enabled'] else '🔴 Disabled'}\n"
        f"Sensitivity: {settings['sensitivity'].capitalize()}\n"
        f"Explanations: {'ON' if settings['show_explanations'] else 'OFF'}\n\nAdjust settings below:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

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
    stats = get_stats(chat.id if chat.type != "private" else None)
    common_text = "".join(f"  • {m}: {c}\n" for m, c in stats["common"]) or "  No data yet"
    await update.message.reply_text(
        f"📊 *Grammar Bot Statistics*\n\n"
        f"Total corrections: {stats['total']}\n"
        f"Today: {stats['today']}\n\n"
        f"Most common mistakes:\n{common_text}", parse_mode="Markdown")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ["group", "supergroup"]:
        member = await chat.get_member(user.id)
        if member.status not in ["administrator", "creator"]:
            await update.message.reply_text("⚠️ Only group admins can view the report.")
            return
        stats = get_stats(chat.id)
    else:
        stats = get_stats()

    daily_text = ""
    for day, count in stats["daily"]:
        bar = "█" * min(count, 10)
        daily_text += f"  {day}: {bar} {count}\n"

    top_users_text = ""
    for i, (username, count) in enumerate(stats["top_users"], 1):
        name = f"@{username}" if username else "Unknown"
        top_users_text += f"  {i}. {name}: {count} corrections\n"

    common_text = "".join(f"  • {m.capitalize()}: {c}\n" for m, c in stats["common"])

    report = (
        "📋 *Grammar Assistant — Full Report*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Today:* {stats['today']} corrections\n"
        f"📆 *This week:* {stats['week']} corrections\n"
        f"🗂 *All time:* {stats['total']} corrections\n\n"
        f"📊 *Daily Breakdown (Last 7 Days):*\n{daily_text or '  No data yet'}\n"
        f"❌ *Most Common Mistakes:*\n{common_text or '  No data yet'}\n"
        f"👤 *Most Corrected Users:*\n{top_users_text or '  No data yet'}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"
    )
    await update.message.reply_text(report, parse_mode="Markdown")

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
    deep_link = f"https://t.me/{bot_info.username}?start=hello"
    await update.message.reply_text(
        "👋 *Hello everyone!*\n\n"
        "I am your *English Grammar Assistant* 🎓\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🌟 *What I can do for you:*\n\n"
        "📌 *In this group:*\n"
        "I silently read your messages and if I find any grammar or punctuation mistakes, "
        "I will send you a *private correction* — only you will see it, nobody else in the group!\n\n"
        "📌 *In private chat:*\n"
        "You can send me any sentence or paragraph directly and I will instantly check it "
        "for grammar, punctuation, vocabulary, and writing style!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *How to get started — 3 simple steps:*\n\n"
        f"1️⃣ Click this link 👉 {deep_link}\n"
        "2️⃣ A chat with me will open — press the *START* button\n"
        "3️⃣ That's it! I will now help you both here in the group and in private chat\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 *Privacy:* Your corrections are completely private. No one else will see them.\n\n"
        "💡 _I am here to help you improve, not to judge. Happy writing!_ ✍️",
        parse_mode="Markdown")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    chat = update.effective_chat
    user = update.effective_user
    text = message.text.strip()

    if text.startswith("/"):
        return

    # ── Private Chat Mode ──────────────────────────────────────────────────────
    if chat.type == "private":
        if len(text.split()) < 4:
            await message.reply_text(
                "Please send a complete sentence or paragraph and I'll check it for grammar! ✏️"
            )
            return

        await message.reply_chat_action("typing")
        result = await analyze_grammar(text, "normal")
        if not result:
            await message.reply_text("⚠️ Could not analyze the text. Please try again.")
            return

        if not result.get("is_english"):
            await message.reply_text("ℹ️ I can only check *English* text. Please send an English message.", parse_mode="Markdown")
            return

        if result.get("is_too_short"):
            await message.reply_text("Please send a longer sentence so I can check it properly! ✏️")
            return

        if not result.get("has_errors"):
            await message.reply_text(
                "✅ *No errors found!*\n\nYour message is grammatically correct. Well done! 🌟",
                parse_mode="Markdown"
            )
            return

        corrected = result.get("corrected", "")
        tip = result.get("tip", "")
        vocab = result.get("vocabulary_suggestion", "")
        tone = result.get("tone_suggestion", "")
        mistake_type = result.get("mistake_type", "general")

        reply = (
            f"✏️ *Grammar Suggestion*\n\n"
            f"*Original Message:*\n_{text}_\n\n"
            f"*Suggested Correction:*\n{corrected}\n"
        )
        if tip:
            reply += f"\n💡 *Tip:* {tip}\n"
        if vocab:
            reply += f"\n📚 *Vocabulary:* {vocab}\n"
        if tone:
            reply += f"\n🎓 *Formal Writing:* {tone}\n"
        reply += "\n_Keep writing! Every correction helps you improve. 🌟_"

        await message.reply_text(reply, parse_mode="Markdown")
        log_correction(user.id, chat.id, text, corrected, mistake_type)
        return

    # ── Group Chat Mode ────────────────────────────────────────────────────────
    if chat.type not in ["group", "supergroup"]:
        return

    settings = get_group_settings(chat.id)
    if not settings["enabled"]:
        return

    if len(text.split()) < 4:
        return

    if not is_known_user(user.id):
        bot_info = await context.bot.get_me()
        deep_link = f"https://t.me/{bot_info.username}?start=hello"
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(f"👋 Hello {user.first_name}!\n\n"
                      "I am your *English Grammar Assistant* 📝\n\n"
                      "I can help improve your English by sending you *private grammar suggestions*.\n\n"
                      f"Please click here to activate: {deep_link}"),
                parse_mode="Markdown")
            add_known_user(user.id, user.username or user.first_name)
        except Exception:
            pass
        return

    result = await analyze_grammar(text, settings["sensitivity"])
    if not result:
        return
    if not result.get("is_english") or result.get("is_too_short") or not result.get("has_errors"):
        return

    corrected = result.get("corrected", "")
    tip = result.get("tip", "")
    vocab = result.get("vocabulary_suggestion", "")
    tone = result.get("tone_suggestion", "")
    mistake_type = result.get("mistake_type", "general")

    private_msg = (f"✏️ *Grammar Suggestion*\n\n"
                   f"*Original Message:*\n_{text}_\n\n"
                   f"*Suggested Correction:*\n{corrected}\n")
    if settings["show_explanations"] and tip:
        private_msg += f"\n💡 *Tip:* {tip}\n"
    if vocab:
        private_msg += f"\n📚 *Vocabulary:* {vocab}\n"
    if tone:
        private_msg += f"\n🎓 *Formal Writing:* {tone}\n"
    private_msg += "\n_Keep writing! Every correction helps you improve. 🌟_"

    try:
        await context.bot.send_message(chat_id=user.id, text=private_msg, parse_mode="Markdown")
        log_correction(user.id, chat.id, text, corrected, mistake_type)
        logger.info(f"Correction sent to user {user.id} in group {chat.id}")
    except Exception as e:
        logger.warning(f"Could not send private message to {user.id}: {e}")

# ─── New Member Welcome ───────────────────────────────────────────────────────

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not update.message or not update.message.new_chat_members:
        return
    bot_info = await context.bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=hello"
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await update.message.reply_text(
            f"👋 *Welcome to the group, {member.first_name}!*\n\n"
            f"We have an *English Grammar Assistant* bot here to help you write better English 🎓\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌟 *What the bot does for you:*\n\n"
            f"📌 *In this group:*\n"
            f"It silently reads messages in the group. If it finds a grammar or punctuation mistake "
            f"in your message, it sends you a *private correction* — only you will see it!\n\n"
            f"📌 *In private chat:*\n"
            f"You can also send any sentence or paragraph directly to the bot and it will "
            f"instantly check your grammar, punctuation, vocabulary, and writing style!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Getting started is easy — just 3 steps:*\n\n"
            f"1️⃣ Click this link 👉 {deep_link}\n"
            f"2️⃣ A private chat with the bot will open — press the *START* button\n"
            f"3️⃣ Done! The bot will now help you in the group and in private chat\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔒 *Privacy:* Your corrections are completely private. Nobody else in the group will see them.\n\n"
            f"💡 _The bot is here to help you improve your English, not to embarrass you. Happy writing!_ ✍️",
            parse_mode="Markdown"
        )

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
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("announce", announce_cmd))
    app.add_handler(CallbackQueryHandler(settings_callback))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Starting with webhook: {webhook_url}")
        app.run_webhook(listen="0.0.0.0", port=int(os.environ.get("PORT", 8080)), webhook_url=webhook_url)
    else:
        logger.info("Starting with polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

# NOTE: The above file is already complete. The dashboard API is served by dashboard_server.py
