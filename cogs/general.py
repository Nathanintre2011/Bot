import io

import aiohttp
import discord
from discord.ext import commands

MAX_FETCH_SIZE = 300_000  # ~300 KB


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        """Check the bot's latency to Discord."""
        latency_ms = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: **{latency_ms}ms**",
            color=discord.Color.green() if latency_ms < 200 else discord.Color.orange(),
        )
        await ctx.send(embed=embed)

    @commands.command(name="get")
    async def get(self, ctx: commands.Context, url: str = None):
        """Fetch the text content of a URL. Example: .get https://example.com/script.lua"""
        if not url:
            await ctx.send("❌ Please provide a URL. Example: `.get https://example.com/file.lua`")
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            await ctx.send("❌ URL must start with `http://` or `https://`.")
            return

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=10)
                    async with session.get(url, timeout=timeout) as resp:
                        if resp.status != 200:
                            await ctx.send(f"❌ Failed to fetch URL (HTTP {resp.status}).")
                            return
                        content = await resp.text(errors="replace")
            except aiohttp.ClientError as e:
                await ctx.send(f"❌ Failed to fetch URL: {e}")
                return
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")
                return

        if not content:
            await ctx.send("⚠️ The URL was reached but the content is empty.")
            return

        if len(content) > MAX_FETCH_SIZE:
            content = content[:MAX_FETCH_SIZE]
            note = f"\n\n⚠️ Truncated, the original content is larger than {MAX_FETCH_SIZE // 1000} KB."
        else:
            note = ""

        if len(content) <= 1900:
            await ctx.send(f"```\n{content}\n```{note}")
        else:
            buf = io.BytesIO(content.encode("utf-8"))
            filename = url.rsplit("/", 1)[-1] or "fetched.txt"
            if "." not in filename:
                filename += ".txt"
            await ctx.send(f"Content is too long to send inline, here's the file:{note}",
                            file=discord.File(buf, filename=filename))


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
      
