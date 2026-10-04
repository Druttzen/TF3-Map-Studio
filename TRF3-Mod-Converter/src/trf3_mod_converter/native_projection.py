"""Read native donor metadata without constructing unused model LOD ASTs.

This conservative fast path accepts one direct ``data()`` return table and
side-effect-free literal root values. It uses Lua's lexer, never Lua execution
or regular-expression brace matching. Unsupported shapes fall back to the
existing full static parser; selected donors still require that full parser.
"""
from __future__ import annotations

from antlr4 import InputStream, Token
from antlr4.error.ErrorListener import ErrorListener
from luaparser.parser.LuaLexer import LuaLexer

from .resource_profiles import load_resource_table


class UnsupportedProjection(ValueError):
    """The fast path cannot prove a literal, direct model return shape."""


_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_DEPTH = 128
_PROJECTED = {'version', 'metadata', 'boundingInfo'}
_SCALARS = {
    LuaLexer.NORMALSTRING, LuaLexer.CHARSTRING, LuaLexer.LONGSTRING,
    LuaLexer.INT, LuaLexer.HEX, LuaLexer.FLOAT, LuaLexer.HEX_FLOAT,
    LuaLexer.NIL, LuaLexer.FALSE, LuaLexer.TRUE,
}
_STRINGS = {LuaLexer.NORMALSTRING, LuaLexer.CHARSTRING, LuaLexer.LONGSTRING}
_BINARY = {
    LuaLexer.PLUS, LuaLexer.MINUS, LuaLexer.STAR, LuaLexer.SLASH,
    LuaLexer.SS, LuaLexer.PER, LuaLexer.CARET, LuaLexer.DD,
    LuaLexer.AMP, LuaLexer.PIPE, LuaLexer.SQUIG, LuaLexer.LL, LuaLexer.GG,
}


class _LexerErrors(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, exc):
        raise UnsupportedProjection(f'Native model lexer error at {line}:{column}: {msg}')


class _Scanner:
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self, offset=0):
        index = self.position + offset
        return self.tokens[index].type if index < len(self.tokens) else Token.EOF

    def take(self, expected=None):
        if self.position >= len(self.tokens):
            raise UnsupportedProjection('Unexpected end of native model')
        token = self.tokens[self.position]
        if expected is not None and token.type != expected:
            raise UnsupportedProjection('Native model does not have a direct literal return shape')
        self.position += 1
        return token

    def value(self, depth=0):
        if depth > _MAX_DEPTH:
            raise UnsupportedProjection('Native literal nesting exceeds the projection limit')
        self.atom(depth)
        while self.peek() in _BINARY:
            self.take()
            self.atom(depth)

    def atom(self, depth):
        if depth > _MAX_DEPTH:
            raise UnsupportedProjection('Native literal nesting exceeds the projection limit')
        token = self.peek()
        if token in (LuaLexer.MINUS, LuaLexer.PLUS, LuaLexer.SQUIG, LuaLexer.POUND, LuaLexer.NOT):
            self.take()
            self.atom(depth+1)
        elif token in _SCALARS:
            self.take()
        elif token == LuaLexer.OP:
            self.take()
            self.value(depth+1)
            self.take(LuaLexer.CP)
        elif token == LuaLexer.OCU:
            self.table(depth+1)
        elif token == LuaLexer.NAME and self.tokens[self.position].text == '_' and self.peek(1) == LuaLexer.OP:
            # The full static parser's established localization convention.
            self.take(); self.take()
            if self.peek() not in _STRINGS:
                raise UnsupportedProjection('Native localization argument is not a literal string')
            self.take(); self.take(LuaLexer.CP)
        else:
            # Calls, references, callbacks and computed helper resources need
            # the full parser. Balanced text alone does not prove purity.
            raise UnsupportedProjection('Native model contains a nonliteral root value')

    def field(self, depth):
        key = None
        if self.peek() == LuaLexer.NAME and self.peek(1) == LuaLexer.EQ:
            key = self.take().text
            self.take()
        elif self.peek() == LuaLexer.OB:
            self.take()
            # Keys themselves must also be side-effect-free literals. Root
            # bracketed keys are accepted structurally but use the full parser
            # if they could select a projected field.
            self.value(depth+1)
            self.take(LuaLexer.CB)
            self.take(LuaLexer.EQ)
            key = False
        start = self.position
        self.value(depth+1)
        stop = self.position
        return key, start, stop

    def table(self, depth):
        if depth > _MAX_DEPTH:
            raise UnsupportedProjection('Native literal nesting exceeds the projection limit')
        self.take(LuaLexer.OCU)
        while self.peek() != LuaLexer.CCU:
            self.field(depth)
            if self.peek() in (LuaLexer.COMMA, LuaLexer.SEMI):
                self.take()
            elif self.peek() != LuaLexer.CCU:
                raise UnsupportedProjection('Native literal table field separator is missing')
        self.take(LuaLexer.CCU)


def project_native_model(text):
    """Return literal ``version``, ``metadata`` and ``boundingInfo`` values.

    Duplicate root fields use the full parser, whose established policy rejects
    duplicate keys. A callback or arbitrary expression anywhere in the root
    table signals ``UnsupportedProjection``; neither parsing strategy executes
    its source. No LOD model is returned.
    """
    if not isinstance(text, str) or len(text.encode('utf-8')) > _MAX_SOURCE_BYTES:
        raise UnsupportedProjection('Native model exceeds the projection source limit')
    lexer = LuaLexer(InputStream(text.removeprefix('\ufeff')))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_LexerErrors())
    # The adjusted source and token indices must use the same character basis.
    source = text.removeprefix('\ufeff')
    tokens = [token for token in lexer.getAllTokens() if token.channel == Token.DEFAULT_CHANNEL]
    scan = _Scanner(tokens)
    scan.take(LuaLexer.FUNCTION)
    if scan.take(LuaLexer.NAME).text != 'data':
        raise UnsupportedProjection('Native model function must be named data')
    scan.take(LuaLexer.OP); scan.take(LuaLexer.CP)
    scan.take(LuaLexer.RETURN)
    scan.take(LuaLexer.OCU)
    fields = []
    seen = set()
    while scan.peek() != LuaLexer.CCU:
        key, start, stop = scan.field(0)
        if key is None or key is False:
            raise UnsupportedProjection('Native root model requires named literal fields')
        if key in seen:
            raise UnsupportedProjection('Duplicate native root field requires the full static parser')
        seen.add(key)
        if key in _PROJECTED:
            fields.append(key+' = '+source[tokens[start].start:tokens[stop-1].stop+1])
        if scan.peek() in (LuaLexer.COMMA, LuaLexer.SEMI):
            scan.take()
        elif scan.peek() != LuaLexer.CCU:
            raise UnsupportedProjection('Native root table field separator is missing')
    scan.take(LuaLexer.CCU)
    if scan.peek() == LuaLexer.SEMI:
        scan.take()
    scan.take(LuaLexer.END)
    if scan.peek() == LuaLexer.SEMI:
        scan.take()
    if scan.peek() != Token.EOF:
        raise UnsupportedProjection('Native model has additional top-level statements')
    result = load_resource_table('return {\n'+',\n'.join(fields)+'\n}')
    return {} if result == [] else result
