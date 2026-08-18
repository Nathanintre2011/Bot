import discord
from discord.ext import commands

from utils.input_source import get_code_input
from utils.lua_syntax import check_lua_syntax


class Syntax(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="checksyntax")
    async def checksyntax(self, ctx: commands.Context, *, arg: str = None):
        """Check the syntax of a Lua/Luau script. Attach a file, give a URL, or paste code."""
        async with ctx.typing():
            try:
                code = await get_code_input(ctx, arg)
            except ValueError as e:
                await ctx.send(f"❌ {e}")
                return

            result = await check_lua_syntax(code)

        if result["ok"] is None:
            await ctx.send(f"⚠️ {result['message']}")
            return

        if result["ok"]:
            embed = discord.Embed(
                title="✅ Syntax Valid",
                description="No errors found.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(title="❌ Syntax Check", color=discord.Color.red())
        embed.add_field(name="Type", value="Error", inline=False)
        embed.add_field(name="Why Error?", value=f"```{result['message'][:1000]}```", inline=False)
        embed.add_field(name="Line", value=str(result["line"]) if result["line"] else "?", inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Syntax(bot))
              
