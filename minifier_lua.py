#!/usr/bin/env python3
"""
MinifierLuaBot engine - lightweight minifier + obfuscator for Lua / Luau code.

CLI usage:
    python minifier_lua.py input.lua
        -> result written to output.lua & copied to clipboard

    python minifier_lua.py input.lua -o result.lua
    python minifier_lua.py input.lua --no-rename       # don't randomize local variable names
    python minifier_lua.py input.lua --no-clipboard    # don't copy to clipboard
    python minifier_lua.py input.lua --keep-comments   # only clean up whitespace
    python minifier_lua.py input.lua --stdout          # also print to terminal
    cat input.lua | python minifier_lua.py -           # read from stdin

Features:
    - Strip unnecessary comments & whitespace
    - Safe against strings, long strings [[...]]/[==[...]==], ambiguous operators
    - Randomize LOCAL variable names (including function params & loop vars)
      into short names (a, b, c, ...), based on simple scope analysis.
      Global variables & table fields (after . or :) are NOT touched.
    - Auto save to output.lua + copy to clipboard
"""

import argparse
import re
import sys

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

TOKEN_SPEC = [
    ('LONGSTRING', r'\[(?P<ls_eq>=*)\[.*?\](?P=ls_eq)\]'),
    ('LONGCOMMENT', r'--\[(?P<lc_eq>=*)\[.*?\](?P=lc_eq)\]'),
    ('LINECOMMENT', r'--[^\n]*'),
    ('STRING_D', r'"(?:\\.|[^"\\\n])*"'),
    ('STRING_S', r"'(?:\\.|[^'\\\n])*'"),
    ('NEWLINE', r'\n'),
    ('WHITESPACE', r'[ \t\r]+'),
    ('NAME', r'[A-Za-z_][A-Za-z0-9_]*'),
    ('NUMBER', r'0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?'),
    ('SYMBOL', r'\.\.\.|\.\.|::|<=|>=|==|~=|//|[-+*/%^#<>=(){}\[\];:,.]'),
    ('OTHER', r'.'),
]

MASTER_RE = re.compile(
    '|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC),
    re.DOTALL,
)

TRIVIAL_KINDS = {'WHITESPACE', 'NEWLINE', 'LINECOMMENT', 'LONGCOMMENT'}

KEYWORDS = {
    'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for',
    'function', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat',
    'return', 'then', 'true', 'until', 'while',
    # Luau contextual keywords, safe to treat as reserved words too
    'continue', 'type', 'export',
}


class Token:
    __slots__ = ('kind', 'text')

    def __init__(self, kind, text):
        self.kind = kind
        self.text = text


def tokenize(src: str):
    tokens = []
    pos = 0
    length = len(src)
    while pos < length:
        m = MASTER_RE.match(src, pos)
        if not m:
            pos += 1
            continue
        tokens.append(Token(m.lastgroup, m.group()))
        pos = m.end()
    return tokens


# ---------------------------------------------------------------------------
# Rename local variables (scope-aware, best-effort)
# ---------------------------------------------------------------------------

def _gen_name_factory(min_len=3, max_len=6):
    import random
    letters = 'abcdefghijklmnopqrstuvwxyz'
    alnum = letters + '0123456789'
    used = set()

    def next_name():
        while True:
            length = random.randint(min_len, max_len)
            s = random.choice(letters) + ''.join(random.choice(alnum) for _ in range(length - 1))
            if s in KEYWORDS or s in used:
                continue
            used.add(s)
            return s
    return next_name


def _prev_meaningful(tokens, i):
    j = i - 1
    while j >= 0 and tokens[j].kind in TRIVIAL_KINDS:
        j -= 1
    return tokens[j] if j >= 0 else None


def _next_meaningful_idx(tokens, i):
    j = i + 1
    while j < len(tokens) and tokens[j].kind in TRIVIAL_KINDS:
        j += 1
    return j if j < len(tokens) else None


def rename_locals(tokens, min_len=3, max_len=6):
    """In-place mutation: replace tokens[i].text for NAMEs that are
    local variables, parameters, or loop variables, with a short random name.
    Table fields / methods (after . or :) and table literal keys are left untouched.
    """
    gen_name = _gen_name_factory(min_len=min_len, max_len=max_len)

    # stack of (kind, {orig_name: mangled_name})
    scope_stack = [('global', {})]
    bracket_stack = []  # holds: '(' '{' '['

    def declare(name):
        mangled = gen_name()
        scope_stack[-1][1][name] = mangled
        return mangled

    def lookup(name):
        for kind, mapping in reversed(scope_stack):
            if name in mapping:
                return mapping[name]
        return None

    n = len(tokens)
    i = 0

    mode = None            # None | 'local_names' | 'local_rhs' | 'for_names'
    pending_names = []
    rhs_depth = 0

    # indices of NAME tokens pending declaration, so they can be renamed
    # once the mangled name is generated on activation
    pending_name_tokens = []
    pending_for_tokens = []
    pending_for_names_list = []

    def activate_local_pending():
        for tok in pending_name_tokens:
            mangled = declare(tok.text)
            tok.text = mangled
        pending_name_tokens.clear()

    while i < n:
        tok = tokens[i]

        if tok.kind != 'NAME' and tok.kind != 'SYMBOL':
            # still need to track newline to end local_rhs
            if mode == 'local_rhs' and tok.kind == 'NEWLINE' and rhs_depth == 0:
                activate_local_pending()
                mode = None
            i += 1
            continue

        if tok.kind == 'SYMBOL':
            if tok.text in ('(', '{', '['):
                bracket_stack.append(tok.text)
            elif tok.text in (')', '}', ']'):
                if bracket_stack:
                    bracket_stack.pop()

            if mode == 'local_names' and tok.text == '=':
                mode = 'local_rhs'
                rhs_depth = 0
            elif mode == 'local_rhs':
                if tok.text in ('(', '{', '['):
                    rhs_depth += 1
                elif tok.text in (')', '}', ']'):
                    rhs_depth -= 1
                elif tok.text == ';' and rhs_depth <= 0:
                    activate_local_pending()
                    mode = None
            elif mode == 'for_names' and tok.text == '=':
                mode = None  # numeric for, wait for 'do' to activate
            i += 1
            continue

        # --- tok.kind == 'NAME' from here on ---
        text = tok.text

        if text in KEYWORDS:
            if text == 'local':
                mode = 'local_names'
                pending_name_tokens = []
            elif text == 'for':
                mode = 'for_names'
                pending_for_tokens = []
            elif text == 'in':
                if mode == 'for_names':
                    mode = None  # generic for, wait for 'do'
            elif text == 'function':
                prev = _prev_meaningful(tokens, i)
                is_local_decl = prev is not None and prev.text == 'local' and prev.kind == 'NAME'
                nxt_idx = _next_meaningful_idx(tokens, i)
                nxt = tokens[nxt_idx] if nxt_idx is not None else None
                func_name_end_idx = i

                if nxt is not None and nxt.kind == 'NAME' and nxt.text not in KEYWORDS:
                    func_name_end_idx = nxt_idx
                    if is_local_decl:
                        mangled = declare(nxt.text)
                        nxt.text = mangled
                    else:
                        found = lookup(nxt.text)
                        if found:
                            nxt.text = found
                    # skip forward past any .field / :method chain
                    j = nxt_idx
                    while True:
                        j2 = _next_meaningful_idx(tokens, j)
                        if j2 is None:
                            break
                        sep = tokens[j2]
                        if sep.kind == 'SYMBOL' and sep.text in ('.', ':'):
                            name_idx = _next_meaningful_idx(tokens, j2)
                            if name_idx is None or tokens[name_idx].kind != 'NAME':
                                break
                            j = name_idx
                            func_name_end_idx = j
                            continue
                        break

                # push scope baru utk parameter + body
                scope_stack.append(('function', {}))
                if mode == 'local_names':
                    activate_local_pending()
                    mode = None

                # find the opening '(' of the parameter list, then declare
                # every NAME directly preceded by '(' or ',' at depth 0
                paren_idx = _next_meaningful_idx(tokens, func_name_end_idx)
                k = paren_idx
                if k is not None and tokens[k].kind == 'SYMBOL' and tokens[k].text == '(':
                    depth = 0
                    m = k
                    while m < n:
                        mt = tokens[m]
                        if mt.kind == 'SYMBOL':
                            if mt.text == '(':
                                depth += 1
                            elif mt.text == ')':
                                depth -= 1
                                if depth == 0:
                                    break
                        elif mt.kind == 'NAME' and mt.text not in KEYWORDS and depth == 1:
                            pv = _prev_meaningful(tokens, m)
                            if pv is not None and pv.kind == 'SYMBOL' and pv.text in ('(', ','):
                                mangled = declare(mt.text)
                                mt.text = mangled
                        m += 1
                    i = k
            elif text == 'do':
                scope_stack.append(('do', {}))
                if pending_for_tokens:
                    for ftok in pending_for_tokens:
                        mangled = declare(ftok.text)
                        ftok.text = mangled
                    pending_for_tokens = []
                mode = None
            elif text == 'then':
                scope_stack.append(('if', {}))
            elif text == 'elseif':
                if len(scope_stack) > 1 and scope_stack[-1][0] == 'if':
                    scope_stack.pop()
            elif text == 'else':
                if len(scope_stack) > 1 and scope_stack[-1][0] == 'if':
                    scope_stack.pop()
                scope_stack.append(('if', {}))
            elif text == 'repeat':
                scope_stack.append(('repeat', {}))
            elif text == 'until':
                if len(scope_stack) > 1 and scope_stack[-1][0] == 'repeat':
                    scope_stack.pop()
            elif text == 'end':
                if len(scope_stack) > 1:
                    scope_stack.pop()
            i += 1
            continue

        # --- plain NAME (not a keyword) ---
        prev = _prev_meaningful(tokens, i)
        preceded_by_dot = prev is not None and prev.kind == 'SYMBOL' and prev.text in ('.', ':')

        if preceded_by_dot:
            i += 1
            continue

        if mode == 'local_names':
            pending_name_tokens.append(tok)
            i += 1
            continue

        if mode == 'for_names':
            pending_for_tokens.append(tok)
            i += 1
            continue

        # table-constructor key: NAME followed by a single '=', directly
        # inside '{' ... '}'
        nxt_idx = _next_meaningful_idx(tokens, i)
        nxt = tokens[nxt_idx] if nxt_idx is not None else None
        if (nxt is not None and nxt.kind == 'SYMBOL' and nxt.text == '='
                and bracket_stack and bracket_stack[-1] == '{'):
            i += 1
            continue

        # function param: NAME preceded by '(' or ',' -> only treated as a
        # param declaration if we just pushed a 'function' scope and are
        # still directly inside that function's '('. For simplicity &
        # safety, params are already handled via the dedicated block above
        # that fires right after seeing 'function' and its opening '('.

        found = lookup(text)
        if found:
            tok.text = found
        i += 1

    return tokens


def _mark_function_params(tokens):
    """Extra pass placeholder: declaring function parameters into the
    freshly-pushed 'function' scope is handled directly inside
    rename_locals for simplicity & correctness (kept for reference).
    """
    return tokens



# ---------------------------------------------------------------------------
# Minify (join tokens into compact code)
# ---------------------------------------------------------------------------

def _needs_space(prev_kind, prev_text, cur_kind, cur_text):
    if prev_kind in ('NAME', 'NUMBER') and cur_kind in ('NAME', 'NUMBER'):
        return True

    risky_symbols = {'-', '.', ':', '='}
    if prev_kind == 'SYMBOL' and cur_kind == 'SYMBOL':
        if prev_text[-1:] in risky_symbols and cur_text[:1] in risky_symbols:
            return True
        if prev_text.endswith('-') and cur_text.startswith('-'):
            return True

    if prev_kind == 'NUMBER' and cur_kind == 'SYMBOL' and cur_text.startswith('.'):
        return True
    if prev_kind == 'SYMBOL' and prev_text.endswith('.') and cur_kind == 'NUMBER':
        return True

    return False


def minify(src: str, keep_comments: bool = False, rename: bool = True,
           min_name_len: int = 3, max_name_len: int = 6) -> str:
    tokens = tokenize(src)

    if rename:
        rename_locals(tokens, min_len=min_name_len, max_len=max_name_len)

    kept = []
    for tok in tokens:
        if tok.kind in ('WHITESPACE', 'NEWLINE'):
            continue
        if tok.kind in ('LINECOMMENT', 'LONGCOMMENT'):
            if keep_comments:
                kept.append(tok)
            continue
        kept.append(tok)

    parts = []
    prev = None
    for tok in kept:
        if prev is not None and _needs_space(prev.kind, prev.text, tok.kind, tok.text):
            parts.append(' ')
        parts.append(tok.text)
        prev = tok

    return ''.join(parts)


# ---------------------------------------------------------------------------
# Clipboard helper
# ---------------------------------------------------------------------------

def copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except ImportError:
        print("Note: the 'pyperclip' module is not installed. Install it with:\n"
              "    pip install pyperclip\n"
              "The result was still saved to a file, just not copied to the clipboard.",
              file=sys.stderr)
        return False
    except Exception as e:
        print(f"Note: failed to copy to clipboard ({e}). "
              "The result was still saved to a file.", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='MinifierLuaBot engine - lightweight Lua/Luau minifier & obfuscator')
    parser.add_argument('input', help="Input .lua/.luau file, or '-' for stdin")
    parser.add_argument('-o', '--output', default='output.lua',
                         help='Output file (default: output.lua)')
    parser.add_argument('--keep-comments', action='store_true',
                         help='Keep comments, only clean up whitespace')
    parser.add_argument('--no-rename', action='store_true',
                         help="Don't randomize local variable names")
    parser.add_argument('--no-clipboard', action='store_true',
                         help="Don't copy the result to clipboard")
    parser.add_argument('--stdout', action='store_true',
                         help='Also print the result to the terminal')
    args = parser.parse_args()

    if args.input == '-':
        src = sys.stdin.read()
    else:
        with open(args.input, 'r', encoding='utf-8') as f:
            src = f.read()

    result = minify(src, keep_comments=args.keep_comments, rename=not args.no_rename)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(result)

    orig_size = len(src.encode('utf-8'))
    new_size = len(result.encode('utf-8'))
    pct = (1 - new_size / orig_size) * 100 if orig_size else 0
    print(f'Done: {args.output} ({orig_size} -> {new_size} bytes, -{pct:.1f}%)',
          file=sys.stderr)

    if not args.no_clipboard:
        if copy_to_clipboard(result):
            print('Result copied to clipboard.', file=sys.stderr)

    if args.stdout:
        print(result)


if __name__ == '__main__':
    main()
