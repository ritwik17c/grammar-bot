#!/usr/bin/env python3
"""
Grammar Correction Telegram Bot powered by Groq AI (Llama 3)
"""

import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Groq client
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are a grammar correction assistant. When given text, you:
1. Identify and fix grammatical errors
2. Briefly explain the main corrections made
3. Keep the original meaning intact
4. Be encouraging and friendly

Format your response as:
✅ Corrected: [corrected text]

📝 Changes made:
[bullet points of corrections, if any]

If the text has no errors, respond with:
✅ No errors found! Your text is grammatically correct.

Keep responses concise and clear."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message on /start."""
    await update.message.reply_text(
        "👋 Hello! I'm your Grammar Correction Bot powered by Groq AI.\n\n"
        "Simply send me any text and I'll check it for grammatical errors and suggest corrections!\n\n"
        "Commands:\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/check <text> - Check specific text\n\n"
        "Or just send me any message directly! 📝"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message."""
    await update.message.reply_text(
        "📖 How to use this bot:\n\n"
        "1. Simply type or paste any text and send it to me\n"
        "2. I'll analyze it for grammar errors\n"
        "3. You'll get the corrected version with an explanation\n\n"
        "Examples:\n"
        "• 'I goes to school yesterday'\n"
        "• 'She dont like apples'\n"
        "• 'Their is a cat in my house'\n\n"
        "I handle everything from simple typos to complex grammar rules! 🎯"
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check command with inline text."""
    if not context.args:
        await update.message.reply_text(
            "Please provide text after /check\nExample: /check I goes to school"
        )
        return
    text = " ".join(context.args)
    await process_grammar(update, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all regular text messages."""
    text = update.message.text
    if not text or len(text.strip()) == 0:
        return
    await process_grammar(update, text)


async def process_grammar(update: Update, text: str) -> None:
    """Process text through Groq for grammar correction."""
    await update.message.reply_chat_action("typing")

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Please check the grammar of this text:\n\n{text}"}
            ],
            max_tokens=1000,
            temperature=0.3
        )

        corrected = response.choices[0].message.content
        await update.message.reply_text(corrected)

    except Exception as e:
        logger.error(f"Error processing grammar: {e}")
        await update.message.reply_text(
            "⚠️ Sorry, I encountered an error analyzing your text. Please try again."
        )


def main() -> None:
    """Start the bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY environment variable not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Grammar Bot (Groq) is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
