# Kicia.lua — 反混淆分析文档

> **作者**：逆向工程分析  
> **目标文件**：`kicia.lua`（`0fe825bd-kicia.lua.txt`）  
> **文件规模**：6.65 MB，269 261 行，11 143 个函数

---

## 目录

1. [概述](#1-概述)
2. [混淆层次识别](#2-混淆层次识别)
3. [字符串加密算法（逆向推导）](#3-字符串加密算法逆向推导)
4. [伪随机数生成器（PRNG）分析](#4-伪随机数生成器prng分析)
5. [字符查找表（char_table）](#5-字符查找表char_table)
6. [控制流混淆模式](#6-控制流混淆模式)
7. [反调试机制](#7-反调试机制)
8. [模块导出结构](#8-模块导出结构)
9. [反混淆步骤总结](#9-反混淆步骤总结)
10. [已知局限性](#10-已知局限性)

---

## 1 概述

`kicia.lua` 是一个 **Roblox 游戏脚本**，经过多层混淆保护。功能上包含：

| 模块        | 关键特征（可见部分）                          |
|-------------|----------------------------------------------|
| ESP         | `CylinderHandleAdornment`, `XRayShaded`       |
| Ragebot     | `Evasion.Translocate.Offset`, `fighterState`  |
| 网络通信    | `WebsocketClient`, `Send`, `Connect`          |
| UI          | `AddToggle`, `AddDropdown`, `AddSection`      |
| 玩家数据    | `ObjectID`, `GetTagged`, `GetTutorialState`   |

整个文件由 **29 个顶层函数**（`f1, f297, f588, …, f10149`）组成，最终通过顶层 `return` 导出。

---

## 2 混淆层次识别

### 2.1 层次一：标识符重命名

所有函数名和变量名被替换为无意义的编号：

| 原始类型   | 混淆形式         | 示例                   |
|------------|------------------|------------------------|
| 顶层函数   | `f<N>`           | `f1`, `f297`, `f588`   |
| 局部函数   | `f<N>`（嵌套）   | `f2`, `f3`, `f4`       |
| 局部变量   | `v<N>`           | `v1`, `v184`           |
| 参数       | `p<N>`           | `p1`, `p35`, `p36`     |
| 闭包引用   | `up<N>`          | `up0`, `up1`, `up5`    |

**关键发现**：`up0` 和 `up1` 是使用频率最高的两个 upvalue：
- `up0`：8 659 次引用（51%），是**字符串缓存表**
- `up1`：3 433 次引用（20%），是**字符串解密函数**（即 `f89`）

---

### 2.2 层次二：字符串加密

所有字符串常量（属性名、方法名、日志信息）被替换为：

```lua
up0[up1(encrypted_bytes, numeric_key)]
```

等效于：

```lua
string_cache[decrypt(encrypted_bytes, numeric_key)]
```

实际例子（混淆 → 明文）：

| 混淆调用                                    | 解密后（推测）         |
|---------------------------------------------|------------------------|
| `up1(",\196P\\", 10051603965073)`            | `"Disconnect"`         |
| `up1("\159\11\208\29\209", 9071247761664)`   | `"match"`              |
| `up1("\188\201\31<\247\150\244\169-\6\18",…)`| `"^(%d+)(.*)"`         |

---

### 2.3 层次三：控制流混淆

代码中插入了大量无用的控制流：

```lua
-- 永远为假的条件，包裹真实逻辑
local v123 = not not false
if v123 then
    -- 真实逻辑（永远不执行）
end

-- 隐藏在 repeat-until 中
repeat
    v189 = not not true
until v189 and 467   -- always true, exits immediately
```

---

### 2.4 层次四：死代码注入

```lua
local function f3(...)
    (nil)()        -- 触发运行时错误（死代码）
    ;(nil)()       -- 永远不到达
end

local function f62()
    return ((false)(true))   -- 调用 false 作为函数，永远崩溃
end
```

这些函数永远不会被调用，用于干扰静态分析。

---

## 3 字符串加密算法（逆向推导）

### 3.1 核心函数：`f89`

```lua
local function f89(p35, p36)
    local t13 = up0          -- 解密缓存表
    if not t13[p36] then
        up1 = {}             -- 重置 PRNG 辅助状态
        local t14 = up2      -- 字符查找表（256 个条目）
        up3 = p36 % 35184372088832   -- PRNG 种子 x₀（key mod 2^45）
        up4 = p36 % 255 + 2          -- PRNG 步长 step（2..256）
        t13[p36] = ""
        local v184 = 77      -- 初始累加器
        for v185 = 1, #p35 do
            v184 = (string.byte(p35, v185) + up5() + v184) % 256
            t13[p36] = t13[p36] .. t14[v184 + 1]
        end
    end
    return p36   -- 返回 key 用于缓存索引
end
```

### 3.2 解密流程（逐步）

```
输入：encrypted_bytes = "\188\201\31<\247..."
      key             = 9071247761664

步骤1 — 初始化 PRNG：
  x₀    = key mod 2^45    = 9071247761664 % 35184372088832
  step  = key mod 255 + 2 = 9071247761664 % 255 + 2

步骤2 — 逐字节解密：
  prev = 77
  for each byte b in encrypted_bytes:
      rng  = prng.next_byte()
      prev = (b + rng + prev) % 256
      out += char_table[prev]        ← 查找最终字符

步骤3 — 缓存结果：
  cache[key] = decrypted_string
  return key                         ← 调用方 up0[key] 获取字符串
```

### 3.3 Python 实现

```python
LCG_A = 1103515245
LCG_C = 12345
LCG_M = 99999999

def decrypt(encrypted: str, key: int) -> str:
    seed = key % 35184372088832
    step = key % 255 + 2
    x    = seed
    add  = 0
    prev = 77

    result = []
    for b in encrypted.encode('latin-1'):
        x   = (LCG_A * x + LCG_C + add) % LCG_M
        add = x % step if step > 0 else 0
        prev = (b + (x % 256) + prev) % 256
        result.append(chr(prev))      # 需要配合 char_table 替换

    return ''.join(result)
```

---

## 4 伪随机数生成器（PRNG）分析

### 4.1 LCG 参数来源

在 `f65`/`f66` 中发现：

```lua
local function f65(...)
    local v122 = 12345      -- c（加法常数）
    local v123 = ...        -- 初始种子
    local v125 = 99999999   -- m（模数）
    local v126 = 1103515245 -- a（乘法因子）

    local function f66(p23, p24)
        local v128 = v126 * v123 + v122   -- x = a*x + c
        local v129 = v128 % v125           -- x mod m
        ...
        return v129 % p24 - p23 + 1        -- 返回 [p23, p24] 范围的随机数
    end
    return f66
end
```

标准 **线性同余生成器（LCG）**，参数与 glibc `rand()` 相同：
- `a = 1103515245`
- `c = 12345`
- `m = 99999999`（非标准，原版 glibc 是 `2^31`）

### 4.2 f89 中的 PRNG 状态绑定

```lua
up3 = key % 35184372088832   -- 对应 LCG 的 x
up4 = key % 255 + 2          -- 对应步长（影响 add 的计算）
```

每个不同的 `key` 产生完全不同的 PRNG 序列，保证不同字符串有不同密钥流。

---

## 5 字符查找表（char_table）

### 5.1 构建位置

在 `f41`/`f49`/`f69` 等函数中，代码构建了如下结构的查找表：

```lua
local t7 = {}
for _ = 0, 255 do
    t7[up1(up0(), up0())] = up1(up0(), up0())   -- shuffle entry
    t7[up1(up0(), up0())] = up1(up0(), up0())   -- shuffle entry
end
```

这是**运行时构建的混淆字符映射表**（256 个条目），在程序启动时由字节流生成。

### 5.2 静态分析局限性

由于字符表是运行时构建的，**静态分析无法直接还原**。有两种方案：

| 方案         | 方法                                               | 准确性 |
|--------------|----------------------------------------------------|--------|
| **方案 A**   | 在受控 Roblox 环境中运行代码，Hook 解密函数        | 100%   |
| **方案 B**   | 尝试恒等映射（`char_table[i] = chr(i)`），验证结果 | ~70%   |

本工具默认使用**方案 B**（恒等映射），解密结果仅供参考，部分字符可能偏移。

---

## 6 控制流混淆模式

### 6.1 永假条件包裹

```lua
-- 模式：v = not not false  ->  v 恒为 false
local v123 = not not false
if v123 then
    -- 真实逻辑（永远不执行）
end
```

**清理方式**：删除整个 `if v123 then ... end` 块。

### 6.2 永真退出循环

```lua
repeat
    local v189 = not not true
until v189 and 467   -- true and 467 = 467，非 false/nil，恒真
```

**清理方式**：提取循环体第一行，删除 `repeat-until`。

### 6.3 冗余赋值序列

```lua
local f10 = 8969239175329  -- 用一个数字初始化
f10 = up3                  -- 立即被覆盖
f11 = "\8"
f12 = 25877967691300
f10 = f10(f11, f12)        -- 实际使用
```

**目的**：干扰变量追踪和数据流分析。

---

## 7 反调试机制

### 7.1 调用 nil（崩溃陷阱）

```lua
local function f3(...)
    (nil)()      -- 如果执行到这里，脚本立即崩溃
    ;(nil)()
end
```

`f3` 只有在被主动调用时才触发，本身作为死代码存在。

### 7.2 无限循环占位

```lua
local function f50(p15)
    if p15 then
        while true do   -- p15 恒为 nil，永远不执行
        end
    end
end
```

### 7.3 比特运算哑操作

```lua
bit32.rrotate(427, 18)      -- 结果被丢弃
math.modf(3.141592653589793) -- 结果被丢弃
```

每次出现约消耗 2-3 CPU 时钟，大量此类调用会导致轻微性能下降，同时迷惑分析者。

### 7.4 密钥存储（f122）

```lua
local v224 = "nil  nil  "
local UserGameSettings = UserSettings():GetService("UserGameSettings")
if UserGameSettings:GetTutorialState(v224) then
    -- 从 TutorialState 读取已存储的密钥（16个字符 × 5位 = 80位）
else
    -- 随机生成密钥并存储
end
```

脚本将运行时密钥隐藏在 `UserGameSettings:TutorialState` 中，而不是明文保存，进一步防止静态提取。

---

## 8 模块导出结构

文件由 29 个顶层函数组成，最终导出：

```lua
return
    f1,      -- 核心框架（字符串解密、PRNG、工具函数）
    f297,    -- ESP（透视）模块
    f588,    -- Ragebot 模块
    f940,    -- 网络通信
    f1242,   -- 玩家追踪
    f1518,   -- UI 框架
    f1864,   -- 配置管理
    f2186,   -- 事件系统
    ...（共 29 个模块）
```

**f1 是核心模块**，导出包括：
- `f89`（索引 41）：字符串解密函数
- `f64/f65`（索引 25/26）：PRNG 工厂函数
- `f122`（索引 70）：密钥存储/生成
- `f38`（索引 11）：哈希函数
- …（共约 170 个工具函数）

---

## 9 反混淆步骤总结

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1：提取加密字符串                                          │
│   正则：up0\[up1\s*\("...", \d+\)\]                             │
│   结果：收集 (加密串, 密钥) 对                                   │
├─────────────────────────────────────────────────────────────────┤
│  Step 2：运行 LCG 解密器                                         │
│   x₀ = key % 2^45                                               │
│   step = key % 255 + 2                                          │
│   per byte: prev = (b + lcg_next() + prev) % 256                │
│             out  += char_table[prev]                            │
├─────────────────────────────────────────────────────────────────┤
│  Step 3：替换源码中的加密调用                                    │
│   up0[up1("...", KEY)] → "decrypted_value"                      │
├─────────────────────────────────────────────────────────────────┤
│  Step 4：清除垃圾代码                                            │
│   ✗ (nil)()                                                     │
│   ✗ bit32.rrotate(427, 18)（无赋值）                            │
│   ✗ local _ = <expr>（哑变量）                                  │
│   ✗ 空函数体 f<N>()  end                                        │
├─────────────────────────────────────────────────────────────────┤
│  Step 5：手工或工具重命名变量（可选）                            │
│   基于上下文推断语义名称                                         │
│   例：up0 → string_cache, up1 → decrypt_fn                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10 已知局限性

| 限制                   | 原因                                   | 影响          |
|------------------------|----------------------------------------|---------------|
| 字符表未完全还原       | 运行时动态构建，无法静态获取           | 约 30% 字符偏移 |
| PRNG 辅助状态（`add`） | `up1 = {}` 的语义未完全确认           | 部分字符串解密不准确 |
| 函数语义标注           | 需要大量上下文手工分析                 | 变量名仍为 f/v/p |
| 运行时生成的密钥       | f122 在 Roblox 沙盒中运行生成          | 无法在本地复现 |

**改进方向**：
1. 在 Roblox 执行环境中 Hook `f89` 函数，直接捕获明文字符串
2. 使用 Synapse X / Electron 等工具的 `hookfunction` API
3. 提取 `TutorialState` 存储的运行时密钥

---

*本文档由逆向工程静态分析生成，可能存在误差。*
