"""
Check Lua/Luau syntax by calling an external binary (luau-analyze or luac)
that must be installed on the machine the bot runs on. We only PARSE
(never execute) the user's code, so this is safe.
"""

import asyncio
import os
import re
import shutil
import tempfile

# Common error patterns from luac/luau: "path:LINE: message" or "path(LINE,COL): message"
_ERR_PATTERNS = [
    re.compile(r':(\d+):\s*(.+)'),
    re.compile(r'\((\d+),\d+\):\s*(.+)'),
]


def parse_lua_error(output: str):
    """Parse a compiler's error output into (line:int|None, message:str)."""
    output = output.strip()
    for pattern in _ERR_PATTERNS:
        m = pattern.search(output)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return None, output


def find_checker():
    """Find an available checker binary. Returns (name, path) or None."""
    for name in ("luau-analyze", "luac", "luac5.1", "luac5.3", "lua5.1", "lua"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


async def check_lua_syntax(code: str) -> dict:
    """Returns a dict:
    {"ok": True}
    {"ok": False, "line": int|None, "message": str}
    {"ok": None, "message": str}   -> no checker available on the server
    """
    checker = find_checker()
    if checker is None:
        return {
            "ok": None,
            "message": (
                "No Lua/Luau checker is installed on the bot's server "
                "(install one of: `luau-analyze`, or `luac`/`lua5.1`)."
            ),
        }

    name, path = checker

    fd, tmp_path = tempfile.mkstemp(suffix=".lua")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)

        if name == "luau-analyze":
            args = [path, tmp_path]
        elif name.startswith("luac"):
            args = [path, "-p", tmp_path]  # -p = parse only, don't produce an output file
        else:
            # 'lua'/'lua5.1' interpreter: use loadfile via -e so it only
            # parses (loadfile doesn't execute the chunk)
            args = [path, "-e",
                    f'local f,err=loadfile("{tmp_path}") '
                    f'if not f then io.stderr:write(err) os.exit(1) end']

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout + stderr).decode("utf-8", errors="replace")

        if proc.returncode == 0 and "error" not in output.lower():
            return {"ok": True}

        line, message = parse_lua_error(output)
        return {"ok": False, "line": line, "message": message or "Unknown error"}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
