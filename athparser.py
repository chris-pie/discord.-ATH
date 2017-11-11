from functools import partial, reduce

from lexer import Lexer, Token

from grafter import Selector, ExprParser, StrictExpr
from grafter import TokenGrafter, TagGrafter
from grafter import EnsureGraft, Repeater
from grafter import LazyGrafter, StrictGrafter

from athast import AthSymbol, SymbolError, EndTilDeath
from athast import IntExpr, FloatExpr, StringExpr, VarExpr
from athast import NotExpr, AndExpr, OrExpr, XorExpr
from athast import UnaryArithExpr, BinaryArithExpr, ValueCmpExpr
from athast import SymBoolExpr, TernaryExpr, Serialize

from athast import InputStmt, PrintFunc, KillFunc
from athast import BifurcateStmt, AggregateStmt
from athast import ProcreateStmt, ReplicateStmt
from athast import FabricateStmt, ExecuteStmt
from athast import WhenStmt, UnlessStmt, TildeAthLoop


ath_lexer = Lexer([
    (r'(?s)/\*.*?\*/', None), # Multi-line comment
    (r'//[^\n]*', None), # Single-line comment
    (r'\s+', None), # Whitespace
    # Code enclosures
    (r'\(', 'BUILTIN'), # Conditional/Call open
    (r'\)', 'BUILTIN'), # Conditional/Call close
    (r'{', 'BUILTIN'), # Suite open
    (r'}', 'BUILTIN'), # Suite close
    (r'\[', 'BUILTIN'), # Symbol slice open
    (r'\]', 'BUILTIN'), # Symbol slice close
    # Separators
    (r';', 'BUILTIN'), # Statement separator
    (r'\.', 'BUILTIN'), # Lookup operator
    (r',', 'BUILTIN'), # Group operator
    # Arithmetic in-place operators
    (r'\+=', 'BUILTIN'), # Add
    (r'-=', 'BUILTIN'), # Sub
    (r'\*\*=', 'BUILTIN'), # Pow
    (r'\*=', 'BUILTIN'), # Mul
    (r'/_=', 'BUILTIN'), # FloorDiv
    (r'/=', 'BUILTIN'), # TrueDiv
    (r'%=', 'BUILTIN'), # Modulo
    # Arithmetic operators
    (r'\+', 'BUILTIN'), # Add, UnaryAbs
    (r'-', 'BUILTIN'), # Sub, UnaryInv
    (r'\*\*', 'BUILTIN'), # Pow
    (r'\*', 'BUILTIN'), # Mul
    (r'/_', 'BUILTIN'), # FloorDiv
    (r'/', 'BUILTIN'), # TrueDiv
    (r'%', 'BUILTIN'), # Modulo
    # Symbol operators
    (r'!=!', 'BUILTIN'), # Assert Both
    (r'!=\?', 'BUILTIN'), # Assert Left
    (r'\?=!', 'BUILTIN'), # Assert Right
    (r'~=!', 'BUILTIN'), # Negate Left
    (r'!=~', 'BUILTIN'), # Negate Right
    (r'~=~', 'BUILTIN'), # Negate Both
    # Bitwise shift in-place operators
    (r'<<=', 'BUILTIN'), # Bitwise lshift
    (r'>>=', 'BUILTIN'), # Bitwise rshift
    # Bitwise shift operators
    (r'<<', 'BUILTIN'), # Bitwise lshift
    (r'>>', 'BUILTIN'), # Bitwise rshift
    # Value operators
    (r'<=', 'BUILTIN'), # Less than or equal to
    (r'<', 'BUILTIN'), # Less than
    (r'>=', 'BUILTIN'), # Greater than or equal to
    (r'>', 'BUILTIN'), # Greater than
    (r'~=', 'BUILTIN'), # Not equal to
    (r'==', 'BUILTIN'), # Equal to
    # Boolean operators
    (r'&&', 'BUILTIN'), # Boolean AND
    (r'\|\|', 'BUILTIN'), # Boolean OR
    (r'\^\^', 'BUILTIN'), # Boolean XOR
    (r'!', 'BUILTIN'), # Boolean NOT
    # Statement keywords
    (r'DIE', 'BUILTIN'), # Kill symbol
    (r'WHEN', 'BUILTIN'), # Conditional Consequent
    (r'UNLESS', 'BUILTIN'), # Conditional Alternative
    (r'~ATH', 'BUILTIN'), # Loop
    (r'print', 'BUILTIN'), # Output
    (r'input', 'BUILTIN'), # Input
    (r'import', 'BUILTIN'), # Import another file
    (r'EXECUTE', 'BUILTIN'), # Subroutine execution
    (r'DIVULGATE', 'BUILTIN'), # Return a symbol
    (r'BIFURCATE', 'BUILTIN'), # Split a symbol
    (r'AGGREGATE', 'BUILTIN'), # Merge a symbol
    (r'PROCREATE', 'BUILTIN'), # Value declaration
    (r'FABRICATE', 'BUILTIN'), # Subroutine declaration
    (r'REPLICATE', 'BUILTIN'), # Deep copy
    # Bitwise in-place operators
    (r'&=', 'BUILTIN'), # Bitwise and
    (r'\|=', 'BUILTIN'), # Bitwise or
    (r'\^=', 'BUILTIN'), # Bitwise xor
    # Bitwise operators
    (r'&', 'BUILTIN'), # Bitwise and
    (r'\|', 'BUILTIN'), # Bitwise or
    (r'\^', 'BUILTIN'), # Bitwise xor
    (r'~', 'BUILTIN'), # Bitwise not
    # Other identifiers
    (r'([\'"])[^\1]*?\1', 'STRING'),
    (r'(\d+\.(\d*)?|\.\d+)([eE][-+]?\d+)?', 'FLOAT'),
    (r'\d+', 'INT'),
    (r'[a-zA-Z]\w*', 'SYMBOL'),
])


strparser = TagGrafter('STRING') ^ StringExpr
fltparser = TagGrafter('FLOAT') ^ FloatExpr
intparser = TagGrafter('INT') ^ IntExpr
nameparser = TagGrafter('SYMBOL') ^ VarExpr


def bltinparser(token):
    return TokenGrafter(token, 'BUILTIN')


def break_group(tokens):
    _, expr, _ = tokens
    return expr


def operatorparser(op_list, grafter, evaluator):
    def parse_ops(op_level):
        ops = reduce(Selector, map(bltinparser, op_level))
        return ops ^ evaluator
    return reduce(StrictExpr, [grafter] + [parse_ops(lvl) for lvl in op_list])


def ternaryexprparser(term):
    def breakdown(tokens):
        trueexpr, _, cond, _, falseexpr = tokens
        return TernaryExpr(truexpr, cond, falseexpr)
    return (
        term
        + bltinparser('WHEN')
        + term
        + bltinparser('UNLESS')
        + term
        ^ breakdown
        )


def symbolexprparser(term):
    ops = [('!=!', '!=?', '?=!', '~=!', '!=~', '~=~')]
    return operatorparser(ops, term, lambda op: lambda l, r: SymBoolExpr(op, l, r))


def boolexprparser(term):
    def eval_not(tokens):
        return NotExpr(tokens[1])
    notparser = bltinparser('!') + term ^ eval_not

    def eval_bool(tokens, op):
        lval, _, rval = tokens
        return op(lval, rval)
    andparser = term + bltinparser('&&') + term ^ partial(eval_bool, op=AndExpr)
    orparser = term + bltinparser('||') + term ^ partial(eval_bool, op=OrExpr)
    xorparser = term + bltinparser('^^') + term ^ partial(eval_bool, op=XorExpr)
    return notparser | andparser | orparser | xorparser


def cmpexprparser(term):
    ops = [('<', '<=', '>', '>=', '==', '~=')]
    return operatorparser(ops, term, lambda op: lambda l, r: ValueCmpExpr(op, l, r))


def binexprparser(term):
    op_order = [
        ('**',),
        ('*', '/', '/_', '%'),
        ('+', '-'),
        ('<<', '>>'),
        ('&',),
        ('|',),
        ('^',),
        ]
    return operatorparser(op_order, term, lambda op: lambda l, r: BinaryArithExpr(op, l, r))


def unaryexprparser(term):
    ops = bltinparser('+') | bltinparser('-') | bltinparser('~')
    return ops + term ^ (lambda _: UnaryArithExpr)


def exprparser():
    def break_group(tokens):
        _, expr, _ = tokens
        return expr
    group = (
        bltinparser('(')
        + LazyGrafter(exprparser)
        + bltinparser(')')
        ^ break_group
        )
    value = (
        fltparser
        | intparser
        | nameparser
        )
    term = value | group
    return (
        # unaryexprparser(term)
        # binexprparser(term)
        cmpexprparser(term)
        # | boolexprparser(term)
        # | symbolexprparser(term)
        )


def groupparser():
    def cull_seps(graft):
        return graft[0] or graft[1]
    term = (strparser | exprparser())
    return Repeater(term + EnsureGraft(bltinparser(',')) ^ cull_seps)


def tildeath():
    def breakdown(tokens):
        _, _, graveexpr, _, _, body, _ = tokens
        return TildeAthLoop(graveexpr, body)
    return (
        bltinparser('~ATH')
        + bltinparser('(')
        + exprparser()
        + bltinparser(')')
        + bltinparser('{')
        + LazyGrafter(stmtparser)
        + bltinparser('}')
        ^ breakdown
        )


def condistmt():
    def brkunless(tokens):
        _, condexpr, _, body, _ = tokens
        if condexpr:
            _, condexpr, _ = condexpr
        return UnlessStmt(condexpr, body)
    def breakdown(tokens):
        _, _, condexpr, _, _, truebody, _, unlesses = tokens
        return WhenStmt(condexpr, truebody, unlesses)
    return (
        bltinparser('WHEN')
        + bltinparser('(')
        + exprparser()
        + bltinparser(')')
        + bltinparser('{')
        + LazyGrafter(stmtparser)
        + bltinparser('}')
        + EnsureGraft(
            Repeater(
                bltinparser('UNLESS')
                + EnsureGraft(
                    bltinparser('(')
                    + exprparser()
                    + bltinparser(')')
                    )
                + bltinparser('{')
                + LazyGrafter(stmtparser)
                + bltinparser('}')
                ^ brkunless
                )
            )
        ^ breakdown
        )


def fabristmt():
    def cull_seps(graft):
        return graft[0] or graft[1]
    argparser = Repeater(nameparser + EnsureGraft(bltinparser(',')) ^ cull_seps)

    def breakdown(tokens):
        _, name, _, args, _, _, body, _ = tokens
        return FabricateStmt(name, args, body)

    return (
        bltinparser('FABRICATE')
        + nameparser
        + bltinparser('(')
        + argparser
        + bltinparser(')')
        + bltinparser('{')
        + LazyGrafter(stmtparser)
        + bltinparser('}')
        ^ breakdown
        )


def execstmt():
    def breakdown(tokens):
        return ExecuteStmt(tokens[2])
    return (
        bltinparser('EXECUTE')
        + bltinparser('(')
        + groupparser()
        + bltinparser(')')
        + bltinparser(';')
        )


def procrstmt():
    def breakdown(tokens):
        _, name, expr, _ = tokens
        if not expr:
            expr = VarExpr('NULL')
        return ProcreateStmt(name, expr)
    return (
        bltinparser('PROCREATE')
        + nameparser
        + EnsureGraft(exprparser())
        + bltinparser(';')
        ^ breakdown
        )


def replistmt():
    def breakdown(tokens):
        _, name, expr, _ = tokens
        return ReplicateStmt(name, expr)
    return (
        bltinparser('REPLICATE')
        + nameparser
        + exprparser()
        + bltinparser(';')
        ^ breakdown)


def inputstmt():
    def breakdown(tokens):
        _, name, prompt, _ = tokens
        return InputStmt(name, prompt)
    return (
        bltinparser('input')
        + nameparser
        + EnsureGraft(strparser | nameparser)
        + bltinparser(';')
        ^ breakdown
        )


def printfunc():
    def breakdown(tokens):
        return PrintFunc(tokens[2])
    return (
        bltinparser('print')
        + bltinparser('(')
        + groupparser()
        + bltinparser(')')
        + bltinparser(';')
        ^ breakdown
        )


def killfunc():
    def breakdown(tokens):
        name, _, _, _, args, _, _ = tokens
        return KillFunc(name, args)
    return (
        nameparser
        + bltinparser('.')
        + bltinparser('DIE')
        + bltinparser('(')
        + groupparser()
        + bltinparser(')')
        + bltinparser(';')
        ^ breakdown
        )


def bfctstmt():
    def breakdown(tokens):
        _, name, _, lname, _, rname, _, _ = tokens
        return BifurcateStmt(name, lname, rname)
    return (
        bltinparser('BIFURCATE')
        + nameparser
        + bltinparser('[')
        + nameparser
        + bltinparser(',')
        + nameparser
        + bltinparser(']')
        + bltinparser(';')
        ^ breakdown
        )


def aggrstmt():
    def breakdown(tokens):
        _, _, lname, _, rname, _, name, _ = tokens
        return AggregateStmt(lname, rname, name)
    return (
        bltinparser('AGGREGATE')
        + bltinparser('[')
        + exprparser()
        + bltinparser(',')
        + exprparser()
        + bltinparser(']')
        + nameparser
        + bltinparser(';')
        ^ breakdown
        )


def stmtparser():
    stmts = (
        replistmt()
        | procrstmt()
        | bfctstmt()
        | aggrstmt()
        | killfunc()
        # | execstmt()
        | printfunc()
        | inputstmt()
        | tildeath()
        # | fabristmt()
        | condistmt()
        )
    return Repeater(stmts) ^ Serialize


class BuiltinSymbol(AthSymbol):
    __slots__ = ()

    def assign_left(self, value):
        raise SymbolError('Builtins cannot be assigned to!')

    def assign_right(self, value):
        raise SymbolError('Builtins cannot be assigned to!')

    def inop(self, other, op):
        raise SymbolError('Builtins cannot be assigned to!')


class AthStackFrame(object):
    """Keeps a record of all symbols declared in a given scope.
    ~ATH implements dynamic scope, so be wary when coding in it!
    """
    __slots__ = ('scope_vars',)
    global_vars = {
        'DIE': BuiltinSymbol(),
        'WHEN': BuiltinSymbol(),
        'UNLESS': BuiltinSymbol(),
        'ATH': BuiltinSymbol(),
        'print': BuiltinSymbol(),
        'input': BuiltinSymbol(),
        'import': BuiltinSymbol(),
        'EXECUTE': BuiltinSymbol(),
        'DIVULGATE': BuiltinSymbol(),
        'BIFURCATE': BuiltinSymbol(),
        'AGGREGATE': BuiltinSymbol(),
        'PROCREATE': BuiltinSymbol(),
        'FABRICATE': BuiltinSymbol(),
        'REPLICATE': BuiltinSymbol(),
        'THIS': BuiltinSymbol(),
        'NULL': BuiltinSymbol(False),
        }

    def __init__(self):
        self.scope_vars = {}

    def __getitem__(self, name):
        try:
            return self.scope_vars[name]
        except KeyError:
            return None

    def __setitem__(self, name, value=None):
        try:
            self.global_vars[name]
        except KeyError:
            pass
        else:
            raise SymbolError('Builtins cannot be assigned to!')

        if value is None:
            value = AthSymbol(True)
        self.scope_vars[name] = value


class TildeAthInterp(object):
    """This is supposed to be a Finite State Machine"""
    __slots__ = ()
    stack = [AthStackFrame()]
    script_parser = StrictGrafter(stmtparser())

    def lookup_name(self, name):
        try:
            return self.stack[0].global_vars[name]
        except KeyError:
            pass
        for frame in reversed(self.stack):
            value = frame[name]
            if value is not None:
                # print('{} found'.format(name))
                return value
        raise NameError('Symbol {} does not exist.'.format(name))

    def assign_name(self, name, value):
        # print('{} assigned'.format(name))
        self.stack[-1][name] = value

    def push_stack(self):
        self.stack.append(AthStackFrame())

    def pop_stack(self):
        if len(self.stack) > 1:
            return self.stack.pop()
        else:
            raise RuntimeError('May not pop global stack')

    def execute(self, script):
        tokens = ath_lexer.lex(script)
        result = self.script_parser(tokens, 0)
        if result:
            try:
                result.value.eval(self)
            except EndTilDeath:
                raise SystemExit
            finally:
                for frame in self.stack:
                    print(frame.scope_vars)
        else:
            raise RuntimeError('Something messed up!')
