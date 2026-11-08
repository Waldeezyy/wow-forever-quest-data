"""Parse a restricted Lua DATA subset without running Lua or Python expressions.

Public API:
  parse_value(text, start=0, env=None) -> (value, end_character_offset)
  iter_calls(text, callee, env=None, all_args=False) -> [(value, call_offset)]
  collect_table_bindings(selected_source_block, env=None) -> dict

Tables containing only positional fields become Python lists. Keyed/mixed
tables become dicts (explicit numeric keys stay numeric); an empty table is a
dict because Lua itself has no empty-array/object distinction. Literal nil is
preserved as None; this parser records declarations rather than executing Lua
assignment/deletion semantics. Duplicate table keys use the last declaration.

An optional environment may contain ALREADY PARSED data. It permits only bare
names and constant-index/field lookups: no calls, arithmetic, metatables,
concatenation, comprehensions, imports, or evaluation. Unknown names fail.

iter_calls lexes strings/comments to avoid false matches. It parses all data
arguments, returning the first by default; all_args=True retains the argument
list. Calls whose arguments contain unsupported expressions fail explicitly.
Use the selected -- Source: block when collecting compiler-local table aliases;
this is a data extractor, not a Lua lexical-scope or control-flow interpreter.
"""
from dataclasses import dataclass
import math
import re


MAX_DEPTH = 128
MAX_NODES = 250_000


class LuaDataError(ValueError):
    def __init__(self, message, text, offset):
        self.offset = offset
        self.line = text.count("\n", 0, offset) + 1
        previous = text.rfind("\n", 0, offset)
        self.column = offset - previous
        super().__init__(f"{message} at line {self.line}, column {self.column} (offset {offset})")


@dataclass(frozen=True)
class _Token:
    kind: str
    value: object
    start: int
    end: int


_NUMBER = re.compile(
    r"(?:0[xX][0-9a-fA-F]+(?:\.(?!\.)[0-9a-fA-F]*)?(?:[pP][+-]?\d+)?"
    r"|(?:\d+\.(?!\.)\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_SIMPLE_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13,
                   "t": 9, "v": 11, "\\": 92, '"': 34, "'": 39}
_EXPRESSION_TOKENS = {"+", "-", "*", "/", "//", "%", "^", "..", "==",
                      "~=", "<", ">", "<=", ">=", "&", "|", "~", "<<", ">>"}


class _Lexer:
    def __init__(self, text, start=0):
        self.text = text
        self.pos = start

    def error(self, message, offset=None):
        raise LuaDataError(message, self.text, self.pos if offset is None else offset)

    def _long(self, start):
        match = _LONG_OPEN.match(self.text, start)
        if not match:
            return None
        close = "]" + match.group(1) + "]"
        end = self.text.find(close, match.end())
        if end < 0:
            self.error("unterminated long string/comment", start)
        value = self.text[match.end():end].replace("\r\n", "\n").replace("\r", "\n")
        # Lua discards a newline immediately following the opening delimiter.
        if value.startswith("\r\n"):
            value = value[2:]
        elif value.startswith(("\n", "\r")):
            value = value[1:]
        return value, end + len(close)

    def _skip(self):
        text = self.text
        while self.pos < len(text):
            if text[self.pos].isspace() or (self.pos == 0 and text[self.pos] == "\ufeff"):
                self.pos += 1
            elif text.startswith("--", self.pos):
                start = self.pos + 2
                block = self._long(start)
                if block is not None:
                    self.pos = block[1]
                else:
                    newline = re.search(r"[\r\n]", text[start:])
                    self.pos = len(text) if newline is None else start + newline.end()
            else:
                break

    def _quoted(self):
        start, quote = self.pos, self.text[self.pos]
        self.pos += 1
        result = bytearray()
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                try:
                    return _Token("string", result.decode("utf-8"), start, self.pos)
                except UnicodeDecodeError:
                    self.error("non-UTF-8 Lua byte string is outside this data format", start)
            if char in "\r\n":
                self.error("unescaped newline in short string", self.pos - 1)
            if char != "\\":
                result.extend(char.encode("utf-8"))
                continue
            if self.pos >= len(self.text):
                self.error("unterminated string escape", start)
            escape = self.text[self.pos]
            self.pos += 1
            if escape in _SIMPLE_ESCAPES:
                result.append(_SIMPLE_ESCAPES[escape])
            elif escape in "\r\n":
                if escape == "\r" and self.text.startswith("\n", self.pos):
                    self.pos += 1
                result.append(10)
            elif escape.isascii() and escape.isdigit():
                digits = escape
                while len(digits) < 3 and self.pos < len(self.text) and self.text[self.pos] in "0123456789":
                    digits += self.text[self.pos]
                    self.pos += 1
                number = int(digits)
                if number > 255:
                    self.error("decimal string escape exceeds one byte", self.pos - len(digits))
                result.append(number)
            elif escape == "x":
                digits = self.text[self.pos:self.pos + 2]
                if len(digits) != 2 or not all(c in "0123456789abcdefABCDEF" for c in digits):
                    self.error("invalid hexadecimal string escape", self.pos - 2)
                result.append(int(digits, 16))
                self.pos += 2
            elif escape == "z":
                # Lua 5.2+ whitespace escape. No executable behavior involved.
                while self.pos < len(self.text) and self.text[self.pos].isspace():
                    self.pos += 1
            else:
                self.error("unsupported string escape \\" + escape, self.pos - 2)
        self.error("unterminated short string", start)

    def next(self):
        self._skip()
        start = self.pos
        if start >= len(self.text):
            return _Token("eof", None, start, start)
        char = self.text[start]
        if char in "\"'":
            return self._quoted()
        if char == "[":
            value = self._long(start)
            if value is not None:
                self.pos = value[1]
                return _Token("string", value[0], start, self.pos)
        match = _NUMBER.match(self.text, start)
        if match:
            spelling = match.group()
            self.pos = match.end()
            if self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
                self.error("invalid numeric literal", start)
            try:
                if spelling.lower().startswith("0x"):
                    value = float.fromhex(spelling) if any(c in spelling.lower() for c in ".p") else int(spelling, 16)
                else:
                    value = float(spelling) if any(c in spelling for c in ".eE") else int(spelling)
            except ValueError:
                self.error("invalid numeric literal", start)
            if isinstance(value, float) and not math.isfinite(value):
                self.error("nonfinite numeric literal", start)
            return _Token("number", value, start, self.pos)
        match = _NAME.match(self.text, start)
        if match:
            self.pos = match.end()
            return _Token("name", match.group(), start, self.pos)
        for operator in ("...", "..", "==", "~=", "<=", ">=", "//", "<<", ">>"):
            if self.text.startswith(operator, start):
                self.pos += len(operator)
                return _Token(operator, operator, start, self.pos)
        # Code outside selected literal values is only tokenized, never run.
        self.pos += 1
        return _Token(char, char, start, self.pos)


class _Parser:
    def __init__(self, text, start=0, env=None):
        self.text = text
        self.lexer = _Lexer(text, start)
        self.lookahead = []
        self.env = env if env is not None else {}
        self.nodes = 0
        self.end = start

    def peek(self, count=0):
        while len(self.lookahead) <= count:
            self.lookahead.append(self.lexer.next())
        return self.lookahead[count]

    def take(self):
        token = self.peek()
        self.lookahead.pop(0)
        self.end = token.end
        return token

    def require(self, kind):
        token = self.take()
        if token.kind != kind:
            raise LuaDataError("expected " + kind + ", found " + str(token.value or token.kind), self.text, token.start)
        return token

    def error(self, message, token=None):
        token = token or self.peek()
        raise LuaDataError(message, self.text, token.start)

    def _index(self, value, key, token):
        if isinstance(key, bool) or key is None or not isinstance(key, (str, int, float)):
            self.error("unsupported constant table index", token)
        if type(value) is list:
            if isinstance(key, (int, float)) and int(key) == key and 1 <= int(key) <= len(value):
                return value[int(key) - 1]
            self.error("missing Lua array index " + repr(key), token)
        if type(value) is dict:
            if key in value:
                return value[key]
            self.error("missing data-table key " + repr(key), token)
        self.error("indexing is allowed only on parsed data tables", token)

    def _reference(self):
        name = self.take()
        if name.value not in self.env:
            self.error("unknown data identifier " + repr(name.value), name)
        value = self.env[name.value]
        while self.peek().kind in ("[", "."):
            if self.peek().kind == ".":
                self.take()
                key = self.require("name")
                value = self._index(value, key.value, key)
            else:
                self.take()
                key = self.peek()
                sign = 1
                if key.kind == "-":
                    sign = -1
                    self.take()
                    key = self.peek()
                if key.kind not in ("number", "string") or (sign == -1 and key.kind != "number"):
                    self.error("reference index must be a literal number or string", key)
                self.take()
                index = sign * key.value if key.kind == "number" else key.value
                self.require("]")
                value = self._index(value, index, key)
        if self.peek().kind in ("(", ":"):
            self.error("function/method calls are unsupported in data expressions")
        if type(value) not in (str, int, float, bool, list, dict, type(None)):
            self.error("environment value is not parsed data", name)
        if type(value) is float and not math.isfinite(value):
            self.error("nonfinite environment data number", name)
        return value

    def value(self, depth=0):
        if depth > MAX_DEPTH:
            self.error("data nesting exceeds limit")
        self.nodes += 1
        if self.nodes > MAX_NODES:
            self.error("data value count exceeds limit")
        token = self.peek()
        if token.kind in ("string", "number"):
            return self.take().value
        if token.kind == "-":
            self.take()
            number = self.require("number")
            return -number.value
        if token.kind == "{":
            return self.table(depth + 1)
        if token.kind == "name":
            if token.value in ("true", "false", "nil"):
                self.take()
                return {"true": True, "false": False, "nil": None}[token.value]
            return self._reference()
        self.error("unsupported data expression beginning " + repr(token.value or token.kind), token)

    def table(self, depth):
        self.require("{")
        fields = []
        keyed = False
        next_index = 1
        while self.peek().kind != "}":
            if self.peek().kind == "eof":
                self.error("unterminated table")
            if self.peek().kind == "[":
                keyed = True
                self.take()
                key_token = self.peek()
                # Table keys are literal scalars; expressions/references are not keys.
                if key_token.kind not in ("number", "string", "-"):
                    self.error("table key must be a literal string or number", key_token)
                key = self.value(depth)
                if isinstance(key, bool) or not isinstance(key, (str, int, float)):
                    self.error("unsupported table key", key_token)
                self.require("]")
                self.require("=")
                fields.append((key, self.value(depth)))
            elif self.peek().kind == "name" and self.peek(1).kind == "=":
                keyed = True
                key = self.take().value
                self.take()
                fields.append((key, self.value(depth)))
            else:
                fields.append((next_index, self.value(depth)))
                next_index += 1
            if self.peek().kind in (",", ";"):
                self.take()
            elif self.peek().kind != "}":
                self.error("expected table separator; expressions are unsupported")
        self.require("}")
        if not fields:
            return {}
        if keyed:
            return dict(fields)
        return [value for _, value in fields]


def parse_value(text, start=0, env=None, *, names=None):
    """Parse one restricted data value; return its end offset, excluding whitespace.

    `names` is an alias for `env`; pass at most one. Numeric array references
    use Lua's one-based indexing. Unsupported operators/calls fail explicitly.
    """
    if env is not None and names is not None:
        raise TypeError("pass env or names, not both")
    if not isinstance(text, str) or not isinstance(start, int) or not 0 <= start <= len(text):
        raise ValueError("text must be str and start a valid character offset")
    parser = _Parser(text, start, env if env is not None else names)
    value = parser.value()
    next_token = parser.peek()
    if next_token.kind in _EXPRESSION_TOKENS or (next_token.kind == "name" and next_token.value in ("and", "or")):
        parser.error("operators are unsupported in data expressions", next_token)
    return value, parser.end


def _tokens(text):
    lexer = _Lexer(text)
    result = []
    while True:
        token = lexer.next()
        result.append(token)
        if token.kind == "eof":
            return result


def iter_calls(text, callee, env=None, *, names=None, all_args=False):
    """Return (first_data_argument, call_character_offset) pairs in source order.

    All arguments must be data. With all_args=True, the pair's first value is
    the complete argument list. Strings/comments/unrelated functions are only
    lexed. This does not simulate whether a Lua branch would execute the call.
    """
    if env is not None and names is not None:
        raise TypeError("pass env or names, not both")
    environment = env if env is not None else names
    pieces = callee.split(".")
    if not pieces or not all(_NAME.fullmatch(piece) for piece in pieces):
        raise ValueError("callee must be a dot-separated identifier")
    wanted = []
    for index, piece in enumerate(pieces):
        if index:
            wanted.append((".", "."))
        wanted.append(("name", piece))
    tokens = _tokens(text)
    calls = []
    for index in range(len(tokens) - len(wanted)):
        if index and (tokens[index - 1].kind in (".", ":") or tokens[index - 1].value == "function"):
            continue
        if any((tokens[index + n].kind, tokens[index + n].value) != item for n, item in enumerate(wanted)):
            continue
        opening = tokens[index + len(wanted)]
        if opening.kind != "(":
            continue
        parser = _Parser(text, opening.end, environment)
        arguments = []
        if parser.peek().kind == ")":
            parser.error("registered data call requires an argument")
        while True:
            arguments.append(parser.value())
            if parser.peek().kind == ",":
                parser.take()
                if parser.peek().kind == ")":
                    parser.error("trailing function argument comma is unsupported")
            else:
                parser.require(")")
                break
        calls.append((arguments if all_args else arguments[0], tokens[index].start))
    return calls


def collect_table_bindings(text, env=None):
    """Resolve local NAME = {literal-data} assignments in a SELECTED source block.

    A shallow copy of env is extended in source order. Non-table locals (e.g.
    `local function register` or `local ADDON = ...`) are not executed or bound.
    An unknown identifier inside a selected table is an error, not a fallback.
    This helper intentionally does not infer Lua function scopes/control flow.
    """
    result = dict(env or {})
    tokens = _tokens(text)
    for index in range(len(tokens) - 3):
        a, b, c, d = tokens[index:index + 4]
        if a.kind == "name" and a.value == "local" and b.kind == "name" and c.kind == "=" and d.kind == "{":
            value, _ = parse_value(text, d.start, result)
            result[b.value] = value
    return result


def extract_guide_block(text, env=None):
    """Extract exactly one RegisterGuide from an already selected Source block."""
    environment = collect_table_bindings(text, env)
    calls = iter_calls(text, "Polestar.RegisterGuide", environment)
    if len(calls) != 1:
        raise LuaDataError("expected exactly one RegisterGuide in selected source block", text, 0)
    value, offset = calls[0]
    if not isinstance(value, dict):
        raise LuaDataError("RegisterGuide argument must be a keyed data table", text, offset)
    return value, offset
