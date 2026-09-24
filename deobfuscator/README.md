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

## 測試

```bash
python3 -m unittest test_deobfuscator
```

## 檔案

```
deobfuscator/
├── deobfuscator.py                  主程式
├── test_deobfuscator.py             單元測試
├── analysis.md                      完整逆向分析與解謎過程
├── kicia_deobfuscated.lua           輸出
├── kicia_deobfuscated_strings.json  字串對照表
└── README.md                        本檔案
```

## 需求

Python 3.8 以上，不需要其他套件。安裝 `lupa`（`pip install lupa`）後，還會多做一次 Lua 5.4 的字面值檢查。
