"""Expression parsing utilities for mqtt2influxdb."""

import re

import py_expression_eval


class ExpressionError(ValueError):
    """Error parsing mathematical expression."""

    pass


# Regex to match array bracket notation like [0], [1], etc.
BRACKET_REGEX = re.compile(r"\[(\d+)\]")


def jsonpath_to_variable(path: str) -> str:
    """Convert JSONPath ($.) to valid expression variable (JSON__).

    Handles array bracket notation by converting [n] to _n_.
    Example: $.topic[1] -> JSON__topic_1_

    Args:
        path: JSONPath expression starting with $.

    Returns:
        Valid expression variable name.
    """
    # First convert brackets [n] to _n_ to avoid parser confusion
    result = BRACKET_REGEX.sub(r"_\1_", path)
    # Then do the standard replacements
    return result.replace("$", "JSON_").replace(".", "_")


def variable_to_jsonpath(var) -> str:
    """Convert expression variable back to JSONPath.

    Reverses the conversion done by jsonpath_to_variable.
    Example: JSON__topic_1_ -> $.topic[1]

    Args:
        var: Expression variable (either string or object with .var attribute).

    Returns:
        JSONPath expression starting with $.
    """
    name = var.var if hasattr(var, "var") else str(var)
    # First do standard replacements
    result = name.replace("JSON_", "$").replace("_", ".")
    # Then convert back _n_ patterns to [n] (now they are .n.)
    result = re.sub(r"\.(\d+)\.", r"[\1]", result)
    return result


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
