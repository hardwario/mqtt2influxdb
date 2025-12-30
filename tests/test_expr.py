"""Unit tests for expression parsing."""

import pytest

from mqtt2influxdb.expr import (
    ExpressionError,
    jsonpath_to_variable,
    parse_expression,
    variable_to_jsonpath,
)


class TestJsonpathToVariable:
    """Tests for JSONPath to variable conversion."""

    def test_simple_payload(self):
        """Test simple $.payload conversion."""
        result = jsonpath_to_variable("$.payload")
        assert result == "JSON__payload"

    def test_nested_path(self):
        """Test nested path conversion."""
        result = jsonpath_to_variable("$.payload.temperature")
        assert result == "JSON__payload_temperature"

    def test_topic_index(self):
        """Test topic index conversion (brackets converted to underscores)."""
        result = jsonpath_to_variable("$.topic[1]")
        assert result == "JSON__topic_1_"

    def test_deeply_nested(self):
        """Test deeply nested path."""
        result = jsonpath_to_variable("$.payload.data.sensor.value")
        assert result == "JSON__payload_data_sensor_value"


class TestVariableToJsonpath:
    """Tests for variable to JSONPath conversion."""

    def test_simple_variable(self):
        """Test simple variable conversion."""
        result = variable_to_jsonpath("JSON__payload")
        assert result == "$.payload"

    def test_nested_variable(self):
        """Test nested variable conversion."""
        result = variable_to_jsonpath("JSON__payload_temperature")
        assert result == "$.payload.temperature"

    def test_object_with_var_attribute(self):
        """Test object with .var attribute."""

        class MockVar:
            var = "JSON__payload_value"

        result = variable_to_jsonpath(MockVar())
        assert result == "$.payload.value"


class TestParseExpression:
    """Tests for expression parsing."""

    def test_simple_expression(self):
        """Test simple expression."""
        expr = parse_expression("= 1 + 2")
        result = expr.evaluate({})
        assert result == 3

    def test_expression_without_equals(self):
        """Test expression without leading equals sign."""
        expr = parse_expression("1 + 2")
        result = expr.evaluate({})
        assert result == 3

    def test_multiplication(self):
        """Test multiplication."""
        expr = parse_expression("= 5 * 3")
        result = expr.evaluate({})
        assert result == 15

    def test_division(self):
        """Test division."""
        expr = parse_expression("= 10 / 2")
        result = expr.evaluate({})
        assert result == 5.0

    def test_complex_expression(self):
        """Test complex expression with parentheses."""
        expr = parse_expression("= (2 + 3) * 4")
        result = expr.evaluate({})
        assert result == 20

    def test_celsius_to_fahrenheit(self):
        """Test Celsius to Fahrenheit conversion formula."""
        expr = parse_expression("= 32 + (JSON__payload * 9 / 5)")

        # 0°C = 32°F
        result = expr.evaluate({"JSON__payload": 0})
        assert result == 32

        # 100°C = 212°F
        result = expr.evaluate({"JSON__payload": 100})
        assert result == 212

        # 37°C = 98.6°F (body temperature)
        result = expr.evaluate({"JSON__payload": 37})
        assert abs(result - 98.6) < 0.01

    def test_expression_with_jsonpath_variable(self):
        """Test expression with JSONPath variable."""
        expr = parse_expression("= $.payload * 2")
        # Variable gets converted to JSON__payload
        result = expr.evaluate({"JSON__payload": 10})
        assert result == 20

    def test_expression_with_nested_variable(self):
        """Test expression with nested JSONPath variable."""
        expr = parse_expression("= $.payload.value + 100")
        result = expr.evaluate({"JSON__payload_value": 50})
        assert result == 150

    def test_expression_variables(self):
        """Test getting variables from expression."""
        expr = parse_expression("= $.payload + $.payload.offset")
        variables = expr.variables()
        assert "JSON__payload" in variables
        assert "JSON__payload_offset" in variables

    def test_invalid_expression(self):
        """Test invalid expression raises ExpressionError."""
        with pytest.raises(ExpressionError) as exc_info:
            parse_expression("= invalid (( syntax")
        assert "Invalid expression" in str(exc_info.value)

    def test_unbalanced_parentheses(self):
        """Test unbalanced parentheses raises error."""
        with pytest.raises(ExpressionError):
            parse_expression("= (1 + 2")

    def test_negative_numbers(self):
        """Test negative numbers in expression."""
        expr = parse_expression("= -5 + 10")
        result = expr.evaluate({})
        assert result == 5

    def test_decimal_in_variable(self):
        """Test decimal numbers work when part of variable values."""
        # Note: Literal decimals like "1.5" don't work directly because
        # jsonpath_to_variable converts . to _, but decimals work in variable values
        expr = parse_expression("= JSON__payload * 2")
        result = expr.evaluate({"JSON__payload": 1.5})
        assert result == 3.0

    def test_power_operation(self):
        """Test power operation."""
        expr = parse_expression("= 2 ^ 3")
        result = expr.evaluate({})
        assert result == 8

    def test_modulo_operation(self):
        """Test modulo operation."""
        expr = parse_expression("= 10 % 3")
        result = expr.evaluate({})
        assert result == 1

    def test_whitespace_handling(self):
        """Test expressions with extra whitespace."""
        expr = parse_expression("=   1   +   2   ")
        result = expr.evaluate({})
        assert result == 3
