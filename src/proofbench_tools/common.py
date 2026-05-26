from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_REMOTE_SIMPLE_API_BASE_URLS: tuple[str, ...] = ()

DEFAULT_OFFICIAL_STAGE2_PROOF_POLICY: dict[str, list[str]] = {
    "allowed_axioms": ["propext", "Quot.sound", "Classical.choice"],
    "allowed_declarations": ["letFun"],
    "allowed_declaration_prefixes": [
        "And.",
        "Bool.",
        "Classical.",
        "Decidable.",
        "Eq.",
        "EquationLHS",
        "EquationRHS",
        "Goal",
        "Exists.",
        "False.",
        "Fin.",
        "Fintype.",
        "Function.",
        "HEq.",
        "Iff.",
        "Init.",
        "Int.",
        "Lean.",
        "List.",
        "Magma.",
        "Mathlib.",
        "MemoFinOp.",
        "Nat.",
        "Nonempty.",
        "Not.",
        "NthRewrites.",
        "OfNat.",
        "Option.",
        "Or.",
        "Prod.",
        "PUnit.",
        "RewriteCombinations.",
        "RewriteGoal.",
        "RewriteHypothesis.",
        "RewriteHypothesisAndGoal.",
        "SimpleRewrites.",
        "Std.",
        "Subgraph.",
        "Subtype.",
        "Sum.",
        "Trans.",
        "True.",
        "Unit.",
        "JudgeDecide.",
        "JudgeFinOp.",
        "JudgeMagma.",
        "inst",
        "of_decide_",
        "submission.",
        "congrArg",
        "congr_arg",
        "eq_self",
        "of_eq_true",
        "id",
        "eq_comm",
        "eq_mp",
        "eq_mpr",
        "rfl",
        "absurd",
    ],
}


@dataclass(frozen=True)
class Expr:
    kind: str
    value: str | None = None
    left: "Expr | None" = None
    right: "Expr | None" = None

    @staticmethod
    def var(name: str) -> "Expr":
        return Expr("var", value=name)

    @staticmethod
    def mul(left: "Expr", right: "Expr") -> "Expr":
        return Expr("mul", left=left, right=right)

    def variables(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []

        def visit(expr: Expr) -> None:
            if expr.kind == "var":
                assert expr.value is not None
                if expr.value not in seen:
                    seen.add(expr.value)
                    ordered.append(expr.value)
                return
            assert expr.left is not None and expr.right is not None
            visit(expr.left)
            visit(expr.right)

        visit(self)
        return ordered

    def variable_names(self) -> set[str]:
        return set(self.variables())

    def to_tuple(self) -> tuple[Any, ...]:
        if self.kind == "var":
            return ("var", self.value)
        assert self.left is not None and self.right is not None
        return ("mul", self.left.to_tuple(), self.right.to_tuple())


@dataclass(frozen=True)
class Equation:
    left: Expr
    right: Expr

    def variables(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for expr in (self.left, self.right):
            for variable in expr.variables():
                if variable not in seen:
                    seen.add(variable)
                    ordered.append(variable)
        return ordered


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize_equation_text(text)
        self.index = 0

    def parse_expr(self) -> Expr:
        expr = self.parse_atom()
        while self._peek() == "*":
            self.index += 1
            expr = Expr.mul(expr, self.parse_atom())
        return expr

    def parse_atom(self) -> Expr:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        if token == "(":
            self.index += 1
            expr = self.parse_expr()
            self._expect(")")
            return expr
        if token.isidentifier():
            self.index += 1
            return Expr.var(token)
        raise ValueError(f"unexpected token {token!r}")

    def finish(self) -> None:
        if self.index != len(self.tokens):
            raise ValueError(f"unparsed tokens: {self.tokens[self.index:]!r}")

    def _peek(self) -> str | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def _expect(self, token: str) -> None:
        actual = self._peek()
        if actual != token:
            raise ValueError(f"expected {token!r}, got {actual!r}")
        self.index += 1


def _tokenize_equation_text(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "()*":
            tokens.append(char)
            index += 1
            continue
        if char == "\u25c7":
            tokens.append("*")
            index += 1
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] == "_"):
                index += 1
            tokens.append(text[start:index])
            continue
        raise ValueError(f"unexpected character {char!r} in {text!r}")
    return tokens


def parse_equation(text: str) -> Equation:
    parts = text.split("=", 1)
    if len(parts) != 2:
        raise ValueError(f"equation has no '=': {text!r}")
    left = _Parser(parts[0].strip())
    left_expr = left.parse_expr()
    left.finish()
    right = _Parser(parts[1].strip())
    right_expr = right.parse_expr()
    right.finish()
    return Equation(left_expr, right_expr)


def lean_expr(expr: Expr, *, top: bool = False) -> str:
    if expr.kind == "var":
        assert expr.value is not None
        return expr.value
    assert expr.left is not None and expr.right is not None
    text = f"{lean_expr(expr.left)} \u25c7 {lean_expr(expr.right)}"
    return text if top else f"({text})"


def eval_expr(expr: Expr, assignment: dict[str, int], table: Sequence[Sequence[int]]) -> int:
    if expr.kind == "var":
        assert expr.value is not None
        return assignment[expr.value]
    assert expr.left is not None and expr.right is not None
    left = eval_expr(expr.left, assignment, table)
    right = eval_expr(expr.right, assignment, table)
    return int(table[left][right])


def equation_holds_for_assignment(
    equation: Equation,
    assignment: dict[str, int],
    table: Sequence[Sequence[int]],
) -> bool:
    return eval_expr(equation.left, assignment, table) == eval_expr(
        equation.right,
        assignment,
        table,
    )


def all_assignments(equation: Equation, order: int) -> Iterable[dict[str, int]]:
    variables = equation.variables()
    for values in product(range(order), repeat=len(variables)):
        yield dict(zip(variables, values, strict=True))


def table_satisfies(equation: Equation, table: Sequence[Sequence[int]]) -> bool:
    order = len(table)
    return all(
        equation_holds_for_assignment(equation, assignment, table)
        for assignment in all_assignments(equation, order)
    )


def table_refutes(equation: Equation, table: Sequence[Sequence[int]]) -> bool:
    order = len(table)
    return any(
        not equation_holds_for_assignment(equation, assignment, table)
        for assignment in all_assignments(equation, order)
    )


def validate_countermodel(
    source_equation: str,
    target_equation: str,
    table: Sequence[Sequence[int]],
) -> tuple[bool, bool]:
    source = parse_equation(source_equation)
    target = parse_equation(target_equation)
    return table_satisfies(source, table), table_refutes(target, table)


def false_certificate_code(table: Sequence[Sequence[int]]) -> str:
    order = len(table)
    table_json = json.dumps([list(row) for row in table], separators=(",", ":"))
    return (
        "import JudgeProblem\n"
        "import JudgeDecide.DecideBang\n"
        "import JudgeFinOp.MemoFinOp\n"
        "set_option maxRecDepth 1000000\n"
        "open MemoFinOp\n\n"
        "def submission : Goal := by\n"
        f"  let m : Magma (Fin {order}) := {{\n"
        f"    op := finOpTable \"{table_json}\"\n"
        "  }\n"
        f"  refine \u27e8Fin {order}, m, ?_\u27e9\n"
        "  decideFin!\n"
    )


def true_certificate_code(proof_body: str) -> str:
    lines = proof_body.strip().splitlines()
    non_empty = [line for line in lines if line.strip()]
    if non_empty:
        min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
        lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]
    indented = "\n".join("  " + line if line.strip() else "" for line in lines)
    return (
        "import JudgeProblem\n"
        "set_option linter.unusedVariables false\n\n"
        "def submission : Goal := by\n"
        "  intro G _ h\n"
        f"{indented}\n"
    )


def answer_with_code(verdict: str, code: str) -> dict[str, Any]:
    return {
        "call": "judge",
        "verdict": verdict,
        "code": code,
    }


def code_sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def table_sha256(table: Sequence[Sequence[int]]) -> str:
    payload = json.dumps([list(row) for row in table], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        handle.flush()


def ensure_official_stage2_problem_defaults(problem: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(problem)
    if not normalized.get("proof_policy"):
        normalized["proof_policy"] = {
            key: list(value)
            for key, value in DEFAULT_OFFICIAL_STAGE2_PROOF_POLICY.items()
        }
    return normalized


def extract_answer(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("answer", "judge_call"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    if {"verdict", "code"} <= row.keys():
        answer = {
            "call": "judge",
            "verdict": row["verdict"],
            "code": row["code"],
        }
        return answer
    raise ValueError(f"candidate row {row.get('id')!r} has no answer/judge_call/verdict+code")


def build_judge_rows(
    problems: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    *,
    id_field: str = "id",
) -> list[dict[str, Any]]:
    problem_by_id = {str(problem[id_field]): problem for problem in problems}
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        problem_id = str(candidate.get(id_field) or "")
        if not problem_id:
            raise ValueError("candidate row missing id")
        problem = problem_by_id.get(problem_id)
        if problem is None:
            raise ValueError(f"candidate id {problem_id!r} not found in problems")
        answer = extract_answer(candidate)
        rows.append(
            {
                "id": problem_id,
                "problem": ensure_official_stage2_problem_defaults(problem),
                "answer": answer,
                "candidate_metadata": {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"answer", "judge_call", "code", "verdict"}
                },
            }
        )
    return rows
