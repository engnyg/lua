#!/usr/bin/env python3
"""Readability pass over the output of deobfuscator.py.

1. restore decompiler artifacts
2. remove dead code behind opaque predicates (`v = not not false`)
3. rename identifiers from a curated map

Stages 2 and 3 use the full-moon based helper in luau-tool/ for parsing and
scope resolution; this script only applies the byte-range edits it returns.
"""

import argparse
import bisect
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

from deobfuscator import Spans

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, 'luau-tool', 'target', 'release', 'luau-tool')


# --------------------------------------------------------------------------
# Stage 1: decompiler artifacts
# --------------------------------------------------------------------------

# The decompiler lost the 4-byte split at the end of the keystream generator
# (f215 / f10421): the 32-bit value is computed into `_` and an empty
# 4-slot table is created instead. Restored from the Prometheus source.
_KEYSTREAM_RE = re.compile(
    r'(?m)^([ \t]*)local _ = (\w+)\((\w+) % 1 \* 4294967296\) \+ \2\(\3\)(\r?\n)'
    r'\1(\w+) = _G\["table\.create"\]\(4\)')

_ARTIFACTS = [
    ('table.create', re.compile(r'_G\["table\.create"\]'), 'table.create'),
    ('bit32.bxor', re.compile(r'_G\["bit32\.bxor"\]'), 'bit32.bxor'),
    ('call split by semicolon', re.compile(r'(?<=[\w\])]);(?=\()'), ''),
]


class _Lines:
    def __init__(self, src):
        self.nl = [m.start() for m in re.finditer('\n', src)]

    def __call__(self, pos):
        return bisect.bisect_left(self.nl, pos) + 1


def restore_artifacts(src: str, report: dict) -> str:
    items = report.setdefault('artifacts', {})
    line = _Lines(src)

    def keystream(m):
        ind, fn, v, nl, buf = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        items.setdefault('keystream byte split', []).append(line(m.start()))
        return (f'{ind}local rnd = {fn}({v} % 1 * 4294967296) + {fn}({v}){nl}'
                f'{ind}local lo = rnd % 65536{nl}'
                f'{ind}local hi = (rnd - lo) / 65536{nl}'
                f'{ind}{buf} = {{ lo % 256, (lo - lo % 256) / 256, hi % 256, (hi - hi % 256) / 256 }}')

    src = _KEYSTREAM_RE.sub(keystream, src)

    for name, rx, repl in _ARTIFACTS:
        spans, line = Spans(src), _Lines(src)
        lines = []

        def sub(m):
            if spans.inside(m.start()):
                return m.group()
            lines.append(line(m.start()))
            return repl

        src = rx.sub(sub, src)
        items[name] = lines
    return src


# --------------------------------------------------------------------------
# luau-tool bridge
# --------------------------------------------------------------------------

def run_tool(cmd: str, src: str) -> dict:
    """Run luau-tool on `src`; edits come back as UTF-8 byte offsets."""
    if not os.path.exists(TOOL):
        sys.exit(f'{TOOL} not found; build it with: cargo build --release '
                 f'--manifest-path {os.path.join(HERE, "luau-tool", "Cargo.toml")}')
    with tempfile.NamedTemporaryFile('wb', suffix='.lua', delete=False) as fh:
        fh.write(src.encode('utf-8'))
        path = fh.name
    try:
        out = subprocess.run([TOOL, cmd, path], check=True,
                             capture_output=True, text=True).stdout
    finally:
        os.unlink(path)
    return json.loads(out)


def apply_edits(src: str, edits: list) -> str:
    data = src.encode('utf-8')
    edits = sorted(edits, key=lambda e: e['start'])
    out, pos = [], 0
    for e in edits:
        if e['start'] < pos:
            raise ValueError(f'overlapping edits at byte {e["start"]}')
        out.append(data[pos:e['start']])
        out.append(e['text'].encode('utf-8'))
        pos = e['end']
    out.append(data[pos:])
    return b''.join(out).decode('utf-8')


def check_syntax(src: str) -> list:
    return run_tool('check', src)['errors']


# --------------------------------------------------------------------------
# Stage 2: opaque predicates (report only)
# --------------------------------------------------------------------------

_TRAP_RE = re.compile(r'\(nil\)|-nil\b|\[nil\]|\((?:false|true)\)\(')
_CONTROL_ONLY_RE = re.compile(r'(?:(?:break|return|end|;)\s*)*')


def classify(body: str) -> str:
    """What the code the decompiled literal says never runs looks like."""
    if _TRAP_RE.search(body):
        return 'trap'
    if _CONTROL_ONLY_RE.fullmatch(body.strip()):
        return 'control flow only'
    return 'looks live'


def report_predicates(src: str, report: dict) -> None:
    lines = src.split('\n')
    sites = run_tool('predicates', src)['sites']
    for site in sites:
        dead = site['dead_lines']
        if dead:
            # skip the `if/while ... then/do` header line; keep the rest
            body = '\n'.join(l.strip() for l in lines[dead[0]:dead[1] - 1])
            site['dead_code'] = classify(body)
            site['excerpt'] = ' '.join(body.split())[:160]
    report['opaque_predicates'] = sites


_ZH = {
    'keystream byte split': '解密器的 4 位元組拆分（f215 / f10421）',
    'table.create': '`_G["table.create"]` → `table.create`',
    'bit32.bxor': '`_G["bit32.bxor"]` → `bit32.bxor`',
    'call split by semicolon': '`up3;(` → `up3(`',
    'assignment': '賦值',
    'condition always true': '條件恆為真',
    'condition always false': '條件恆為假',
    'loop never runs': '迴圈不執行',
    'runs once': '只跑一次',
    'infinite loop': '無窮迴圈',
    'condition depends on other values': '條件取決於其他值',
    'value not tested by the next statement': '下一句沒有用到',
    'trap': '陷阱',
    'looks live': '像真實邏輯',
    'control flow only': '只有流程控制',
}


_RULE_DOCS = {
    'Instance.new': ('`local v = Instance.new("C")`', '`uiCorner`'),
    'field': ('`local v = a.b.Field`，且 v 之後不再被賦值', '`character`'),
    'string index': ('`local v = a["Field"]`', '`host`'),
    'require': ('`local v = require(a.Module)`', '`Module`'),
    'signal handler': ('函式被傳給 `x.Signal:Connect(f)`，而且只對應一個訊號', '`onRenderStepped`'),
    'assigned to field': ('函式被存進欄位 `t.Name = f`，而且只有這一個欄位名稱', '`_reconcile`'),
    'UI section title': ('`AddSection` 的回傳值，用 `Title` 命名', '`generalSection`'),
    'lazy module getter': ('`local t = X.cache.KEY … t = { c = load() } … return t.c`',
                           '`lazyModule_dJ`'),
    'UI element label': ('`AddToggle(section, { Label = "Auto Save" })` 的回傳值與選項表',
                         '`autoSaveToggle`、`autoSaveToggleOptions`'),
}


def _zh(key: str) -> str:
    return _ZH.get(key, key)


def write_markdown(report: dict, path: str, out_name: str) -> None:
    sites = report['opaque_predicates']
    dead = [s for s in sites if s.get('dead_lines')]
    kinds = Counter(s['dead_code'] for s in dead)
    md = [f'# {out_name} 報告', '',
          '由 `optimize.py` 產生。行號對應 `' + out_name + '`。', '',
          '## 還原的反編譯殘留', '',
          '| 項目 | 處數 | 行號（前 10 個） |', '|---|---|---|']
    for k, v in report['artifacts'].items():
        md.append(f'| {_zh(k)} | {len(v)} | {", ".join(map(str, v[:10]))} |')
    md += ['', '## 不透明條件（未修改，只列出）', '',
           f'共 {len(sites)} 處 `V = not not C`。反編譯器輸出的 `not not false` 不可信'
           '（見 analysis.md 第 7 節），所以程式碼保持原樣。', '',
           f'照字面解讀會「永遠不執行」的程式碼有 {len(dead)} 段：'
           + '、'.join(f'{_zh(k)} {v} 段' for k, v in kinds.most_common()) + '。', '',
           '| 行 | 字面值 | 結構 | 字面解讀 | 不執行的行 | 內容判斷 | 摘要 |',
           '|---|---|---|---|---|---|---|']
    for s in dead:
        ex = s['excerpt'].replace('|', '\\|')
        md.append(f"| {s['line']} | `{str(s['literal']).lower()}` | {_zh(s['construct'])} | "
                  f"{_zh(s['literal_reading'])} | {s['dead_lines'][0]}–{s['dead_lines'][1]} | "
                  f"{_zh(s['dead_code'])} | `{ex}` |")
    other = Counter((s['construct'], s['literal_reading']) for s in sites if not s.get('dead_lines'))
    md += ['', '其餘各處：', '']
    md += [f'- {_zh(k[0])}，{_zh(k[1])}：{c} 處' for k, c in other.most_common()]

    renames = report.get('renames', [])
    rules = Counter(r['rule'] for r in renames)
    md += ['', '## 自動改名', '',
           f'共改名 {len(renames)} 個反編譯器產生的名稱（`vN` / `tN` / `fN`），'
           '完整對照在 JSON 報告的 `renames`。改名後重新解析整份檔案，'
           '每個變數引用指向的宣告都和改名前相同。', '',
           '不改名的範圍（Luarmor 執行環境與載入器）：'
           + '、'.join(f'第 {a}–{b} 行' for a, b in report.get('excluded_lines', [])) + '。', '',
           '| 規則 | 依據 | 例子 | 數量 |', '|---|---|---|---|']
    for key, (why, example) in _RULE_DOCS.items():
        md.append(f'| {key} | {why} | {example} | {rules.get(key, 0)} |')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(md) + '\n')


# --------------------------------------------------------------------------
# Stage 3: rename decompiler names (vN / tN / fN) from evidence in the code
# --------------------------------------------------------------------------

_KEYWORDS = set('and break do else elseif end false for function if in local nil not or '
                'repeat return then true until while continue export type self'.split())
_GENERATED = re.compile(r'[vtf]\d+')
_IDENT = re.compile(r'[A-Za-z_]\w*')


def lower_camel(name: str) -> str:
    """`UICorner` → `uiCorner`, `Character` → `character`, `CFrame` → `cFrame`."""
    m = re.match(r'([A-Z]+)(?=[A-Z][a-z])|([A-Z]+)(?![a-z])|([A-Z])', name)
    if not m:
        return name
    head = m.group()
    return head.lower() + name[len(head):]


class Renamer:
    """Proposes names from local evidence, assigns them without clashes and
    returns byte-range edits (UTF-8 offsets)."""

    def __init__(self, src: str, skip_ranges):
        self.src = src
        self.data = src.encode('utf-8')
        res = run_tool('resolve', src)
        self.names = res['names']                     # [start, end, name, target, is_decl]
        self.starts = [n[0] for n in self.names]
        self.decl_index = {n[3]: i for i, n in enumerate(self.names) if n[4]}
        self.refs = {}
        for i, n in enumerate(self.names):
            if not n[4] and n[3] >= 0:
                self.refs.setdefault(n[3], []).append(i)
        self.fn_by_name = {name: (s, e) for name, s, e in res['functions']}
        self.bodies = [tuple(b) for b in res['bodies']]    # sorted by start
        self.body_starts = [b[0] for b in self.bodies]
        self.skip = skip_ranges
        self.proposals = {}                           # decl id -> (name, rule)
        self.free_renames = []                        # (scope, old, new, [name indexes])
        self.errors = []
        self.used_cache = {}
        self.assigned = {}                            # new name -> [scope ranges]

    # -- source helpers ----------------------------------------------------
    def line_around(self, pos):
        s = self.data.rfind(b'\n', 0, pos) + 1
        e = self.data.find(b'\n', pos)
        e = len(self.data) if e < 0 else e
        return s, e, self.data[s:e].decode('utf-8').rstrip('\r')

    def is_write(self, idx):
        start, end = self.names[idx][0], self.names[idx][1]
        ls, _, line = self.line_around(start)
        before = self.data[ls:start].decode('utf-8')
        after = self.data[end:self.line_around(start)[1]].decode('utf-8')
        return bool(re.fullmatch(r'\s*(?:local\s+)?(?:[\w.\[\]"]+\s*,\s*)*', before)
                    and re.match(r'\s*(?:,\s*[\w.\[\]"]+\s*)*(?:=(?!=)|[-+*/%^.]{1,2}=)', after))

    def skipped(self, pos):
        return any(a <= pos < b for a, b in self.skip)

    # -- scopes ------------------------------------------------------------
    def scope_of(self, pos):
        """Innermost function body containing pos (whole file if none). Bodies
        nest, so the last one starting before pos that also ends after it is
        the innermost."""
        i = bisect.bisect_right(self.body_starts, pos) - 1
        while i >= 0:
            s, e = self.bodies[i]
            if pos < e:
                return (s, e)
            i -= 1
        return (0, len(self.data))

    def used(self, scope):
        if scope not in self.used_cache:
            lo = bisect.bisect_left(self.starts, scope[0])
            hi = bisect.bisect_left(self.starts, scope[1])
            self.used_cache[scope] = {n[2] for n in self.names[lo:hi]}
        return self.used_cache[scope]

    def free(self, name, scope):
        if name in _KEYWORDS or name in self.used(scope):
            return False
        for a, b in self.assigned.get(name, ()):
            if a <= scope[0] < b or scope[0] <= a < scope[1]:
                return False
        return True

    # -- rules ---------------------------------------------------------------
    def propose(self, decl_id, name, rule):
        if decl_id in self.proposals or not name or not _IDENT.fullmatch(name):
            return
        self.proposals[decl_id] = (name, rule)

    def rule_manual(self, table: dict):
        """Curated names: {scope function: {old: new}}. A name declared in the
        scope renames that binding; otherwise free names (upN) in the scope."""
        for scope_name, mapping in table.items():
            if scope_name.startswith('_'):
                continue  # comment keys
            if scope_name not in self.fn_by_name:
                self.errors.append(f'{scope_name}: no such function')
                continue
            scope = self.fn_by_name[scope_name]
            lo = bisect.bisect_left(self.starts, scope[0])
            hi = bisect.bisect_left(self.starts, scope[1])
            for old, new in mapping.items():
                if old == '_comment':
                    continue
                if not _IDENT.fullmatch(new) or new in _KEYWORDS:
                    self.errors.append(f'{scope_name}.{old}: invalid name {new!r}')
                    continue
                decls = [self.names[i] for i in range(lo, hi)
                         if self.names[i][4] and self.names[i][2] == old]
                if len(decls) == 1:
                    self.proposals[decls[0][3]] = (new, 'manual')
                elif len(decls) > 1:
                    self.errors.append(f'{scope_name}.{old}: declared {len(decls)} times')
                else:
                    # upvalues are numbered per prototype: only refs whose
                    # innermost function is the scope itself
                    body = self.bodies[bisect.bisect_left(self.body_starts, scope[0])]
                    refs = [i for i in range(lo, hi)
                            if self.names[i][2] == old and self.names[i][3] == -1
                            and self.scope_of(self.names[i][0]) == body]
                    if refs:
                        self.free_renames.append((body, old, new, refs))
                    else:
                        self.errors.append(f'{scope_name}.{old}: not found')

    def rule_local_value(self):
        rx = [
            ('Instance.new', re.compile(r'Instance\.new\("(\w+)"\)'), lower_camel),
            ('require', re.compile(r'require\([\w.:]*\.([A-Za-z_]\w*)\)'), str),
            ('field', re.compile(r'[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*\.([A-Za-z_]\w*)'), lower_camel),
            ('string index', re.compile(r'[A-Za-z_][\w.]*\["([A-Za-z_]\w*)"\]'), lower_camel),
        ]
        for i, n in enumerate(self.names):
            if not n[4] or not _GENERATED.fullmatch(n[2]) or self.skipped(n[0]):
                continue
            ls, le, line = self.line_around(n[0])
            m = re.fullmatch(r'\s*local ' + re.escape(n[2]) + r' = (.+?)\s*', line)
            if not m or any(self.is_write(r) for r in self.refs.get(n[3], ())):
                continue
            for rule, pat, fmt in rx:
                v = pat.fullmatch(m.group(1))
                if v:
                    self.propose(n[3], fmt(v.group(1)), rule)
                    break

    def rule_function_refs(self):
        for i, n in enumerate(self.names):
            if not n[4] or not re.fullmatch(r'f\d+', n[2]) or self.skipped(n[0]):
                continue
            if any(self.is_write(r) for r in self.refs.get(n[3], ())):
                continue
            fields, signals = set(), set()
            for r in self.refs.get(n[3], ()):
                _, _, line = self.line_around(self.names[r][0])
                m = re.fullmatch(r'\s*[\w.\[\]"]*?(?:\.([A-Za-z_]\w*)|\["([A-Za-z_]\w*)"\]) = '
                                 + re.escape(n[2]) + r'\s*', line)
                if m:
                    fields.add(m.group(1) or m.group(2))
                for m in re.finditer(r'(?:\.([A-Za-z_]\w*)|:GetPropertyChangedSignal\("(\w+)"\))'
                                     r':(?:Connect|Once)\(' + re.escape(n[2]) + r'\)', line):
                    sig = m.group(1) or m.group(2) + 'Changed'
                    signals.add('on' + sig[0].upper() + sig[1:])
            if len(fields) == 1:
                self.propose(n[3], fields.pop(), 'assigned to field')
            elif not fields and len(signals) == 1:
                self.propose(n[3], signals.pop(), 'signal handler')

    def rule_sections(self):
        rx = re.compile(r'(?m)^[ \t]*local (t\d+) = \{ Title = "([^"]+)"[^\n]*\n'
                        r'[ \t]*local (t\d+) = \w+\(\w+, \1\)')
        for m in rx.finditer(self.src):
            words = re.findall(r'[A-Za-z0-9]+', m.group(2))
            if not words:
                continue
            name = words[0].lower() + ''.join(w.capitalize() for w in words[1:]) + 'Section'
            pos = len(self.src[:m.start(3)].encode('utf-8'))
            i = bisect.bisect_left(self.starts, pos)
            if i < len(self.names) and self.names[i][0] == pos and self.names[i][4] \
                    and not self.skipped(pos):
                self.propose(self.names[i][3], name if name[0].isalpha() else '_' + name,
                             'UI section title')

    def table_text(self, pos):
        """(text, byte offset) of the `{ ... }` constructor at the first `{` after pos."""
        i = self.data.find(b'{', pos)
        depth, j, n = 0, i, min(len(self.data), i + 4000)
        while j < n:
            c = self.data[j]
            if c == 0x22:  # skip "strings"
                j += 1
                while j < n and self.data[j] != 0x22:
                    j += 2 if self.data[j] == 0x5C else 1
            elif c == 0x7B:
                depth += 1
            elif c == 0x7D:
                depth -= 1
                if depth == 0:
                    return self.data[i:j + 1].decode('utf-8'), i
            j += 1
        return None, i

    def index_at(self, pos):
        i = bisect.bisect_left(self.starts, pos)
        return i if i < len(self.names) and self.names[i][0] == pos else None

    def name_at(self, pos):
        i = self.index_at(pos)
        return None if i is None else self.names[i]

    def element_kind(self, callee_idx):
        """`AddToggle3` → `Toggle`; a local alias `local v = x.AddSlider` → `Slider`."""
        name = self.names[callee_idx]
        m = re.fullmatch(r'Add([A-Z]\w*?)\d*', name[2])
        if m:
            return m.group(1)
        if name[3] < 0:
            return None
        d = self.names[self.decl_index[name[3]]]
        _, _, line = self.line_around(d[0])
        m = re.fullmatch(r'\s*local ' + re.escape(d[2]) + r' = [\w.]+\.Add([A-Z]\w*?)\s*', line)
        return m.group(1) if m else None

    _KINDS = ('Toggle', 'Slider', 'Dropdown', 'Label', 'Button', 'TextBox', 'List', 'Color',
              'Keybind', 'Group', 'Gear', 'Tab', 'Section')

    def base_from(self, text, tstart, key):
        """Base name from `key = var.Row` / `key = var`, using var's proposed name."""
        m = re.search(r'(?:^\{|,)\s*' + key + r' = (\w+)(?:\.Row)?\s*[,}]', text)
        if not m:
            return None
        tok = self.name_at(tstart + len(text[:m.start(1)].encode('utf-8')))
        prop = tok and tok[3] >= 0 and self.proposals.get(tok[3])
        if not prop:
            return None
        for kind in self._KINDS:
            if prop[0].endswith(kind) and len(prop[0]) > len(kind):
                return prop[0][:-len(kind)]
        return None

    def rule_ui_elements(self):
        """`local t = { Label = "Auto Save", ... }` used once as
        `[local v =] AddToggle3(section, t)` → `autoSaveToggleOptions` and
        `autoSaveToggle`. Later passes also name `{ Row = autoSaveLabel.Row }`
        (the control on that label's row), `{ Option = "Solid" }` groups and
        `{ Source = animateToggle }` groups."""
        candidates = []
        for n in self.names:
            if not n[4] or not re.fullmatch(r't\d+', n[2]) or self.skipped(n[0]):
                continue
            _, _, line = self.line_around(n[0])
            if not re.match(r'\s*local ' + n[2] + r' = \{', line):
                continue
            refs = self.refs.get(n[3], ())
            if any(self.is_write(r) for r in refs):
                continue
            calls = []
            for r in refs:
                _, _, rl = self.line_around(self.names[r][0])
                m = re.fullmatch(r'\s*(?:local ([vt]\d+) = )?(\w+)\(\w+, ' + n[2] + r'\)\s*', rl)
                if m:
                    calls.append((m, self.names[r][0]))
            if len(calls) != 1:
                continue
            (m, at), = calls
            ls, _, rl = self.line_around(at)
            callee = self.index_at(ls + len(rl[:m.start(2)].encode('utf-8')))
            kind = None if callee is None else self.element_kind(callee)
            if not kind:
                continue
            text, tstart = self.table_text(n[1])
            if text:
                candidates.append((n, m, ls, rl, kind, text, tstart))

        for pass_ in range(3):
            for n, m, ls, rl, kind, text, tstart in candidates:
                if n[3] in self.proposals:
                    continue
                base = None
                label = re.search(r'(?:^\{|,)\s*Label = "([^"]+)"', text)
                if label:
                    base = self.camel(label.group(1))
                elif pass_ > 0:
                    option = re.search(r'(?:^\{|,)\s*Option = "([^"]+)"', text)
                    if option:
                        base = self.camel(option.group(1))
                    else:
                        base = self.base_from(text, tstart, 'Row') or self.base_from(text, tstart, 'Source')
                if not base:
                    continue
                self.propose(n[3], base + kind + 'Options', 'UI element label')
                if m.group(1):
                    d = self.name_at(ls + len(rl[:m.start(1)].encode('utf-8')))
                    if d and d[4] and not any(self.is_write(r) for r in self.refs.get(d[3], ())):
                        self.propose(d[3], base + kind, 'UI element label')

    @staticmethod
    def camel(text):
        words = re.findall(r'[A-Za-z0-9]+', text)
        if not words:
            return None
        first = words[0].lower() if words[0].isupper() else words[0][0].lower() + words[0][1:]
        base = first + ''.join(w[0].upper() + w[1:] for w in words[1:])
        return '_' + base if base[0].isdigit() else base

    def rule_lazy_modules(self):
        """`local function f() local t = X.cache.KEY if not t then t = { c = load() }
        X.cache.KEY = t end return t.c end` → `lazyModule_KEY`."""
        rx = re.compile(
            r'(?m)^[ \t]*local function (f\d+)\(\)[ \t]*\r?\n'
            r'[ \t]*local (t\d+) = ([\w.]+)\.cache\.(\w+)[ \t]*\r?\n'
            r'[ \t]*if not \2 then[ \t]*\r?\n'
            r'[ \t]*\2 = \{ c = [\w.]+\(\) \}[ \t]*\r?\n'
            r'[ \t]*\3\.cache\.\4 = \2[ \t]*\r?\n'
            r'[ \t]*end[ \t]*\r?\n'
            r'[ \t]*return \2\.c[ \t]*\r?\n'
            r'[ \t]*end\b')
        for m in rx.finditer(self.src):
            pos = len(self.src[:m.start(1)].encode('utf-8'))
            i = bisect.bisect_left(self.starts, pos)
            if i < len(self.names) and self.names[i][0] == pos and self.names[i][4] \
                    and not self.skipped(pos):
                self.propose(self.names[i][3], 'lazyModule_' + m.group(4), 'lazy module getter')

    # -- assignment ------------------------------------------------------------
    def pick(self, base, scope, strict):
        """`base`, or `base2`, `base3`… (`base_2` if base ends in a digit)."""
        if strict:
            return base if self.free(base, scope) else None
        sep = '_' if base[-1].isdigit() else ''
        for k in range(1, 100):
            cand = base if k == 1 else f'{base}{sep}{k}'
            if self.free(cand, scope):
                return cand
        return None

    def take(self, name, scope):
        self.assigned.setdefault(name, []).append(scope)
        self.used(scope).add(name)

    def edits(self):
        edits, applied = [], []
        for scope, old, new, refs in self.free_renames:
            if not self.free(new, scope):
                self.errors.append(f'{old} -> {new}: name already used in scope')
                continue
            self.take(new, scope)
            edits += [{'start': self.names[i][0], 'end': self.names[i][1], 'text': new}
                      for i in refs]
            applied.append({'line': self.data.count(b'\n', 0, self.names[refs[0]][0]) + 1,
                            'old': old, 'new': new, 'rule': 'manual (upvalue)'})

        # curated names first, then evidence-based ones, each in source order
        order = sorted(self.proposals.items(),
                       key=lambda kv: (kv[1][1] != 'manual', self.names[self.decl_index[kv[0]]][0]))
        for decl_id, (base, rule) in order:
            d = self.names[self.decl_index[decl_id]]
            scope = self.scope_of(d[0])
            cand = self.pick(base, scope, strict=rule == 'manual')
            if cand is None:
                if rule == 'manual':
                    self.errors.append(f'{d[2]} -> {base}: name already used in scope')
                continue
            self.take(cand, scope)
            for idx in [self.decl_index[decl_id]] + self.refs.get(decl_id, []):
                edits.append({'start': self.names[idx][0], 'end': self.names[idx][1], 'text': cand})
            applied.append({'line': self.data.count(b'\n', 0, d[0]) + 1,
                            'old': d[2], 'new': cand, 'rule': rule})
        return edits, applied


def luarmor_ranges(src: str):
    """Line ranges of the Luarmor runtime: f1, and the loader prologue inside
    the function that reads LUARMOR_* flags, up to its last top-level
    `while true do`, the loop that runs the protected script."""
    lines = src.split('\n')
    ranges = []
    for i, l in enumerate(lines):
        if re.match(r'local function f1\(', l):
            end = next(j for j in range(i + 1, len(lines)) if re.match(r'end\b', lines[j]))
            ranges.append((i + 1, end + 1))
            break
    mark = next(i for i, l in enumerate(lines) if 'LUARMOR_SkipAntidebugDevMode' in l)
    start = next(i for i in range(mark, -1, -1) if re.match(r'\tlocal function f\d+\(', lines[i]))
    fn_end = next(i for i in range(mark, len(lines)) if re.match(r'\tend\b', lines[i]))
    stop = max(i for i in range(mark, fn_end) if re.fullmatch(r'\t\twhile true do\s*', lines[i]))
    ranges.append((start + 1, stop))
    return ranges


def signature(src: str):
    """Binding structure: (is_decl, target) per name token, in order."""
    return [(n[4], n[3]) for n in run_tool('resolve', src)['names']]


def auto_rename(src: str, report: dict, skip_lines, manual=None) -> str:
    data = src.encode('utf-8')
    line_starts = [0] + [m.end() for m in re.finditer(rb'\n', data)]
    skip = [(line_starts[a - 1], line_starts[b] if b < len(line_starts) else len(data))
            for a, b in skip_lines]
    r = Renamer(src, skip)
    r.rule_manual(manual or {})
    r.rule_function_refs()
    r.rule_sections()
    r.rule_ui_elements()
    r.rule_lazy_modules()
    r.rule_local_value()
    edits, applied = r.edits()
    if r.errors:
        sys.exit('names.json problems:\n  ' + '\n  '.join(r.errors))
    out = apply_edits(src, edits)
    before = [(n[4], n[3]) for n in r.names]
    if signature(out) != before:
        sys.exit('rename changed variable binding; aborting')
    report['renames'] = applied
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='output of deobfuscator.py')
    ap.add_argument('-o', '--output', help='default: <input>_optimized.lua')
    ap.add_argument('-r', '--report', help='default: <output>_report.json (+ .md)')
    ap.add_argument('-n', '--names', default=os.path.join(HERE, 'names.json'),
                    help='curated names {scope function: {old: new}} (default: names.json)')
    args = ap.parse_args(argv)

    root = os.path.splitext(args.input)[0]
    out = args.output or root + '_optimized.lua'
    rep = args.report or os.path.splitext(out)[0] + '_report.json'
    rep_md = os.path.splitext(rep)[0] + '.md'
    if len({os.path.realpath(p) for p in (args.input, out, rep, rep_md)}) != 4:
        ap.error('input, output and report paths must all differ')

    with open(args.input, encoding='latin-1', newline='') as fh:
        src = fh.read()
    report = {}

    src = restore_artifacts(src, report)
    errors = check_syntax(src)
    if errors:
        sys.exit(f'syntax errors after restoring artifacts: {errors[:5]}')
    report_predicates(src, report)
    report['excluded_lines'] = luarmor_ranges(src)
    manual = {}
    if os.path.exists(args.names):
        with open(args.names, encoding='utf-8') as fh:
            manual = json.load(fh)
    src = auto_rename(src, report, report['excluded_lines'], manual)
    errors = check_syntax(src)
    if errors:
        sys.exit(f'syntax errors after renaming: {errors[:5]}')

    with open(out, 'w', encoding='latin-1', newline='') as fh:
        fh.write(src)
    with open(rep, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    write_markdown(report, rep_md, os.path.basename(out))

    counts = {k: len(v) for k, v in report['artifacts'].items()}
    print(f'artifacts restored : {counts}')
    dead = Counter(x['dead_code'] for x in report['opaque_predicates'] if x.get('dead_lines'))
    print(f'opaque predicates  : {len(report["opaque_predicates"])} sites, '
          f'literally-dead code: {dict(dead)} (reported, not removed)')
    rules = Counter(x['rule'] for x in report['renames'])
    print(f'renamed            : {len(report["renames"])} bindings {dict(rules)}')
    print(f'excluded (Luarmor) : lines {report["excluded_lines"]}')
    print(f'wrote {out}, {rep} and {rep_md}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
