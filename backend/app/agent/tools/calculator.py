"""Calculator tool — sympy + keyword blacklist.

Contract (PLAN.md §3.3):
  success -> {result: str, latex: str}
  failure -> {error: "forbidden_keyword" | "syntax_error" | "evaluation_error"}
"""

import sympy
from langchain_core.tools import tool

#: Keywords that must never reach sympy's evaluator.
FORBIDDEN_KEYWORDS = (
    "__",
    "import",
    "os",
    "sys",
    "exec",
    "eval(",
    "open(",
    "subprocess",
    "lambda",
    ";",
    "\n",
)

#: Namespace exposed to sympy during evaluation — deliberately minimal.
SAFE_NAMESPACE = {
    "sqrt": sympy.sqrt,
    "pi": sympy.pi,
    "E": sympy.E,
    "I": sympy.I,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "log": sympy.log,
    "exp": sympy.exp,
    "Abs": sympy.Abs,
}


def _format_result(expr: sympy.Expr) -> str:
    """Render the evaluated expression as a short human-readable string."""
    if expr.is_Integer:
        return str(int(expr))
    if expr.is_number:
        return str(float(expr.evalf()))
    return str(expr)


@tool
def calculate(expression: str) -> dict:
    """Evaluate a mathematical expression and return the result.

    Args:
        expression: A math expression, e.g. "2+2*3" or "sqrt(2)".
    """
    expression = (expression or "").strip()
    if not expression:
        return {"error": "syntax_error"}

    lowered = expression.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in lowered:
            return {"error": "forbidden_keyword"}

    try:
        expr = sympy.sympify(expression, evaluate=True, locals=SAFE_NAMESPACE)
    except (sympy.SympifyError, SyntaxError, TypeError, ValueError):
        return {"error": "syntax_error"}
    except Exception:
        return {"error": "evaluation_error"}

    if not isinstance(expr, sympy.Expr):
        return {"error": "syntax_error"}

    try:
        value = expr.evalf()
    except (TypeError, ValueError, ZeroDivisionError):
        return {"error": "evaluation_error"}
    except Exception:
        return {"error": "evaluation_error"}

    if value.has(sympy.zoo) or value.has(sympy.nan) or value.has(sympy.oo):
        return {"error": "evaluation_error"}

    try:
        return {"result": _format_result(expr), "latex": sympy.latex(expr)}
    except Exception:
        return {"error": "evaluation_error"}
