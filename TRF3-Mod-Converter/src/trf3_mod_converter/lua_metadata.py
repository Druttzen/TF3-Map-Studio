"""Read static Lua metadata without executing a mod or its callbacks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from luaparser import ast
from luaparser import astnodes as lua


@dataclass(frozen=True)
class UnsupportedValue:
    reason: str


def _value(node: lua.Node) -> Any:
    if isinstance(node, lua.String):
        value = node.s.decode("utf-8")
        if node.delimiter == lua.StringDelimiter.DOUBLE_SQUARE:
            value = value.replace("\r\n", "\n").replace("\r", "\n")
            if value.startswith("\n"):
                value = value[1:]
        return value
    if isinstance(node, lua.Number):
        return node.n
    if isinstance(node, lua.TrueExpr):
        return True
    if isinstance(node, lua.FalseExpr):
        return False
    if isinstance(node, lua.Nil):
        return None
    if isinstance(node, lua.UMinusOp):
        operand = _value(node.operand)
        if isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand
    if isinstance(node, lua.Concat):
        left, right = _value(node.left), _value(node.right)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, lua.Call) and isinstance(node.func, lua.Name):
        if node.func.id == "_" and len(node.args) == 1:
            return _value(node.args[0])
    if isinstance(node, lua.Table):
        mapped: dict[Any, Any] = {}
        next_index = 1
        for entry in node.fields:
            if entry.key is None:
                key = next_index
                next_index += 1
            elif isinstance(entry.key, lua.Name) and not entry.between_brackets:
                key = entry.key.id
            else:
                key = _value(entry.key)
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                return UnsupportedValue("a computed or unsupported Lua table key")
            mapped[key] = _value(entry.value)
        if not mapped:
            return []
        if all(type(key) is int for key in mapped) and set(mapped) == set(range(1, len(mapped) + 1)):
            return [mapped[key] for key in range(1, len(mapped) + 1)]
        return mapped
    if isinstance(node, (lua.AnonymousFunction, lua.Function, lua.LocalFunction)):
        return UnsupportedValue("an inline Lua callback; migrate it to a TF3 script module first")
    return UnsupportedValue(f"a dynamic Lua expression ({type(node).__name__}); use literal metadata")


def load_lua_table(text: str) -> dict[str, Any]:
    """Accept a bare table, returned chunk, or direct return in data()."""
    text = text.lstrip("\ufeff")
    try:
        tree = ast.parse(text)
    except ast.SyntaxException:
        try:
            tree = ast.parse("return " + text)
        except ast.SyntaxException as error:
            raise ValueError(f"Invalid Lua metadata: {error}") from error

    if any(not isinstance(statement, (lua.Return, lua.Function, lua.LocalFunction)) for statement in tree.body.body):
        raise ValueError("Lua metadata uses executable top-level statements. Replace them with literal metadata before conversion")
    returns = [statement for statement in tree.body.body if isinstance(statement, lua.Return)]
    data_functions = [
        statement for statement in tree.body.body
        if isinstance(statement, (lua.Function, lua.LocalFunction))
        and isinstance(statement.name, lua.Name) and statement.name.id == "data"
    ]
    if data_functions:
        if len(data_functions) != 1 or returns:
            raise ValueError("Lua metadata contains ambiguous data functions or returns")
        statements = data_functions[0].body.body
        returns = [statement for statement in statements if isinstance(statement, lua.Return)]
        if any(not isinstance(statement, (lua.Return, lua.LocalFunction)) for statement in statements):
            raise ValueError("data() computes metadata. Replace it with a direct literal return table before conversion")
    if len(returns) != 1 or len(returns[0].values) != 1:
        raise ValueError("Lua metadata must contain one direct returned table or data() return table")
    payload = _value(returns[0].values[0])
    if payload == []:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Lua metadata must return a table with named fields")
    return payload
