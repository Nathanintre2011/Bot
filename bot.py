import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", ".")

intents = discord.Intents.default()
intents.message_content = True  # required so the bot can read command content

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=commands.DefaultHelpCommand())

COGS = [
    "cogs.general",
    "cogs.syntax",
    "cogs.obfuscate",
    "cogs.minify",
]


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Prefix: {PREFIX}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument: {error}")
        return
    # Don't expose raw tracebacks to the user
    print(f"Unhandled error in command {ctx.command}: {error}")
    await ctx.send("❌ Something went wrong while running this command.")


async def main():
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token."
        )
    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
