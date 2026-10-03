"""Read static Lua metadata without executing a mod or its callbacks."""
from __future__ import annotations

from dataclasses import dataclass
import math
import operator
from typing import Any

from luaparser import ast
from luaparser import astnodes as lua


@dataclass(frozen=True)
class UnsupportedValue:
    reason: str
    empty_callback: bool = False


def _value(node: lua.Node, constant_numbers: bool = False) -> Any:
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
        operand = _value(node.operand, constant_numbers)
        if isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand
    if isinstance(node, lua.Concat):
        left, right = _value(node.left, constant_numbers), _value(node.right, constant_numbers)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if constant_numbers:
        operators = {lua.AddOp:operator.add, lua.SubOp:operator.sub, lua.MultOp:operator.mul,
                     lua.FloatDivOp:operator.truediv, lua.ExpoOp:math.pow}
        operation = operators.get(type(node))
        arguments = [node.left,node.right] if operation else None
        if (isinstance(node,lua.Call) and isinstance(node.func,lua.Index)
                and node.func.notation == lua.IndexNotation.DOT and isinstance(node.func.value,lua.Name)
                and node.func.value.id == 'math' and isinstance(node.func.idx,lua.Name)
                and node.func.idx.id == 'pow' and len(node.args) == 2):
            operation, arguments = math.pow, node.args
        if operation:
            values = [_value(a, True) for a in arguments]
            if all(type(v) in (int,float) and math.isfinite(v) for v in values):
                try:
                    result = operation(*values)
                    if math.isfinite(result): return result
                except (ValueError, ZeroDivisionError, OverflowError):
                    pass
                raise ValueError('Constant numeric expression is undefined or non-finite')
    if isinstance(node, lua.Call) and isinstance(node.func, lua.Name):
        if node.func.id == "_" and len(node.args) == 1:
            return _value(node.args[0], constant_numbers)
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
                key = _value(entry.key, constant_numbers)
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                return UnsupportedValue("a computed or unsupported Lua table key")
            mapped[key] = _value(entry.value, constant_numbers)
        if not mapped:
            return []
        if all(type(key) is int for key in mapped) and set(mapped) == set(range(1, len(mapped) + 1)):
            return [mapped[key] for key in range(1, len(mapped) + 1)]
        return mapped
    if isinstance(node, (lua.AnonymousFunction, lua.Function, lua.LocalFunction)):
        return UnsupportedValue("an inline Lua callback; migrate it to a TF3 script module first",
                                isinstance(node, lua.AnonymousFunction) and not node.body.body)
    return UnsupportedValue(f"a dynamic Lua expression ({type(node).__name__}); use literal metadata")


def load_lua_table(text: str, *, constant_numbers: bool = False) -> dict[str, Any]:
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
    if constant_numbers:
        for node in ast.walk(tree):
            bindings = node.targets if isinstance(node,(lua.Assign,lua.LocalAssign)) else []
            if isinstance(node,(lua.Function,lua.LocalFunction,lua.AnonymousFunction)):
                bindings = [*node.args, getattr(node,'name',None)]
            if any(isinstance(binding,lua.Name) and binding.id == 'math' for binding in bindings):
                raise ValueError('Cannot fold numeric expressions with a shadowed math binding')
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
    payload = _value(returns[0].values[0], constant_numbers)
    if payload == []:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Lua metadata must return a table with named fields")
    return payload
