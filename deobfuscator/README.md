# Kicia Lua Deobfuscator

Static deobfuscator and analysis toolkit for `kicia.lua`, a heavily obfuscated
Roblox script.

## Features

| Feature | Description |
|---|---|
| String decryption | Reverses the LCG-based stream cipher used for all string literals |
| Junk removal | Strips `(nil)()`, dummy bit-ops, empty functions, dead assignments |
| String map export | Writes `_strings.json` with every `(encrypted → plaintext)` pair |
| Stats report | Before/after line count, size, encrypted-string count |

## Quick start

```bash
python3 deobfuscator.py kicia.lua kicia_deobfuscated.lua
```

This produces:
- `kicia_deobfuscated.lua` — source with strings decrypted and junk removed
- `kicia_strings.json`     — mapping of every decrypted string

## How the cipher works

Every string constant is stored as:

```lua
up0[up1(encrypted_bytes, key)]
-- equivalent to:
cache[decrypt(encrypted_bytes, key)]
```

where `decrypt` is a stream cipher backed by a Linear Congruential Generator:

```
a    = 1103515245
c    = 12345
m    = 99999999
x₀   = key mod 2^45
step = key mod 255 + 2

per byte b:
    x    = (a·x + c + add) mod m
    add  = x mod step
    prev = (b + x mod 256 + prev) mod 256   (prev₀ = 77)
    out += char_table[prev]
```

The `char_table` (256-entry) is built dynamically at runtime.
The static tool uses an identity mapping as an approximation (~70 % accuracy).
For exact decryption, hook `f89` inside the Roblox executor.

## Full analysis

See [analysis.md](analysis.md) for:
- All four obfuscation layers (renaming / strings / control-flow / anti-debug)
- PRNG derivation from `f65`/`f66`
- Module export map
- Step-by-step deobfuscation procedure
- Known limitations and improvement paths

## File structure

```
deobfuscator/
├── deobfuscator.py   main tool
├── analysis.md       reverse-engineering documentation
└── README.md         this file
```

## Requirements

Python 3.8+ — no external dependencies.
