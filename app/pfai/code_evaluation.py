from __future__ import annotations
import ast
from dataclasses import dataclass

@dataclass(frozen=True)
class CodeEvalResult:
    passed: bool
    syntax_ok: bool
    unsafe_imports: tuple[str, ...]
    score: float
    details: dict

class PythonCodeEvaluator:
    """Strict static safety pre-filter for generated Python.

    This is not a kernel/container security boundary. It blocks dangerous
    imports and common dynamic escape primitives before code reaches the
    disposable resource-limited subprocess used by SandboxedCodeEvaluator.
    """
    DEFAULT_ALLOWED_IMPORTS = frozenset({
        'abc','array','bisect','collections','copy','dataclasses','datetime',
        'decimal','enum','fractions','functools','heapq','itertools','json',
        'math','operator','random','re','statistics','string','textwrap','typing',
        'unicodedata',
    })
    DEFAULT_BLOCKED_CALLS = frozenset({
        '__import__','eval','exec','compile','open','input','breakpoint',
        'globals','locals','vars','getattr','setattr','delattr',
    })
    DEFAULT_BLOCKED_ATTRIBUTES = frozenset({
        '__class__','__mro__','__bases__','__base__','__subclasses__',
        '__globals__','__builtins__','__loader__','__spec__','__import__',
    })

    def __init__(self, blocked_imports=('subprocess','os','shutil','socket','ctypes'),
                 allowed_imports=None, blocked_calls=None, blocked_attributes=None):
        self.blocked=set(blocked_imports)
        self.allowed_imports=set(allowed_imports or self.DEFAULT_ALLOWED_IMPORTS)
        self.blocked_calls=set(blocked_calls or self.DEFAULT_BLOCKED_CALLS)
        self.blocked_attributes=set(blocked_attributes or self.DEFAULT_BLOCKED_ATTRIBUTES)

    def evaluate(self, code: str) -> CodeEvalResult:
        try:
            tree=ast.parse(code)
        except SyntaxError as exc:
            return CodeEvalResult(False,False,(),0.0,{'error':str(exc)})
        bad=set(); primitives=set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root=alias.name.split('.')[0]
                    if root in self.blocked or root not in self.allowed_imports:
                        bad.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root=node.module.split('.')[0]
                if root in self.blocked or root not in self.allowed_imports:
                    bad.add(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.blocked_calls:
                primitives.add(f'call:{node.func.id}')
            elif isinstance(node, ast.Attribute) and node.attr in self.blocked_attributes:
                primitives.add(f'attribute:{node.attr}')
            elif isinstance(node, ast.Name) and node.id in {'__builtins__','__loader__','__spec__','__package__'}:
                primitives.add(f'name:{node.id}')
        unsafe=tuple(sorted(bad | primitives))
        structure=.25 if any(isinstance(n,(ast.FunctionDef,ast.ClassDef)) for n in ast.walk(tree)) else 0.0
        assertions=.25 if any(isinstance(n,ast.Assert) for n in ast.walk(tree)) else 0.0
        docstrings=.10 if any(isinstance(n,ast.Expr) and isinstance(getattr(n,'value',None),ast.Constant) and isinstance(n.value.value,str) for n in ast.walk(tree)) else 0.0
        safety=.40 if not unsafe else 0.0
        score=min(1.0,structure+assertions+docstrings+safety)
        return CodeEvalResult(not unsafe,True,unsafe,score,{
            'functions_or_classes':structure>0,'assertions':assertions>0,'docstrings':docstrings>0,
            'blocked_primitives':sorted(primitives),
        })
