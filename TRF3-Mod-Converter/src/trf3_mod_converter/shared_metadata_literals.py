"""Read shared literal localization keys without executing either source file."""
from __future__ import annotations

from luaparser import ast
from luaparser import astnodes as lua

from .lua_metadata import _value, load_lua_table, same_pure_literal
from .resource_profiles import load_resource_table


def _tree(text: str):
    text = text.lstrip('\ufeff')
    try:
        return ast.parse(text)
    except ast.SyntaxException:
        # Match the metadata reader's supported bare-table input.
        try:
            return ast.parse('return ' + text)
        except ast.SyntaxException as error:
            raise ValueError(f'Invalid shared metadata Lua source: {error}') from error


def _shadowed_names(tree, names: set[str]) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        bindings = node.targets if isinstance(node, lua.LocalAssign) else []
        if isinstance(node, (lua.Function, lua.LocalFunction, lua.AnonymousFunction)):
            bindings = [*node.args, getattr(node, 'name', None)]
        found.update(binding.id for binding in bindings
                     if isinstance(binding, lua.Name) and binding.id in names)
    return found


def _assignment_name(target):
    while isinstance(target, lua.Index):
        target = target.value
    return target.id if isinstance(target, lua.Name) else None


def load_literal_dependency_info(text: str) -> dict:
    """Read only dependency identities from a direct literal info header.

    A provider can contain active callbacks or unrelated helper definitions.
    This inspection does not import, execute, or convert any provider behavior.
    Selected fields must be inert constants in the final data() definition;
    dynamic return construction and ambiguous identities remain blockers.
    """
    if len(text.encode('utf-8')) > 4 * 1024 * 1024:
        raise ValueError('Dependency metadata exceeds the safe parser input limit')
    try:
        tree = _tree(text)
    except RecursionError as error:
        raise ValueError('Dependency metadata nesting exceeds the safe parser limit') from error
    statements = tree.body.body
    functions = [node for node in statements
                 if isinstance(node, (lua.Function, lua.LocalFunction)) and isinstance(node.name, lua.Name)
                 and node.name.id == 'data']
    direct_chunk = (not functions and len(statements) == 1 and isinstance(statements[0], lua.Return))
    if not direct_chunk and (len(functions) != 1 or not statements
                             or statements[-1] is not functions[0] or functions[0].args):
        raise ValueError('Dependency metadata requires one final argument-free data() definition')
    fn = None if direct_chunk else functions[0]
    # Header inspection admits only independent literal local initializers and
    # uncalled local helper declarations before data(). Imports and top-level
    # API calls are not asserted harmless merely because we do not run them.
    for statement in statements[:-1] if not direct_chunk else []:
        if isinstance(statement, lua.LocalFunction):
            if not isinstance(statement.name, lua.Name) or statement.name.id == 'data':
                raise ValueError('Dependency metadata has an ambiguous local helper')
            continue
        if (not isinstance(statement, lua.LocalAssign)
                or len(statement.targets) != len(statement.values)
                or any(not isinstance(target, lua.Name) or target.id == 'data' for target in statement.targets)):
            raise ValueError('Dependency metadata prefix must contain only independent literal locals or local helpers')
        for expression in statement.values:
            if any(isinstance(node, (lua.Call, lua.AnonymousFunction, lua.Function, lua.LocalFunction))
                   for node in ast.walk(expression)):
                raise ValueError('Dependency metadata prefix contains a computed import or initializer')
            value = _value(expression, strict_duplicates=True)
            if not same_pure_literal(value, value):
                raise ValueError('Dependency metadata prefix contains a nonliteral local initializer')
    for node in ast.walk(tree):
        if node is fn:
            continue
        targets = node.targets if isinstance(node, (lua.Assign, lua.LocalAssign)) else []
        if isinstance(node, (lua.Function, lua.LocalFunction)):
            targets = [node.name]
        if any(_assignment_name(target) == 'data' for target in targets):
            raise ValueError('Dependency metadata has a shadowed or mutable data binding')
    body = statements if direct_chunk else fn.body.body
    if (len(body) != 1 or not isinstance(body[0], lua.Return) or len(body[0].values) != 1
            or not isinstance(body[0].values[0], lua.Table)):
        raise ValueError('Dependency metadata must directly return one literal root table')

    def key(field):
        if isinstance(field.key, lua.Name) and not field.between_brackets:
            return field.key.id
        if isinstance(field.key, lua.String):
            return _value(field.key)
        raise ValueError('Dependency metadata header needs literal named keys')

    headers = [field.value for field in body[0].values[0].fields if key(field) == 'info']
    if len(headers) != 1 or not isinstance(headers[0], lua.Table):
        raise ValueError('Dependency metadata requires one direct literal info table')
    selected = {'requiredMods', 'modid', 'modId', 'steamId', 'minorVersion'}
    result = {}
    for field in headers[0].fields:
        name = key(field)
        if name not in selected:
            continue
        # Even a literal-looking localization call is not an identity constant:
        # its function could be replaced by this provider's unrelated code.
        if any(isinstance(node, (lua.Call, lua.AnonymousFunction, lua.Function, lua.LocalFunction))
               for node in ast.walk(field.value)):
            raise ValueError(f'Dependency identity {name} must be a pure literal')
        value = _value(field.value, strict_duplicates=True)
        if not same_pure_literal(value, value):
            raise ValueError(f'Dependency identity {name} must be a finite inert literal')
        if name in result and not same_pure_literal(result[name], value):
            raise ValueError(f'Conflicting duplicate dependency identity: {name}')
        result[name] = value
    return result


def load_mod_metadata(text: str, strings_text: str | None, *, audit: dict) -> dict:
    """Allow only localization arguments from verified same-package globals.

    All ordinary metadata validation remains with ``load_lua_table``. A binding
    must be assigned once as a string in the direct strings.lua data() body,
    with no lexical shadow or other write in either file. The resource reader
    proves its literal value and all locale tables; only the in-memory metadata
    AST changes. The original source text and language tables stay untouched.
    """
    original = load_lua_table(text, audit=audit, resource='mod.lua')
    tree = _tree(text)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, lua.Call) and isinstance(node.func, lua.Name)
             and node.func.id == '_' and len(node.args) == 1
             and isinstance(node.args[0], lua.Name)]
    if not calls:
        return original
    requested = {node.args[0].id for node in calls}
    if strings_text is None:
        raise ValueError('Shared metadata localization binding has no same-package strings.lua')
    strings_tree = _tree(strings_text)
    shadowed = (_shadowed_names(tree, requested | {'_'})
                | _shadowed_names(strings_tree, requested | {'_'}))
    if shadowed:
        raise ValueError(f'Shadowed shared metadata localization binding: {sorted(shadowed)}')
    if any(_assignment_name(target) in requested for node in ast.walk(tree)
           if isinstance(node, lua.Assign) for target in node.targets):
        raise ValueError('Shared metadata localization binding is written or mutated in mod.lua')

    functions = [node for node in strings_tree.body.body
                 if isinstance(node, lua.Function) and isinstance(node.name, lua.Name)
                 and node.name.id == 'data']
    if len(functions) != 1 or functions[0].args:
        raise ValueError('Shared metadata bindings require one argument-free strings.lua data()')
    direct = functions[0].body.body
    global_assignments = [node for node in direct if isinstance(node, lua.Assign)
                          and len(node.targets) == len(node.values) == 1
                          and isinstance(node.targets[0], lua.Name)]
    for name in requested:
        writes = [node for node in ast.walk(strings_tree) if isinstance(node, lua.Assign)
                  and any(_assignment_name(target) == name for target in node.targets)]
        eligible = [node for node in global_assignments if node.targets[0].id == name]
        if len(writes) != 1 or len(eligible) != 1 or writes[0] is not eligible[0]:
            raise ValueError(f'Unknown, multiply assigned or mutable shared metadata binding: {name}')

    proof = {}
    load_resource_table(strings_text, allow_global_literals=True,
                        audit=proof, resource='strings.lua')
    folded = [row for row in proof.get('translationMigrations', [])
              if row.get('policy') == 'fold_literal_translation_binding']
    bindings = {}
    for name in requested:
        rows = [row for row in folded if row.get('sourceName') == name]
        if len(rows) != 1 or type(rows[0].get('sourceValue')) is not str:
            raise ValueError(f'Shared metadata binding must be one verified literal string: {name}')
        bindings[name] = rows[0]['sourceValue']

    for call in calls:
        value = bindings[call.args[0].id]
        call.args[0] = lua.String(s=value.encode('utf-8'), raw=value,
                                 delimiter=lua.StringDelimiter.DOUBLE_QUOTE)
    # The original metadata reader already validated the return shape and
    # statement contract. Re-read only its now-literal AST payload, retaining
    # TranslatedString provenance instead of choosing a language here.
    data_functions = [node for node in tree.body.body
                      if isinstance(node, (lua.Function, lua.LocalFunction))
                      and isinstance(node.name, lua.Name) and node.name.id == 'data']
    statements = data_functions[0].body.body if data_functions else tree.body.body
    payload = next(node.values[0] for node in statements if isinstance(node, lua.Return))
    result = _value(payload)
    for name, value in sorted(bindings.items()):
        audit.setdefault('metadataMigrations', []).append({
            'sourceResource': 'strings.lua', 'sourceName': name,
            'sourceValue': value, 'targetResource': 'mod.lua',
            'policy': 'fold_shared_literal_localization_key',
            'originalFile': '_port_originals/strings.lua', 'nativeTest': 'not_run'})
    return result
