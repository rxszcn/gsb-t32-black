# t 前缀模板字符串被当成文档字符串：现状说明

复现脚本：`repro/tstring-docstring-positions.py`，用 `.venv/bin/python repro/tstring-docstring-positions.py` 运行。
环境：Python 3.14.4，black 0.1.dev1+gb618da9d7。下面四组输出是逐行照抄的实测结果。

## 一、四组实测结果（原样照抄）

### 1) 模块开头一句字符串：会不会被补空行（补了 = 按文档字符串处理）

```
"    补空行 = True
f"   补空行 = False
b"   补空行 = False
t"   补空行 = True
rt"  补空行 = True
u"   补空行 = True
```

无前缀、`u`、`t`、`rt` 都被补空行（按文档字符串处理）；`f`、`b` 不补。

### 2) 函数体第一句是跨行字符串：里面那行的缩进会不会被挪

```
t 前缀 输出与输入逐字节相同 = False | 输出第三行: '    第二行 {x}'
f 前缀 输出与输入逐字节相同 = True | 输出第三行: '        第二行 {x}'
```

输入里第二行是 8 空格缩进；t 前缀的输出被改成 4 空格（字符串字面内容被改），f 前缀的输出与输入逐字节相同。

### 3) 类体第一句

```
"    补空行 = True
f"   补空行 = False
t"   补空行 = True
```

### 4) 走整文件那条带安全检查的路（相当于命令行默认档位）

```
t 前缀 + 安全档 -> 抛 ASTSafetyError INTERNAL ERROR: Black 0.1.dev1+gb618da9d7 on Python (CPython
t 前缀 + 跳过检查 -> 通过，产出第三行: '    第二行 {x}'
f 前缀 + 安全档 -> 什么都没改
```

默认档位（`fast=False`，即命令行默认）直接抛 `ASTSafetyError`（命令行上表现为 INTERNAL ERROR）；加跳过安全检查的开关（`fast=True`，对应 `--fast`）才过得去，且放行的就是内容已被改动的结果。CI 上有人加这个开关，绕过的正是这道检查。

## 二、那处判定按什么规则排除前缀

判定在 `src/black/nodes.py:574` 的 `is_docstring()`。对字符串叶子节点，它先取前缀再做排除：

- `src/black/nodes.py:580`：`if set(prefix).intersection("bBfF"): return False` —— 排除清单是写死的字符集合 `bBfF`，只挡字节串和 f 字符串两档。
- 前缀本身由 `get_string_prefix()`（`src/black/strings.py:89`）按 `STRING_PREFIX_CHARS = "fturbFTURB"`（`src/black/strings.py:14`）切出来，`t`/`T` 早就进了合法前缀字符表，所以 `t"..."`、`rt"..."` 能被正确识别出前缀——但识别出来之后，排除清单里没有 `tT`，于是继续往下走位置判断（模块/类/函数体第一句），命中就返回 True。

为什么 f 挡住了而 t 没挡住：纯粹是排除清单枚举了 `fF` 而漏了 `tT`。`t` 被加进 `STRING_PREFIX_CHARS`（让切前缀、引号规范化这些通用逻辑认识它），但 `is_docstring` 的排除集合没有同步更新。两者机制上没有任何区别——f 字符串和 t 字符串在运行时都不是 `str` 常量、都不会成为 `__doc__`，只是一个在清单里一个不在。

## 三、这条现状凭什么能一路走到内容被改动

1. 入口放行：`is_docstring()` 对 t 前缀返回 True 后，`visit_STRING()`（`src/black/linegen.py:471`）把它当文档字符串处理，跨行时走 `fix_multiline_docstring()`（`src/black/strings.py:66`）。这个函数按 PEP 257 的规则求"除首行外的最小缩进"并整体去缩进、再按当前深度重新加缩进——对真文档字符串这是无害的排版，对 t 字符串这是直接改字面量内容（实测第二行从 8 空格变 4 空格）。
2. 空行同理：`src/black/lines.py:922` 依据 `is_docstring` 给文档字符串块后面补空行，所以模块/类开头的 t 字符串后面多出空行（第 1、3 组）。
3. 安全检查对不上号：`src/black/parsing.py:241` 的 AST 对比里，"独立字符串可能被重排缩进"的宽容归一化只覆盖 `ast.Constant` 且父节点是 `ast.Expr` 的情形——也就是真文档字符串在 AST 里的形态。t 字符串在 AST 里是 `TemplateStr`（插值部分是 `Interpolation` 节点），不是 `Constant`，归一化不适用；于是第 2 组那种缩进改动在对比中原样暴露，默认档位抛 `ASTSafetyError`。
4. 跳过检查就放行了改动：`fast=True`（`--fast`）跳过整道 AST 等价性检查，被改掉内容的输出直接通过。也就是说：判定漏排除 → 内容被改 → 唯一的兜底检查因为 AST 节点类型对不上而误报内部错误 → 加开关跳过检查后，错误结果一路绿灯。

## 四、主张的原则

只有解释器真的会当作 `__doc__` 收下的字符串才应按文档字符串处理：即求值结果是 `str` 常量的前缀——无前缀、`u`、`r`（及 `r`/`u` 与大小写组合）。凡是求值结果不是 `str` 或根本不会成为 `__doc__` 的前缀，一律排除：`b`（bytes）、`f`（JoinedStr，运行时不求值为普通 str）、`t`（TemplateStr，求值结果是 `string.Template`）。换句话说，`is_docstring` 的排除集合应当与"运行时不会成为文档字符串"对齐，把 `tT` 补进现有的 `bBfF`，而不是等每个下游各自兜底。

最小输入对照（各是什么结果）：

- 模块顶 `t"文档"\nx = 1` → 现状：被补空行（误判为文档字符串）；按原则：不应补。
- 模块顶 `f"文档"\nx = 1` → 不补空行（正确，f 在排除清单里）。
- 模块顶 `"文档"\nx = 1` → 补空行（正确，真文档字符串）。
- 函数体首句跨行 `t"""..."""` → 现状：内部行被重排缩进、默认档位抛 `ASTSafetyError`、`--fast` 放行改动；按原则：应逐字节保持原样（如同 f 前缀现状）。
