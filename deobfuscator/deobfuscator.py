#!/usr/bin/env python3
"""
Kicia Lua Deobfuscator
======================
Deobfuscates the custom string-encryption scheme used in kicia.lua.

Obfuscation layers identified:
  1. Function renaming  : f1, f2, f3... (top-level) / p1, v1... (locals)
  2. String encryption  : up0[up1(encrypted_str, key)]
  3. Control-flow junk  : dead loops, (nil)(), redundant assignments
  4. Anti-debug         : infinite loops under always-false conditions

String-decryption algorithm (reversed from f89):
  - Cipher    : stream cipher with LCG PRNG
  - LCG       : x_next = (a * x + c) % m  where a=1103515245, c=12345, m=99999999
  - Key seeds : x0 = key % 35184372088832 (2^45),  step = key % 255 + 2
  - State     : prev = 77 (initial accumulator)
  - Per byte  : v = (encrypted_byte + prng() + prev) % 256
                result += char_table[v]   (256-entry XOR-shuffled table)
                prev = v
"""

import re
import sys
import os
import json
from collections import defaultdict, OrderedDict


# ─────────────────────────────────────────────────────────────────────────────
# LCG PRNG  (matches f65/f66 and f89's upvalue initialisation)
# ─────────────────────────────────────────────────────────────────────────────

LCG_A = 1103515245
LCG_C = 12345
LCG_M = 99999999


class LCG:
    """Linear Congruential Generator matching the obfuscator's PRNG."""

    def __init__(self, seed: int, step: int):
        self.x     = seed % LCG_M
        self.step  = step
        self._add  = 0          # up1 shadow state

    def next_byte(self) -> int:
        """Return the next pseudo-random byte (0-255), mirroring up5()."""
        self.x   = (LCG_A * self.x + LCG_C + self._add) % LCG_M
        self._add = self.x % self.step if self.step > 0 else 0
        return self.x % 256


# ─────────────────────────────────────────────────────────────────────────────
# String decryption
# ─────────────────────────────────────────────────────────────────────────────

# Identity char-table bootstrap: the shuffle happens at runtime inside the VM.
# Without executing the code we use the nominal identity mapping (ASCII 1-256).
# After patching, callers can supply the real shuffled table.
_DEFAULT_CHAR_TABLE = [chr(i) for i in range(256)]


def decrypt_string(encrypted: str, key: int,
                   char_table: list = None) -> str:
    """
    Decrypt one obfuscated string literal.

    Parameters
    ----------
    encrypted  : raw string bytes (Lua escape sequences already resolved)
    key        : numeric key from the source (second argument of up1)
    char_table : 256-entry lookup list of single characters (optional)

    Returns
    -------
    Decrypted string, or an empty string on failure.
    """
    if char_table is None:
        char_table = _DEFAULT_CHAR_TABLE

    seed = key % 35184372088832   # 2^45
    step = key % 255 + 2
    rng  = LCG(seed, step)

    result = []
    prev   = 77                    # matches `local v184 = 77`

    try:
        raw = encrypted.encode('latin-1')
    except Exception:
        raw = bytes(ord(c) % 256 for c in encrypted)

    for b in raw:
        prev = (b + rng.next_byte() + prev) % 256
        result.append(char_table[prev])

    return ''.join(result)


# ─────────────────────────────────────────────────────────────────────────────
# Lua escape-sequence parser
# ─────────────────────────────────────────────────────────────────────────────

def unescape_lua_string(s: str) -> str:
    """
    Convert Lua numeric escapes (\\N, \\NNN, \\xHH) to raw bytes.
    Handles \\0, \\n, \\t, \\\\, etc.
    """
    out = []
    i   = 0
    while i < len(s):
        if s[i] != '\\':
            out.append(s[i])
            i += 1
            continue
        i += 1
        if i >= len(s):
            break
        c = s[i]
        if c == 'n':
            out.append('\n'); i += 1
        elif c == 't':
            out.append('\t'); i += 1
        elif c == 'r':
            out.append('\r'); i += 1
        elif c == '\\':
            out.append('\\'); i += 1
        elif c == '"':
            out.append('"'); i += 1
        elif c == "'":
            out.append("'"); i += 1
        elif c == '0':
            # \0  or  \0NN
            j = i + 1
            while j < i + 3 and j < len(s) and s[j].isdigit():
                j += 1
            out.append(chr(int(s[i:j])));  i = j
        elif c.isdigit():
            j = i
            while j < i + 3 and j < len(s) and s[j].isdigit():
                j += 1
            out.append(chr(int(s[i:j]) % 256));  i = j
        elif c == 'x':
            out.append(chr(int(s[i+1:i+3], 16)));  i += 3
        else:
            out.append(c);  i += 1
    return ''.join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Source-file scanner
# ─────────────────────────────────────────────────────────────────────────────

# Matches:  up1("...", 123456789)
#       or: up3("...", 123456789)
_CALL_RE = re.compile(
    r'up\d+\s*\(\s*("(?:[^"\\]|\\.)*")\s*,\s*(\d+)\s*\)',
    re.DOTALL
)

# Matches:  up0[up1("...", 123)]
_INDEXED_RE = re.compile(
    r'up0\[up1\s*\(\s*("(?:[^"\\]|\\.)*")\s*,\s*(\d+)\s*\)\]',
    re.DOTALL
)


def extract_encrypted_strings(source: str) -> list:
    """Return [(raw_str, key, line_no), ...] for every decrypt call found."""
    results = []
    for m in _INDEXED_RE.finditer(source):
        raw_str = m.group(1)[1:-1]          # strip outer quotes
        key     = int(m.group(2))
        line_no = source[:m.start()].count('\n') + 1
        results.append((raw_str, key, line_no))
    return results


def replace_encrypted_strings(source: str, char_table=None) -> tuple:
    """
    Replace every  up0[up1("...", KEY)]  with the decrypted literal.

    Returns (new_source, replacements_dict).
    """
    replacements = {}
    cache        = {}

    def replacer(m):
        raw_str = m.group(1)[1:-1]
        key     = int(m.group(2))
        ckey    = (raw_str, key)
        if ckey not in cache:
            unescaped = unescape_lua_string(raw_str)
            decrypted = decrypt_string(unescaped, key, char_table)
            cache[ckey] = decrypted
        decrypted = cache[ckey]
        replacements[ckey] = decrypted
        return f'"{decrypted}"'

    new_source = _INDEXED_RE.sub(replacer, source)
    return new_source, replacements


# ─────────────────────────────────────────────────────────────────────────────
# Junk-code removal (conservative)
# ─────────────────────────────────────────────────────────────────────────────

# Empty functions  ->  nothing
_EMPTY_FUNC_RE = re.compile(
    r'local function (f\d+)\(\)\s*end\n', re.MULTILINE
)

# Dead  (nil)()  calls
_NIL_CALL_RE = re.compile(r'\s*;?\(nil\)\(\)\s*;?\s*\n')

# Dead  bit32.rrotate(427, 18)  without assignment
_DEAD_CALL_RE = re.compile(
    r'\s*(?:bit32\.rrotate|math\.modf)\([^)]+\)\s*\n'
)

# Redundant  local _ = ...  junk
_DUMMY_LOCAL_RE = re.compile(r'\s*local _ = [^\n]+\n')


def remove_junk(source: str) -> str:
    source = _NIL_CALL_RE.sub('\n', source)
    source = _DEAD_CALL_RE.sub('\n', source)
    source = _DUMMY_LOCAL_RE.sub('\n', source)
    # collapse multiple blank lines
    source = re.sub(r'\n{3,}', '\n\n', source)
    return source


# ─────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────

def collect_stats(source: str) -> dict:
    lines = source.splitlines()
    return {
        'total_lines'        : len(lines),
        'total_bytes'        : len(source.encode()),
        'function_defs'      : len(re.findall(r'local function f\d+', source)),
        'encrypted_strings'  : len(re.findall(r'up0\[up1\s*\(', source)),
        'upvalue_refs'       : len(re.findall(r'\bup\d+\b', source)),
        'upvalue_kinds'      : len(set(re.findall(r'\bup(\d+)\b', source))),
        'if_statements'      : source.count('\n\t\tif ') + source.count('\n\t\t\tif '),
        'while_loops'        : source.count('while '),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage:  python3 deobfuscator.py <input.lua> [output.lua]")
        sys.exit(1)

    infile  = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else infile.replace('.lua', '_deobfuscated.lua').replace('.txt', '_deobfuscated.lua')

    print(f"[*] Reading {infile} …")
    with open(infile, 'r', encoding='utf-8', errors='replace') as fh:
        source = fh.read()

    before = collect_stats(source)
    print(f"[*] Source stats:")
    print(f"      Lines     : {before['total_lines']:,}")
    print(f"      Size      : {before['total_bytes']/1024/1024:.2f} MB")
    print(f"      Functions : {before['function_defs']:,}")
    print(f"      Encrypted : {before['encrypted_strings']:,}")

    print("[*] Step 1 – decrypting strings …")
    source, replacements = replace_encrypted_strings(source)
    print(f"    Replaced  {len(replacements):,} unique (str, key) pairs")

    print("[*] Step 2 – removing junk code …")
    source = remove_junk(source)

    after = collect_stats(source)
    print(f"[*] Result stats:")
    print(f"      Lines     : {after['total_lines']:,}")
    print(f"      Size      : {after['total_bytes']/1024/1024:.2f} MB")

    print(f"[*] Writing {outfile} …")
    with open(outfile, 'w', encoding='utf-8') as fh:
        fh.write(source)

    # Write replacements JSON for inspection
    rep_file = outfile.replace('.lua', '_strings.json')
    with open(rep_file, 'w', encoding='utf-8') as fh:
        serialisable = {f"{k[0]!r}:{k[1]}": v for k, v in replacements.items()}
        json.dump(serialisable, fh, ensure_ascii=False, indent=2)
    print(f"[*] String map written to {rep_file}")
    print("[+] Done.")


if __name__ == '__main__':
    main()
