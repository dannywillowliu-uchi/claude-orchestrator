#!/usr/bin/env python3
"""
Run the Claude Code Telegram bot.

Usage:
    python -m claude_orchestrator.run_telegram_bot

Environment variables required:
    TELEGRAM_BOT_TOKEN - Your Telegram bot token from BotFather
    TELEGRAM_CHAT_ID - Your chat ID (optional, will be set on /start)
"""

import os
import asyncio
from dotenv import load_dotenv

from .telegram_bot import TelegramBot


async def main():
	# Load environment variables
	load_dotenv()

	token = os.getenv("TELEGRAM_BOT_TOKEN")
	chat_id = os.getenv("TELEGRAM_CHAT_ID")

	if not token:
		print("Error: TELEGRAM_BOT_TOKEN not set")
		print("Set it in .env file or as environment variable")
		return

	print("Starting Claude Code Telegram Bot...")
	print(f"Chat ID: {chat_id or 'Not set (use /start to set)'}")

	bot = TelegramBot(token=token, chat_id=chat_id)

	try:
		await bot.start()
		print("Bot started. Press Ctrl+C to stop.")

		# Keep running
		while True:
			await asyncio.sleep(1)

	except KeyboardInterrupt:
		print("\nStopping bot...")
	finally:
		await bot.stop()
		print("Bot stopped.")


if __name__ == "__main__":
	asyncio.run(main())
