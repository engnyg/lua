#!/usr/bin/env python3
"""Static deobfuscator for kicia.lua.

Decrypts the Prometheus-style encrypted string constants and removes junk
statements that are provably side-effect free. Everything else is left
byte-for-byte unchanged. See analysis.md for the reverse-engineering notes.
"""

import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter

MOD45 = 2 ** 45
MOD32 = 2 ** 32


# --------------------------------------------------------------------------
# Cipher (reversed from f10421 / f10422, and their copies f215 / f89)
# --------------------------------------------------------------------------

def keystream(key: int):
    s45 = key % MOD45
    s8 = key % 255 + 2
    buf = []
    while True:
        if not buf:
            s45 = (s45 * 149 + 4033097371307) % MOD45
            s8 = s8 * 37 % 257
            while s8 == 1:
                s8 = s8 * 37 % 257
            r = s8 % 32
            n = (s45 // 2 ** (13 - (s8 - r) // 32)) % MOD32 / 2 ** r
            rnd = int(n % 1 * MOD32) + int(n)
            lo, hi = rnd % 65536, rnd // 65536
            buf = [lo % 256, lo // 256, hi % 256, hi // 256]
        yield buf.pop()


def decrypt(cipher: bytes, key: int) -> bytes:
    out = bytearray()
    prev = 77
    for b, k in zip(cipher, keystream(key)):
        prev = (b + k + prev) % 256
        out.append(prev)  # the char table (t299) is the identity map
    return bytes(out)


# --------------------------------------------------------------------------
# Lua string literals
# --------------------------------------------------------------------------

_SIMPLE_ESC = {'a': 7, 'b': 8, 'f': 12, 'n': 10, 'r': 13, 't': 9, 'v': 11,
               '\\': 92, '"': 34, "'": 39}


def parse_lua_string(body: str) -> bytes:
    """Decode the inside of a quoted Lua literal. `body` is latin-1 text."""
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c != '\\':
            out.append(ord(c))
            i += 1
            continue
        i += 1
        if i >= n:
            raise ValueError('dangling backslash')
        c = body[i]
        if c in _SIMPLE_ESC:
            out.append(_SIMPLE_ESC[c])
            i += 1
        elif c in '\r\n':
            out.append(10)
            i += 2 if body[i:i + 2] in ('\r\n', '\n\r') else 1
        elif c == 'z':
            i += 1
            while i < n and body[i] in ' \t\r\n\v\f':
                i += 1
        elif c == 'x':
            h = body[i + 1:i + 3]
            if not re.fullmatch(r'[0-9A-Fa-f]{2}', h):
                raise ValueError('bad \\x escape')
            out.append(int(h, 16))
            i += 3
        elif c.isdigit():
            m = re.match(r'\d{1,3}', body[i:])
            v = int(m.group())
            if v > 255:
                raise ValueError('decimal escape too large')
            out.append(v)
            i += len(m.group())
        elif c == 'u':
            m = re.match(r'u\{([0-9A-Fa-f]+)\}', body[i:])
            if not m or int(m.group(1), 16) > 0x10FFFF:
                raise ValueError('bad \\u escape')
            out += chr(int(m.group(1), 16)).encode('utf-8', 'surrogatepass')
            i += len(m.group())
        else:
            raise ValueError('invalid escape \\' + c)
    return bytes(out)


def lua_quote(data: bytes) -> str:
    parts = ['"']
    for b in data:
        if b == 34:
            parts.append('\\"')
        elif b == 92:
            parts.append('\\\\')
        elif b == 10:
            parts.append('\\n')
        elif b == 13:
            parts.append('\\r')
        elif b == 9:
            parts.append('\\t')
        elif 32 <= b < 127:
            parts.append(chr(b))
        else:
            parts.append('\\%03d' % b)
    parts.append('"')
    return ''.join(parts)


# --------------------------------------------------------------------------
# Minimal lexer: locate strings and comments so matches inside them are skipped
# --------------------------------------------------------------------------

_STR = r'"(?:[^"\\\r\n]|\\(?:\r\n|\n\r|z\s*|[\s\S]))*"'
_SPAN_RE = re.compile(
    r'--\[(=*)\[[\s\S]*?\]\1\]'
    r'|--[^\r\n]*'
    r'|\[(=*)\[[\s\S]*?\]\2\]'
    r'|' + _STR +
    r"|'(?:[^'\\\r\n]|\\(?:\r\n|\n\r|z\s*|[\s\S]))*'"
)


class Spans:
    def __init__(self, src: str):
        self.starts, self.ends = [], []
        for m in _SPAN_RE.finditer(src):
            self.starts.append(m.start())
            self.ends.append(m.end())

    def inside(self, pos: int) -> bool:
        i = bisect.bisect_right(self.starts, pos) - 1
        return i >= 0 and pos < self.ends[i]


def blank_strings(src: str) -> str:
    """Blank out strings/comments (same length, newlines kept) for token analysis."""
    def repl(m):
        t = m.group()
        if t.startswith('--'):
            return re.sub(r'[^\n]', ' ', t)
        return t[0] + re.sub(r'[^\n]', ' ', t[1:-1]) + t[-1]
    return _SPAN_RE.sub(repl, src)


# --------------------------------------------------------------------------
# String decryption passes
# --------------------------------------------------------------------------

class Decryptor:
    def __init__(self):
        self.table = {}          # (cipher bytes, key) -> plain bytes
        self.sites = Counter()
        self.failed = []

    def get(self, lit: str, key: int):
        try:
            cipher = parse_lua_string(lit[1:-1])
        except ValueError as e:
            self.failed.append((lit, key, str(e)))
            return None
        k = (cipher, key)
        if k not in self.table:
            self.table[k] = decrypt(cipher, key)
        self.sites[k] += 1
        return lua_quote(self.table[k])


_MIN_KEY = 10 ** 9

# cache[decrypt("...", KEY)]
_LITERAL_RE = re.compile(
    r'(?<![\w.:])(\w+)\[(\w+)\(\s*(' + _STR + r')\s*,\s*(\d+)\s*\)\]')

# F = F("...", KEY) \n F = cache[F]
_REG_CALL_RE = re.compile(
    r'(?m)^([ \t]*)(\w+) = \2\(\s*(' + _STR + r')\s*,\s*(\d+)\s*\)[ \t]*\r?\n'
    r'[ \t]*\2 = \w+\[\2\][ \t]*(?=\r?$)')

# cache[decrypt(var | "...", var | KEY)] where the variables are set just above
_REG_ARGS_RE = re.compile(
    r'(?<![\w.:])(\w+)\[(\w+)\(\s*(\w+|' + _STR + r')\s*,\s*(\w+)\s*\)\]')

_BLOCK_WORDS = re.compile(
    r'\b(?:end|else|elseif|then|do|function|repeat|until|while|for|return|goto)\b|::')


_SUFFIX_RE = re.compile(r'\s*(?:[\[:({"\']|\.(?!\.))')
_CONTINUES_RE = re.compile(
    r'(?:[-+*/%^#<>=,(\[{~]|\.\.|\b(?:and|or|not|return|local|in|then|do|else))\s*$')


def as_expr(src: str, m, q: str) -> str:
    """Make literal `q` valid where match `m` stood: `"s":f()` must be `("s"):f()`,
    and at the start of a statement a leading `;` stops Lua from reading it
    as a call on the previous line."""
    if not _SUFFIX_RE.match(src, m.end()):
        return q
    q = '(' + q + ')'
    start = src.rfind('\n', 0, src.rfind('\n', 0, m.start()))
    before = blank_strings(src[start + 1:m.start()]).rstrip()
    if not before or not _CONTINUES_RE.search(before):
        q = ';' + q
    return q


def pass_literal(src: str, dec: Decryptor) -> str:
    spans = Spans(src)

    def repl(m):
        key = int(m.group(4))
        if key < _MIN_KEY or spans.inside(m.start()):
            return m.group()
        q = dec.get(m.group(3), key)
        return as_expr(src, m, q) if q is not None else m.group()

    return _LITERAL_RE.sub(repl, src)


def pass_register_call(src: str, dec: Decryptor) -> str:
    spans = Spans(src)

    def repl(m):
        key = int(m.group(4))
        if key < _MIN_KEY or spans.inside(m.start(2)):
            return m.group()
        q = dec.get(m.group(3), key)
        if q is None:
            return m.group()
        return f'{m.group(1)}{m.group(2)} = {q}'

    return _REG_CALL_RE.sub(repl, src)


def _lookback(lines, idx, name, value_re, alias=True):
    """Value of `name` at lines[idx], from `[local] name = <value>` in the
    straight-line code just above; follows one `name = other` alias."""
    tok = re.compile(r'(?<![\w.:])' + re.escape(name) + r'(?!\w)')
    assign = re.compile(r'[ \t]*(?:local )?' + re.escape(name) +
                        r' = (' + value_re + r'|\w+)[ \t]*\r?')
    for j in range(idx - 1, max(idx - 9, -1), -1):
        m = assign.fullmatch(lines[j])
        if m:
            if re.fullmatch(value_re, m.group(1)):
                return m.group(1)
            if alias and re.fullmatch(r'[A-Za-z_]\w*', m.group(1)):
                return _lookback(lines, j, m.group(1), value_re, alias=False)
            return None
        code = blank_strings(lines[j])
        if _BLOCK_WORDS.search(code) or tok.search(code):
            return None
    return None


def pass_register_args(src: str, dec: Decryptor) -> str:
    spans = Spans(src)
    line_starts = [0] + [m.end() for m in re.finditer(r'\n', src)]
    lines = src.split('\n')

    def repl(m):
        if spans.inside(m.start()):
            return m.group()
        idx = bisect.bisect_right(line_starts, m.start()) - 1
        prefix = src[line_starts[idx]:m.start()]
        words = {w.group() for w in _BLOCK_WORDS.finditer(blank_strings(prefix))}
        if words - {'return', 'then'}:
            return m.group()
        a, b = m.group(3), m.group(4)
        if a.isdigit() or (b.isdigit() and a.startswith('"')):
            return m.group()  # plain literal form is handled by pass_literal
        lit = a if a.startswith('"') else _lookback(lines, idx, a, _STR)
        if lit is None:
            return m.group()
        if b.isdigit():
            key = int(b)
        else:
            k = _lookback(lines, idx, b, r'\d+')
            if k is None:
                return m.group()
            key = int(k)
        if key < _MIN_KEY:
            return m.group()
        q = dec.get(lit, key)
        return as_expr(src, m, q) if q is not None else m.group()

    return _REG_ARGS_RE.sub(repl, src)


# --------------------------------------------------------------------------
# Junk removal (only statements that are provably side-effect free)
# --------------------------------------------------------------------------

_PURE_FUNCS = {
    'bit32': None,  # every bit32 function is pure
    'math': {'abs', 'ceil', 'floor', 'fmod', 'modf', 'max', 'min', 'sqrt',
             'exp', 'log', 'pow', 'sin', 'cos', 'tan', 'asin', 'acos',
             'atan', 'sinh', 'cosh', 'tanh', 'rad', 'deg', 'frexp', 'ldexp',
             'sign', 'clamp', 'round', 'log10', 'noise'},
    'string': {'byte', 'char', 'len', 'sub', 'rep', 'lower', 'upper',
               'reverse', 'pack', 'unpack', 'format'},
}
_EXPR_TOKEN = re.compile(
    r'\s+|0[xX][0-9A-Fa-f]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?'
    r'|' + _STR + r'|\.\.|==|~=|<=|>=|[-+*/%^#<>(),]'
    r'|\b(?:and|or|not|nil|true|false)\b'
    r'|(bit32|math|string)\.(\w+)(?=\s*\()')

_OPEN_WORDS = re.compile(r'(?:and|or)\b')


def is_pure_expr(expr: str) -> bool:
    pos, depth = 0, 0
    while pos < len(expr):
        m = _EXPR_TOKEN.match(expr, pos)
        if not m:
            return False
        if m.group(1):
            allowed = _PURE_FUNCS[m.group(1)]
            if allowed is not None and m.group(2) not in allowed:
                return False
        tok = m.group()
        depth += tok == '('
        depth -= tok == ')'
        if depth < 0:
            return False
        pos = m.end()
    return depth == 0 and not re.search(r'(?:[-+*/%^#<>=,(]|\.\.|\band|\bor|\bnot)\s*$', expr)


def _next_code_line(lines, i):
    for j in range(i + 1, len(lines)):
        s = lines[j].strip()
        if s and not s.startswith('--'):
            return s
    return ''


def _prev_code_line(lines, i):
    for j in range(i - 1, -1, -1):
        s = lines[j].strip()
        if s and not s.startswith('--'):
            return s
    return ''


def _safe_boundary(lines, i, check_prev):
    nxt = _next_code_line(lines, i)
    if nxt and (not re.match(r'[A-Za-z_]', nxt) or _OPEN_WORDS.match(nxt)):
        return False
    if check_prev:
        prv = blank_strings(_prev_code_line(lines, i))
        if re.search(r'(?:[-+*/%^#<>=,(\[{]|\.\.|\b(?:and|or|not|return|local|in))$', prv):
            return False
    return True


def underscore_is_read(src: str) -> bool:
    """True if `_` is ever read (not just bound or assigned to)."""
    code = blank_strings(src)
    binding = re.compile(r'(?:\blocal|\bfor|\bfunction\b[\w.:\s]*\()'
                         r'\s*(?:\w+\s*,\s*)*$')
    target = re.compile(r'[ \t]*(?:[\w.]+\s*,\s*)*_\s*(?:,\s*[\w.]+\s*)*=(?!=)')
    for m in re.finditer(r'(?<![\w.:"])_(?![\w"])', code):
        if binding.search(code, max(0, m.start() - 60), m.start()):
            continue
        if target.match(code, code.rfind('\n', 0, m.start()) + 1):
            continue
        return True
    return False


def remove_junk(src: str, stats: Counter) -> str:
    code = blank_strings(src)
    name_counts = Counter(re.findall(r'(?<![\w.:])f\d+(?!\w)', code))
    allow_local_underscore = not underscore_is_read(src)
    stats['underscore_read'] = int(not allow_local_underscore)

    lines = src.split('\n')
    code_lines = code.split('\n')
    drop = set()

    bare_call = re.compile(r'[ \t]*(bit32\.\w+|math\.\w+)\(([-+\d.,\s]*)\)[ \t]*;?[ \t]*\r?')
    local_us = re.compile(r'[ \t]*local _ = (.+?)[ \t]*;?[ \t]*\r?')
    empty_fn = re.compile(r'[ \t]*local function (f\d+)\([\w\s,.]*\)[ \t]*\r?')

    i = 0
    while i < len(lines):
        line = lines[i]
        m = bare_call.fullmatch(line)
        if m and (m.group(1).startswith('bit32.') or
                  m.group(1)[5:] in _PURE_FUNCS['math']) \
                and _safe_boundary(lines, i, check_prev=True):
            drop.add(i)
            stats['bare_pure_call'] += 1
            i += 1
            continue
        m = local_us.fullmatch(line)
        if m and allow_local_underscore and is_pure_expr(m.group(1)) \
                and _safe_boundary(lines, i, check_prev=False):
            drop.add(i)
            stats['local_underscore'] += 1
            i += 1
            continue
        m = empty_fn.fullmatch(line)
        if m and i + 1 < len(lines) and code_lines[i + 1].strip() == 'end' \
                and name_counts[m.group(1)] == 1 \
                and _safe_boundary(lines, i + 1, check_prev=False):
            drop.update((i, i + 1))
            stats['empty_function'] += 1
            i += 2
            continue
        i += 1

    return '\n'.join(l for k, l in enumerate(lines) if k not in drop)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def verify(dec: Decryptor):
    """Round-trip every emitted literal; also through real Lua when lupa exists."""
    for plain in dec.table.values():
        if parse_lua_string(lua_quote(plain)[1:-1]) != plain:
            raise AssertionError('quoting round-trip failed')
    try:
        from lupa import lua54
    except ImportError:
        return 'python only (install lupa for a Lua check)'
    L = lua54.LuaRuntime(encoding=None)
    ev = L.eval('function(s) return assert(load("return " .. s))() end')
    for plain in dec.table.values():
        if ev(lua_quote(plain).encode('latin-1')) != plain:
            raise AssertionError('Lua round-trip failed for ' + lua_quote(plain))
    return 'python + Lua 5.4'


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('-o', '--output', help='default: <input>_deobfuscated.lua')
    ap.add_argument('-s', '--strings', help='default: <output>_strings.json')
    ap.add_argument('--keep-junk', action='store_true', help='skip junk removal')
    args = ap.parse_args(argv)

    root = os.path.splitext(args.input)[0]
    out = args.output or root + '_deobfuscated.lua'
    strings = args.strings or os.path.splitext(out)[0] + '_strings.json'
    paths = [os.path.realpath(p) for p in (args.input, out, strings)]
    if len(set(paths)) != 3:
        ap.error('input, output and strings paths must all differ')

    # latin-1 maps every byte to one char, so untouched bytes round-trip exactly
    with open(args.input, encoding='latin-1', newline='') as fh:
        src = fh.read()
    before = len(src.split('\n'))

    dec = Decryptor()
    src = pass_register_call(src, dec)
    prev = None
    while prev != src:
        prev = src
        src = pass_literal(src, dec)
        src = pass_register_args(src, dec)

    stats = Counter()
    if not args.keep_junk:
        src = remove_junk(src, stats)
    check = verify(dec)

    with open(out, 'w', encoding='latin-1', newline='') as fh:
        fh.write(src)

    entries = []
    for (cipher, key), plain in sorted(dec.table.items(), key=lambda kv: kv[0][1]):
        try:
            text = plain.decode('utf-8')
        except UnicodeDecodeError:
            text = None
        entries.append({'key': key, 'cipher': lua_quote(cipher),
                        'plain': lua_quote(plain), 'text': text,
                        'sites': dec.sites[(cipher, key)]})
    with open(strings, 'w', encoding='utf-8') as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=1)

    remaining = len(re.findall(r'\w+\[\w+\(\s*"', src))
    readable = sum(1 for e in entries if e['text'] is not None and e['text'].isprintable())
    print(f'decrypted sites     : {sum(dec.sites.values())}')
    print(f'unique strings      : {len(entries)} ({readable} printable UTF-8)')
    print(f'undecodable literals: {len(dec.failed)}')
    print(f'remaining call sites: {remaining}')
    print(f'junk removed        : {dict(stats)}')
    print(f'lines               : {before} -> {len(src.split(chr(10)))}')
    print(f'literal check       : {check}')
    print(f'wrote {out} and {strings}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
