"""Expression parsing utilities for mqtt2influxdb."""

import py_expression_eval


class ExpressionError(ValueError):
    """Error parsing mathematical expression."""

    pass


def jsonpath_to_variable(path: str) -> str:
    """Convert JSONPath ($.) to valid expression variable (JSON__).

    Args:
        path: JSONPath expression starting with $.

    Returns:
        Valid expression variable name.
    """
    return path.replace("$", "JSON_").replace(".", "_")


def variable_to_jsonpath(var) -> str:
    """Convert expression variable back to JSONPath.

    Args:
        var: Expression variable (either string or object with .var attribute).

    Returns:
        JSONPath expression starting with $.
    """
    name = var.var if hasattr(var, "var") else str(var)
    return name.replace("JSON_", "$").replace("_", ".")


def parse_expression(text: str) -> py_expression_eval.Expression:
    """Parse expression string into evaluable expression.

    Args:
        text: Expression string, optionally starting with =.

    Returns:
        Parsed expression object.

    Raises:
        ExpressionError: If expression cannot be parsed.
    """
    try:
        # Remove leading = sign
        text = text.lstrip("=").strip()
        return py_expression_eval.Parser().parse(jsonpath_to_variable(text))
    except Exception as e:
        raise ExpressionError(f"Invalid expression: {text}") from e
