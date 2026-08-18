"""
Helper for pulling Lua/Luau code out of a Discord command invocation.
Priority: attached file > URL inside the text > raw text / code block.
"""

import aiohttp

MAX_SIZE = 300_000  # ~300 KB, plenty for a typical Lua script


async def get_code_input(ctx, arg_text: str | None) -> str:
    """Returns the source code (str). Raises ValueError if there's no
    valid input or fetching it failed."""

    # 1. Attachment
    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        if attachment.size > MAX_SIZE:
            raise ValueError(f"File is too large (max {MAX_SIZE // 1000} KB).")
        data = await attachment.read()
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("File can't be read as text (make sure it's a plain .lua/.txt file).")

    text = (arg_text or "").strip()
    if not text:
        raise ValueError("No file, URL, or text was provided. Attach a file, give a URL, or paste code directly.")

    # 2. URL
    if text.startswith("http://") or text.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(text, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Failed to fetch URL (HTTP {resp.status}).")
                    content = await resp.text(errors='replace')
        except aiohttp.ClientError as e:
            raise ValueError(f"Failed to fetch URL: {e}")
        if len(content) > MAX_SIZE:
            raise ValueError(f"Content from the URL is too large (max {MAX_SIZE // 1000} KB).")
        return content

    # 3. Raw text, optionally wrapped in a ```code block```
    if text.startswith("```") and text.endswith("```") and len(text) >= 6:
        inner = text[3:-3]
        lines = inner.split("\n")
        if lines and lines[0].strip() and lines[0].strip().isalpha():
            # first line is likely a language tag, e.g. ```lua
            lines = lines[1:]
        return "\n".join(lines)

    return text
              
