# 复现：模板字符串（t 前缀）被当成文档字符串的三种现场，以及带安全检查那条路的答复
import black
from black import Mode, format_str

print("=== 1) 模块开头一句字符串：会不会被补空行（补了=按文档字符串处理）")
for pre in ('"', 'f"', 'b"', 't"', 'rt"', 'u"'):
    body = '文档 {x}"' if pre in ('f"', 't"', 'rt"') else '文档"'
    src = pre + body + "\nx = 1\n"
    out = format_str(src, mode=Mode())
    print("   ", pre.ljust(4), "补空行 =", out.count("\n") > src.count("\n"))

print("=== 2) 函数体第一句是跨行字符串：里面那行的缩进会不会被挪")
t = 'def f():\n    t"""第一行\n        第二行 {x}\n    """\n    return 1\n'
ft = 'def f():\n    f"""第一行\n        第二行 {x}\n    """\n    return 1\n'
for name, src in (("t 前缀", t), ("f 前缀", ft)):
    out = format_str(src, mode=Mode())
    print("   ", name, "输出与输入逐字节相同 =", out == src, "| 输出第三行:", repr(out.splitlines()[2]))

print("=== 3) 类体第一句")
for pre in ('"', 'f"', 't"'):
    src = "class A:\n    " + pre + '文档"\n    x = 1\n'
    out = format_str(src, mode=Mode())
    print("   ", pre.ljust(4), "补空行 =", out.count("\n") > src.count("\n"))

print("=== 4) 走整文件那条带安全检查的路（相当于命令行默认档位）")
for name, src, fast in (("t 前缀 + 安全档", t, False), ("t 前缀 + 跳过检查", t, True),
                        ("f 前缀 + 安全档", ft, False)):
    try:
        out = black.format_file_contents(src, fast=fast, mode=Mode())
        print("   ", name, "-> 通过，产出第三行:", repr(out.splitlines()[2]))
    except black.NothingChanged:
        print("   ", name, "-> 什么都没改")
    except Exception as e:
        print("   ", name, "-> 抛", type(e).__name__, str(e)[:60])
