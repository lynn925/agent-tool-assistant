"""计算器工具 —— sympy 求值 + 关键字黑名单。

对应 PLAN.md §3.3 的契约：
  成功 -> {result: str, latex: str}
  失败 -> {error: "forbidden_keyword" | "syntax_error" | "evaluation_error"}

安全上有两道防线，缺一不可：
  1. 黑名单：把 import / exec / open 这类危险词直接挡在门外；
  2. 白名单：sympy 求值时只能看到 SAFE_NAMESPACE 里的十几个数学符号。
"""

import sympy
from langchain_core.tools import tool

#: 危险关键字黑名单。命中任意一个就直接拒绝，不进入求值环节。
#: 注意这里做的是"子串包含"判断，所以 "__" 能同时拦住 __import__、__class__ 等。
FORBIDDEN_KEYWORDS = (
    "__",  # 双下划线魔术方法（__import__ / __globals__ 等）
    "import",  # import 语句
    "os",  # os 模块（注意它也会误伤含 "os" 的普通词）
    "sys",  # sys 模块
    "exec",  # exec() 执行任意代码
    "eval(",  # eval() 求值
    "open(",  # open() 读写文件
    "subprocess",  # 子进程调用
    "lambda",  # lambda 表达式（sympy 不需要它）
    ";",  # 分号（一条语句里塞多行代码）
    "\n",  # 换行（同上）
)

#: sympy 求值时可访问的符号白名单 —— 只有这些数学函数和常数。
#: 传 locals 给 sympify，就等于限定了它能看到的命名空间。
SAFE_NAMESPACE = {
    "sqrt": sympy.sqrt,  # 平方根
    "pi": sympy.pi,  # 圆周率
    "E": sympy.E,  # 自然常数
    "I": sympy.I,  # 虚数单位
    "sin": sympy.sin,  # 正弦
    "cos": sympy.cos,  # 余弦
    "tan": sympy.tan,  # 正切
    "log": sympy.log,  # 对数
    "exp": sympy.exp,  # 指数
    "Abs": sympy.Abs,  # 绝对值
}


def _format_result(expr: sympy.Expr) -> str:
    """把求值结果渲染成简短易读的字符串。

    先判断是不是整数 —— 是的话输出 "8" 而不是 "8.0"，更符合直觉。
    """
    if expr.is_Integer:
        return str(int(expr))
    if expr.is_number:
        return str(float(expr.evalf()))
    # 不是具体数值（比如 x**2），就返回符号形式本身
    return str(expr)


@tool
def calculate(expression: str) -> dict:
    """计算一个数学表达式并返回结果。

    Args:
        expression: 数学表达式，例如 "2+2*3" 或 "sqrt(2)"。
    """
    expression = (expression or "").strip()
    if not expression:
        return {"error": "syntax_error"}

    # 第一道防线：黑名单预过滤。先转小写，这样 "IMPORT" 也能拦住。
    lowered = expression.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in lowered:
            return {"error": "forbidden_keyword"}

    # 第二道防线：白名单求值。locals 参数限制了 sympy 能看到的符号。
    try:
        expr = sympy.sympify(expression, evaluate=True, locals=SAFE_NAMESPACE)
    except (sympy.SympifyError, SyntaxError, TypeError, ValueError):
        # 表达式本身写错了，比如 "2++"
        return {"error": "syntax_error"}
    except Exception:
        return {"error": "evaluation_error"}

    # sympify 有可能返回非表达式对象（比如纯数字），这里挡一下
    if not isinstance(expr, sympy.Expr):
        return {"error": "syntax_error"}

    # 求值：1/0 会在这一步变成 zoo（无穷大）
    try:
        value = expr.evalf()
    except (TypeError, ValueError, ZeroDivisionError):
        return {"error": "evaluation_error"}
    except Exception:
        return {"error": "evaluation_error"}

    # 无穷、NaN 这类结果不算有效答案
    if value.has(sympy.zoo) or value.has(sympy.nan) or value.has(sympy.oo):
        return {"error": "evaluation_error"}

    try:
        return {"result": _format_result(expr), "latex": sympy.latex(expr)}
    except Exception:
        return {"error": "evaluation_error"}
