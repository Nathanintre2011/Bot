import discord
from discord.ext import commands
from utils.input_source import get_input_code
from utils.minifier_lua import minify
import io

class MinifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="minify")
    async def minify_cmd(self, ctx, *, arg: str = None):
        """
        Minify Lua/Luau code (strips comments & whitespace without renaming variables).
        Usage: 
          .minify <code / raw url>
          .minify (with attached .lua file)
        """
        # Fetch code from attachment, URL, or text message
        code, err = await get_input_code(ctx, arg)
        if err:
            await ctx.send(f"❌ **Error:** {err}")
            return

        if not code.strip():
            await ctx.send("❌ **Error:** Script content is empty!")
            return

        # Perform minification (keep_comments=False, rename=False)
        try:
            minified_code = minify(
                code,
                keep_comments=False,
                rename=False
            )
            
            # Add credit header
            header = "-- [[ Minified by MinifierLuaBot ]]\n"
            final_code = header + minified_code

            # Calculate byte compression ratio
            orig_size = len(code.encode('utf-8'))
            new_size = len(final_code.encode('utf-8'))
            reduction = ((orig_size - new_size) / orig_size * 100) if orig_size > 0 else 0

            # Output as embed code block if short enough, otherwise attach .lua file
            if len(final_code) <= 1900:
                embed = discord.Embed(
                    title="⚡ Lua Script Minified",
                    color=discord.Color.blue()
                )
                embed.description = f"```lua\n{final_code}\n```"
                embed.add_field(name="Original Size", value=f"`{orig_size}` bytes", inline=True)
                embed.add_field(name="Minified Size", value=f"`{new_size}` bytes", inline=True)
                embed.add_field(name="Saved", value=f"`{reduction:.1f}%`", inline=True)
                await ctx.send(embed=embed)
            else:
                file_data = io.BytesIO(final_code.encode('utf-8'))
                file = discord.File(file_data, filename="minified.lua")
                
                embed = discord.Embed(
                    title="⚡ Lua Script Minified",
                    description=f"File exceeds Discord message limit. Minified script attached below!\n\n"
                                f"• **Original:** `{orig_size}` bytes\n"
                                f"• **Minified:** `{new_size}` bytes\n"
                                f"• **Saved:** `{reduction:.1f}%`",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed, file=file)

        except Exception as e:
            await ctx.send(f"❌ **Failed to minify script:** `{str(e)}`")

async def setup(bot):
    await bot.add_cog(MinifyCog(bot))
