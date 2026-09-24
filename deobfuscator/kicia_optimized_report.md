# kicia_optimized.lua 報告

由 `optimize.py` 產生。行號對應 `kicia_optimized.lua`。

## 還原的反編譯殘留

| 項目 | 處數 | 行號（前 10 個） |
|---|---|---|
| 解密器的 4 位元組拆分（f215 / f10421） | 2 | 2274, 158256 |
| `_G["table.create"]` → `table.create` | 2683 | 468, 639, 774, 909, 1057, 1109, 1110, 1111, 1112, 1113 |
| `_G["bit32.bxor"]` → `bit32.bxor` | 53 | 1152, 1153, 1154, 1156, 1157, 1158, 1159, 1160, 1161, 1182 |
| `up3;(` → `up3(` | 1 | 13 |

## 不透明條件（未修改，只列出）

共 133 處 `V = not not C`。反編譯器輸出的 `not not false` 不可信（見 analysis.md 第 7 節），所以程式碼保持原樣。

照字面解讀會「永遠不執行」的程式碼有 28 段：像真實邏輯 17 段、陷阱 9 段、只有流程控制 2 段。

| 行 | 字面值 | 結構 | 字面解讀 | 不執行的行 | 內容判斷 | 摘要 |
|---|---|---|---|---|---|---|
| 1319 | `false` | if | 條件恆為假 | 1320–1328 | 像真實邏輯 | `if not v213 then v213 = 4842 end v212 = (v211 * v212 + up3) % v210 v209 = up4 + 1 up4 = v209 up2 = v212` |
| 1346 | `false` | if | 條件恆為假 | 1347–1355 | 像真實邏輯 | `if not v223 then v223 = 4842 end v222 = (v221 * v222 + v214) % v220 v219 = v216 + 1 v216 = v219 v215 = v222` |
| 1402 | `false` | if | 條件恆為假 | 1403–1411 | 像真實邏輯 | `if not v241 then v241 = 4842 end v240 = (v239 * v240 + v232) % v238 v237 = v234 + 1 v234 = v237 v233 = v240` |
| 13086 | `false` | if | 條件恆為假 | 13087–13089 | 陷阱 | `return -nil` |
| 27579 | `false` | while | 迴圈不執行 | 27580–27585 | 陷阱 | `if not ((nil).StartColor == nil or (nil).EndColor == nil) then up2(nil) break end` |
| 27706 | `false` | while | 迴圈不執行 | 27707–27712 | 陷阱 | `if not ((nil).StartColor == nil or (nil).EndColor == nil) then f2078(nil) break end` |
| 52803 | `false` | if | 條件恆為假 | 52804–52806 | 只有流程控制 | `break` |
| 85782 | `false` | if | 條件恆為假 | 85783–85788 | 陷阱 | `if (nil)._originalBodyColors[nil] == nil then end ;(nil)._originalBodyColors[nil] = (nil).Color return` |
| 86178 | `false` | if | 條件恆為假 | 86179–86184 | 陷阱 | `if (nil)._originalBodyColors[nil] == nil then end ;(nil)._originalBodyColors[nil] = (nil).Color return` |
| 87947 | `true` | if | 條件恆為假 | 87948–87950 | 陷阱 | `(nil).c = nil` |
| 103361 | `false` | if | 條件恆為假 | 103362–103367 | 像真實邏輯 | `v280 = not not false if v280 then _continue197 = true end` |
| 103363 | `false` | if | 條件恆為假 | 103364–103366 | 像真實邏輯 | `_continue197 = true` |
| 105315 | `false` | if | 條件恆為假 | 105316–105322 | 像真實邏輯 | `while t281._resolved[v443] do local _ = -4294956281 + f7027(386) + -10625 f7027 = nil t281, v443 = ... end` |
| 105679 | `false` | if | 條件恆為假 | 105680–105686 | 像真實邏輯 | `while t295._resolved[v500] do local _ = -4294956281 + f7044(386) + -10625 f7044 = nil t295, v500 = ... end` |
| 113745 | `false` | if | 條件恆為假 | 113746–113750 | 像真實邏輯 | `f7516 = unpack v71 = up0 v72 = 1` |
| 113762 | `false` | if | 條件恆為假 | 113763–113767 | 像真實邏輯 | `f7519 = unpack v77 = v76 v78 = 1` |
| 115523 | `false` | if | 條件恆為假 | 115524–115528 | 像真實邏輯 | `f7676 = unpack v240 = v239 v241 = 1` |
| 124785 | `false` | if | 條件恆為假 | 124786–124788 | 像真實邏輯 | `t154 = {}` |
| 158180 | `false` | if | 條件恆為假 | 158181–158189 | 像真實邏輯 | `if not v295 then v295 = 4842 end v294 = (v293 * v294 + v286) % v292 v291 = v288 + 1 v288 = v291 v287 = v294` |
| 160054 | `false` | if | 條件恆為假 | 160055–160057 | 只有流程控制 | `break` |
| 187507 | `false` | while | 迴圈不執行 | 187508–187513 | 陷阱 | `if not ((nil).StartColor == nil or (nil).EndColor == nil) then f11194(nil) break end` |
| 189241 | `false` | if | 條件恆為假 | 189242–189246 | 像真實邏輯 | `f11282 = unpack v4232 = v4231 v4233 = 1` |
| 190487 | `false` | if | 條件恆為假 | 190488–190494 | 像真實邏輯 | `while t924._resolved[v4381] do local _ = -4294956281 + f11338(386) + -10625 f11338 = nil t924, v4381 = ... end` |
| 192816 | `false` | if | 條件恆為假 | 192817–192819 | 像真實邏輯 | `t1043 = {}` |
| 193131 | `false` | if | 條件恆為假 | 193132–193137 | 陷阱 | `if (nil)._originalBodyColors[nil] == nil then end ;(nil)._originalBodyColors[nil] = (nil).Color return` |
| 197968 | `true` | if | 條件恆為假 | 197969–197971 | 陷阱 | `(nil).c = nil` |
| 198629 | `false` | if | 條件恆為假 | 198630–198635 | 像真實邏輯 | `v5360 = not not false if v5360 then _continue605 = true end` |
| 198631 | `false` | if | 條件恆為假 | 198632–198634 | 像真實邏輯 | `_continue605 = true` |

其餘各處：

- if，條件恆為真：38 處
- repeat，只跑一次：22 處
- repeat，無窮迴圈：20 處
- 賦值，下一句沒有用到：19 處
- while，條件恆為真：6 處

## 自動改名

共改名 63918 個反編譯器產生的名稱（`vN` / `tN` / `fN`），完整對照在 JSON 報告的 `renames`。改名後重新解析整份檔案，每個變數引用指向的宣告都和改名前相同。

不改名的範圍（Luarmor 執行環境與載入器）：第 1–3284 行、第 158122–160364 行。另外 `names.json` 的 `_skip` 列出的函式（躲避偵測的程式碼）也不改名。

| 規則 | 依據 | 例子 | 數量 |
|---|---|---|---|
| Instance.new | `local v = Instance.new("C")` | `uiCorner` | 1203 |
| field | `local v = a.b.Field`，且 v 之後不再被賦值 | `character` | 1844 |
| string index | `local v = a["Field"]` | `host` | 1 |
| require | `local v = require(a.Module)` | `Module` | 0 |
| signal handler | 函式被傳給 `x.Signal:Connect(f)`，而且只對應一個訊號 | `onRenderStepped` | 145 |
| assigned to field | 函式被存進欄位 `t.Name = f`，而且只有這一個欄位名稱 | `_reconcile` | 8 |
| UI section title | `AddSection` 的回傳值，用 `Title` 命名 | `generalSection` | 219 |
| lazy module getter | `local t = X.cache.KEY … t = { c = load() } … return t.c` | `lazyModule_dJ` | 514 |
| UI element label | `AddToggle(section, { Label = "Auto Save" })` 的回傳值與選項表 | `autoSaveToggle`、`autoSaveToggleOptions` | 2158 |
| class trove label | `function T.new` 建立 `_trove = Trove.new("a.KillFeed")`：類別與載入它的函式 | `KillFeed`、`loadKillFeed` | 270 |
| prototype copy | 獨立原型和內嵌副本逐 token 相同：沿用內嵌副本的名稱 | `hookEquipCooldown_proto(self_, item)` | 12095 |
| prototype copy (upvalue) | 同上，原型的 `upN` 取內嵌副本在同一位置的變數名稱 | `up2` → `restore` | 3126 |
| duplicate copy | 載入器裡深層巢狀的模組程式碼和已命名的函式逐 token 相同（已命名那邊的 `upN` 可對應任何名稱）：沿用已命名函式的名稱 | `v6449` → `header` | 16378 |
| module registry | 載入器登錄模組的寫法 `local A = R; local B = L; getter … A.cache.KEY … { c = B() }`：R 的別名都叫 `modules`（同一作用域重複宣告，前一個不再被使用時才可以），B 是 `loadModule_KEY` | `v4115` → `modules`、`v4116` → `loadModule_y` | 1619 |
| manual | `names.json` 人工命名 | `loadEquipCooldownModifier` | 24338 |
| manual (upvalue) | `names.json` 人工命名的上值 | `up0` → `settings` | 0 |
