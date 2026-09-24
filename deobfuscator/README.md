# kicia.lua 反混淆工具

`kicia.lua` 的靜態反混淆工具。它會解密加密的字串常數，並刪除能證明沒有副作用的垃圾程式碼。其餘內容逐位元組保留。

## 功能

| 功能 | 說明 |
|---|---|
| 字串解密 | 還原 Prometheus 風格的字串加密（45 位元 LCG + 8 位元乘法狀態，每步產生 4 個位元組） |
| 三種呼叫寫法 | `X[Y("…", KEY)]`（名稱不限）、`F = F("…", KEY)` + `F = X[F]`、以及金鑰或密文放在前幾行變數裡的寫法 |
| 安全輸出 | 解密結果一律輸出成純 ASCII 的 Lua 字面值；接方法呼叫時自動加括號，例如 `("Websocket"):Close()` |
| 垃圾程式碼刪除 | 只刪除參數全為常數的純 `bit32`/`math` 呼叫、單行純運算的 `local _ = …`、沒有任何引用的空函式 |
| 驗證 | 每個輸出字面值都用 Python 解析，並用 Lua 5.4 執行，確認和明文逐位元組相同（需要安裝 `lupa`） |

## 使用方式

```bash
python3 deobfuscator.py kicia.lua -o kicia_deobfuscated.lua
```

會產生：
- `kicia_deobfuscated.lua`：反混淆後的程式碼
- `kicia_deobfuscated_strings.json`：每個不同的 (密文, key)，包含明文與出現次數

選項：

| 選項 | 說明 |
|---|---|
| `-o, --output` | 輸出檔，預設為 `<輸入>_deobfuscated.lua` |
| `-s, --strings` | 字串對照表，預設為 `<輸出去掉副檔名>_strings.json` |
| `--keep-junk` | 只解密字串，不刪除垃圾程式碼 |

輸入、輸出、JSON 三個路徑必須不同，否則工具會拒絕執行，不會覆寫任何檔案。

## 加密方式

每個字串常數都寫成 `cache[decrypt(ciphertext, key)]`，解密器（`f10421`/`f10422`，`f1` 內另有副本 `f215`/`f89`）的運作如下：

```
s45 ← key mod 2^45,  s8 ← key mod 255 + 2,  prev ← 77

每需要 4 個新位元組：
    s45 ← (149·s45 + 4033097371307) mod 2^45
    重複 s8 ← 37·s8 mod 257，直到 s8 ≠ 1
    由 s45、s8 算出 32 位元亂數，拆成 4 個位元組（從高位開始取）

每個密文位元組 b：
    prev ← (b + 金鑰位元組 + prev) mod 256
    輸出 chr(prev)
```

字元表 `t299[i] = string.char(i - 1)` 是恆等映射，不影響結果。

## 目前的處理結果

| 項目 | 數量 |
|---|---|
| 解密的呼叫位置 | 714 |
| 不同的字串 | 404（全部是合法 UTF-8） |
| 刪除的垃圾語句 | `local _` 287 個、純函式呼叫 8 個、空函式 14 個 |
| 行數 | 269,261 → 268,494 |

用 `full-moon`（支援 Luau 語法的解析器）檢查：輸出沒有引入任何語法錯誤。唯一的錯誤是原始檔第 13 行本來就有的反編譯殘留 `up3;(`，工具保留原樣。

## 第二階段：可讀性優化（optimize.py）

```bash
cargo build --release --manifest-path luau-tool/Cargo.toml   # 需要 Rust
python3 optimize.py kicia_deobfuscated.lua -o kicia_optimized.lua
```

會產生：
- `kicia_optimized.lua`：優化後的程式碼。和 `kicia_deobfuscated.lua` 相比，只有兩處解密器還原時各多了 2 行：第 2274 行之後的行號要加 2，第 158256 行之後要加 4
- `kicia_optimized_report.md`：給人看的報告
- `kicia_optimized_report.json`：完整資料（每一處殘留、不透明條件、改名對照）

| 步驟 | 做了什麼 | 結果 |
|---|---|---|
| 1. 還原反編譯殘留 | `_G["table.create"]` → `table.create`、`_G["bit32.bxor"]` → `bit32.bxor`、`up3;(` → `up3(`，並補回解密器被弄壞的 4 位元組拆分 | 2,739 處；整份檔案第一次能被 Luau 解析器完整解析 |
| 2. 不透明條件 | 列出全部 133 處 `V = not not C`，以及照字面解讀不會執行的程式碼，並判斷那段程式碼像陷阱還是像真實邏輯 | **只列報告，不刪除**（原因見 analysis.md 第 13 節） |
| 3. 自動改名 | 依程式碼本身的線索替 `vN` / `tN` / `fN` 取名，例如 `Instance.new("UICorner")` → `uiCorner`、`:Connect(f)` → `onRenderStepped`、`{ Label = "Auto Save" }` → `autoSaveToggle`、`Trove.new("a.KillFeed")` → `KillFeed`；反編譯器倒出的獨立原型沿用內嵌副本的名稱（`_proto` 尾碼）；載入器裡的第二份模組程式碼沿用已命名函式的名稱 | 38,046 個名稱；不動 Luarmor 的執行環境與載入器序段 |
| 4. 手動改名 | 讀過程式碼後寫在 `names.json` 的名稱，涵蓋 `f297` 到 `f9797` 共 27 個模組；最後的 `f10149` 由自動規則沿用這些名稱 | 24,338 個名稱；`_skip` 列出的躲避偵測與腳本保護程式碼刻意不命名（見 analysis.md 第 16 節） |

`luau-tool` 是用 [full-moon](https://crates.io/crates/full_moon)（Luau 解析器）寫的小工具，提供 `check`（語法檢查）、`predicates`（不透明條件分析）、`resolve`（作用域解析）三個子命令。Python 只套用它回傳的位元組範圍修改，所以沒改到的地方格式完全不變。

`-n/--names` 可以指定其他對照表（預設 `names.json`）。改名完成後會重新解析整份檔案，確認每一個變數引用指向的宣告都和改名前相同；如果有任何不同，就不會寫出檔案。

**注意：這份檔案是反編譯器把各個函式原型分別倒出來的結果，`up0`–`up101` 這些上值從來沒有被宣告，所以無法直接執行。** 詳見 analysis.md 第 12 節。

## 測試

```bash
python3 -m unittest test_deobfuscator test_optimize   # test_optimize 的部分測試需要先建置 luau-tool
```

## 檔案

```
deobfuscator/
├── deobfuscator.py                  第一階段：字串解密
├── optimize.py                      第二階段：可讀性優化
├── names.json                       手動改名對照表
├── luau-tool/                       Rust 輔助工具（語法檢查、條件分析、作用域解析）
├── test_deobfuscator.py             第一階段的測試
├── test_optimize.py                 第二階段的測試
├── analysis.md                      完整逆向分析與解謎過程
├── kicia_deobfuscated.lua           第一階段輸出
├── kicia_deobfuscated_strings.json  字串對照表
├── kicia_optimized.lua              第二階段輸出
├── kicia_optimized_report.md        第二階段報告
├── kicia_optimized_report.json      第二階段完整資料
└── README.md                        本檔案
```

## 需求

- 第一階段：Python 3.8 以上，不需要其他套件。安裝 `lupa`（`pip install lupa`）後，還會多做一次 Lua 5.4 的字面值檢查。
- 第二階段：另外需要 Rust（建置 `luau-tool`）。
