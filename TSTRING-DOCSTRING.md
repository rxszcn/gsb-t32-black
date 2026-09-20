# t 前缀字符串被误判为文档字符串：现状记录

环境：仓库当前源码，Python 3.14.4，`.venv/bin/python repro/tstring-docstring-positions.py`
（另需构建期生成的 `src/_black_version.py`，该文件在 `.gitignore` 内，不属于仓库代码）。

## 一、复现脚本的四组原始读数

以下输出逐字照抄，未作任何改动：

```
=== 1) 模块开头一句字符串：会不会被补空行（补了=按文档字符串处理）
    "    补空行 = True
    f"   补空行 = False
    b"   补空行 = False
    t"   补空行 = True
    rt"  补空行 = True
    u"   补空行 = True

=== 2) 函数体第一句是跨行字符串：里面那行的缩进会不会被挪
    t 前缀 输出与输入逐字节相同 = False | 输出第三行: '    第二行 {x}'
    f 前缀 输出与输入逐字节相同 = True | 输出第三行: '        第二行 {x}'

=== 3) 类体第一句
    "    补空行 = True
    f"   补空行 = False
    t"   补空行 = True

=== 4) 走整文件那条带安全检查的路（相当于命令行默认档位）
    t 前缀 + 安全档 -> 抛 ASTSafetyError INTERNAL ERROR: Black 26.0.0.dev0 on Python (CPython) 3.14.4
    t 前缀 + 跳过检查 -> 通过，产出第三行: '    第二行 {x}'
    f 前缀 + 安全档 -> 什么都没改
```

读法小结：

- 第 1、3 组：会被补空行（即被当成文档字符串）的前缀是 `"`（无前缀）、`t"`、`rt"`、`u"`；
  不补空行的是 `f"` 和 `b"`。
- 第 2 组：跨行 `t` 字符串的第二行由 8 个空格被挪成 4 个空格，模板的文本内容被改写；
  同样位置的 `f` 字符串逐字节不变。
- 第 4 组：默认（安全）档对 `t` 前缀抛 `ASTSafetyError`，打印的是
  `INTERNAL ERROR: Black 26.0.0.dev0 on Python (CPython) 3.14.4 ...`
  并附带一个 diff 日志路径；`fast=True`（对应命令行 `--fast`，跳过安全检查）时不报错，
  直接产出内容已被改动的结果；`f` 前缀在安全档下是 `NothingChanged`（脚本显示"什么都没改"）。

## 二、判定规则：前缀是怎么被排除的

入口在 `src/black/nodes.py` 的 `is_docstring`：

```python
def is_docstring(node: NL) -> bool:
    if isinstance(node, Leaf):
        if node.type != token.STRING:
            return False

        prefix = get_string_prefix(node.value)
        if set(prefix).intersection("bBfF"):
            return False
    ...
```

前缀由 `src/black/strings.py` 的 `get_string_prefix` 取：逐字符消费
`STRING_PREFIX_CHARS = "fturbFTURB"`，直到遇到引号为止。因此 `rt"` 得到 `"rt"`，
`u"` 得到 `"u"`，等等。

排除集只有 `"bBfF"` 四个字符，即：

- `b`/`B`：bytes 字面量，Python 语言里不可能是文档字符串（对应
  `tests/data/cases/bytes_docstring.py` 这批老用例）；
- `f`/`F`：f 字符串，求值得到的是插值后的 str，同样不是文档字符串。

这个函数要判断的其实是"这个字符串语句在语法位置上是不是文档字符串"，而 Python
语言对文档字符串的定义（`ast.get_docstring` 遵循的规则）是：模块、类或函数体
第一条语句，且必须是一个 **纯字符串常量表达式**。用 3.14 的标准库实测：

| 前缀 | `ast.get_docstring` 是否认作文档字符串 |
| --- | --- |
| 无前缀、`r`、`u` | 是 |
| `f`、`b`、`t`、`rt` | 否 |

所以正确的排除集合应当是"所有使字面量不再是纯 str 常量的前缀"：`b/B`（bytes）、
`f/F`（插值）、`t/T`（模板，可与 `r` 组合成 `rt`/`tr`，同样不是常量）。

## 三、为什么 f 挡住了，t 没挡住

`is_docstring` 里这份黑名单写于只有 bytes 和 f-string 需要排除的年代。PEP 750
给 3.14 引入 `t` 前缀时，字符串词法这一侧（`STRING_PREFIX_CHARS`、t-string 的
换行/插值处理）加了支持，但这处"谁不算文档字符串"的判定没有同步更新：

- `f"..."` 的前缀里含 `f`，与 `"bBfF"` 相交，第 580 行直接 `return False`，
  后面的文档字符串处理一条都走不到；
- `t"..."` 的前缀是 `t`（或 `rt`），不含 `b/B/f/F` 任何一个字符，于是判定继续
  往下走。而它所在的语法位置（`file_input` 下第一条 `simple_stmt`，或
  NEWLINE/INDENT 之后函数体、类体的第一条 `simple_stmt`）与真正的文档字符串
  完全相同，函数最终返回 `True`。

也就是说：**挡住 f 的不是"它会插值"这条语义，而仅仅是一张少了 `tT` 的字符黑名单。**

## 四、误判之后，内容为什么能真的被改掉

被判成文档字符串后，下游有两处按文档字符串整形，都假设字符串是一个静态的 str：

1. 空行。`src/black/lines.py` 中 `Line.is_docstring` 与
   `_line_is_module_docstring` / `_maybe_empty_lines` 会在模块级文档字符串之后
   补两个空行、在类体文档字符串之后补一个空行。第 1、3 组看到的"多空行"就是
   这里产生的——纯排版，语义无害，但位置已经错了。

2. 跨行内容重排，这一条会改语义。`src/black/linegen.py` 的 `visit_STRING`
   对 `is_docstring(leaf)` 的字面量调用 `src/black/strings.py` 的
   `fix_multiline_docstring`：它按 PEP 257 的算法求正文各行（首行除外）的最小
   缩进，全部剥掉，再按语法深度重新补 `4 * depth` 个空格。对真正的文档字符串，
   这只是改"常量的排版"，Python 语义上字符串仍是同一个语句的值；但模板字符串
   里的空白是 **模板文本的一部分**，第二行从 8 空格变成 4 空格，运行时
   `TemplateStr.values` 里 `Constant('第一行\n        第二行 ')` 就变成了
   `Constant('第一行\n    第二行 ')`，求值结果随之不同。第 2 组的逐字节比较
   `False` 就是这个改动。

3.14 的 AST 里，t 字符串解析为 `ast.TemplateStr(values=[Constant(...),
Interpolation(...), ...])`，而不是一个 `Expr` 包着的 `Constant`。安全检查
（`src/black/parsing.py` 的 `_stringify_ast`）对文档字符串缩进差异本来有一条
专门的豁免：父节点是 `ast.Expr` 的 `Constant(value: str)` 比较时会折叠换行
周边空白——这条豁免只覆盖普通文档字符串。t 字符串的静态片段是 `TemplateStr`
内部的嵌套 `Constant`，不满足豁免条件，于是改动如实体现在 AST 差异里，
`assert_equivalent` 判定源码与产物不等价，默认档抛出 `ASTSafetyError`
（第 4 组第一条）。

这条现状能一路走到"内容被改动"，靠的是两层放行叠加：

- `black.format_str(...)`（以及第 1、2、3 组走的路径）根本不做 AST 等价性
  校验，错误判定直接变成错误产物；
- `black.format_file_contents(..., fast=True)` / 命令行 `--fast` 显式关掉
  唯一能拦住它的安全检查（`assert_equivalent`），于是 CI 上加 `--fast` 后，
  语义已变的代码会被当作"格式化成功"写回磁盘。安全档抛错是最后一道防线，
  但它只能让任务失败，并不能阻止 `--fast` 或库 API 用户拿到被改写的模板。

## 五、主张的原则

**"按文档字符串对待"的判据应当与 Python 语言保持一致：只有求值结果是纯
str 常量的字面量，才允许走文档字符串整形。** 具体地，`is_docstring` 的前缀
排除集应从 `"bBfF"` 扩成覆盖所有非纯 str 常量的前缀，即把 `t/T` 纳入
（`rt`/`tr` 因含 `t` 自然被排除）；无前缀、`r/R`、`u/U` 仍是合法文档字符串，
继续按现状处理。判定应由"黑名单"改为按语言事实回答"它是不是常量 str
表达式"，这样以后再增加带语义的前缀时不会重蹈。

最小输入（函数体第一句，跨行）：

```python
def f():
    P"""第一行
        第二行 {x}
    """
    return 1
```

把 `P` 分别换成各前缀，当前源码下的实际结果：

| 前缀 | 当前是否按文档字符串整形 | `--fast`（跳过检查）结果 | 默认安全档结果 |
| --- | --- | --- | --- |
| 无、`r`、`u` | 是（符合语言定义，正确） | 第二行规整为 4 空格，语义等价 | 通过 |
| `f`、`b` | 否（黑名单挡住，正确） | 什么都没改，逐字节不变 | 什么都没改 |
| `t`、`rt` | **误判为是** | 第二行 8 空格被改成 4 空格，模板内容被改写 | `ASTSafetyError`（内部错误） |

按上述原则修复后，`t`/`rt` 两行应当与 `f`/`b` 完全一致：不补空行、不动正文、
安全档与 `--fast` 下均逐字节不变。
