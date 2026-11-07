"""One Java source renderer for statement and expression IR (audit C1).

``JavaGenerator`` (native/plain Java) and ``SpringBootGenerator`` each carried
a ~200-line copy of the same statement/expression rendering; the copies had
already drifted (cast style, ``if`` condition grouping, nested-line handling,
typed assignments, ``throw``). Both now inherit this renderer. The remaining
differences are explicit class options, each one preserving exactly the
output that generator produced before (proven by a byte-identical generated
corpus), so a fix to shared rendering now reaches every runtime at once.
"""
from __future__ import annotations

import re

from engine.transformation.java_ir import JavaBasicType

_JAVA_LITERAL_SUFFIX_RE = re.compile(r"^[+-]?\d+[Ll]$")



def _wrapped_in_one_pair(text: str) -> bool:
    """True when the first ``(`` of ``text`` is closed by its last character (``(a) || (b)`` is not wrapped)."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index == len(text) - 1
    return False


class JavaSourceRenderer:
    """Renders Java IR statements and expressions to Java source text."""

    #: ``JavaAssignment.java_type`` renders a typed declaration-assignment.
    render_typed_assignment: bool = False
    #: ``JavaThrow`` is rendered (otherwise it is an unmapped statement).
    render_throw: bool = False
    #: ``if ((a > b))`` -> ``if (a > b)``: drop the condition's outer group.
    strip_if_condition_parens: bool = False
    #: Multi-line statements nested in ``if``/``else`` are indented per line
    #: and empty renderings are skipped (otherwise appended as one string).
    split_nested_if_lines: bool = False
    #: ``(T) x`` instead of ``(T)(x)``.
    spaced_cast: bool = False

    @staticmethod
    def _escape_java_string(value: str) -> str:
        """Escape a raw string value for embedding in a Java string literal.

        Control bytes are escaped too: ``MOVE LOW-VALUE`` fills the
        receiver with NUL and ``MOVE HIGH-VALUE`` with 0xFF, and a raw
        control byte in generated source is rejected by ``javac`` (or
        corrupted by a non-UTF-8 reader) instead of being a legal character
        in a string literal.
        """
        return (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
            .replace("\x00", "\\u0000")
            .replace("\xff", "\\u00ff")
        )

    def _nested(self, statements) -> list[str]:
        """Body lines of an if/else branch, per ``split_nested_if_lines``."""
        lines: list[str] = []
        for s in statements:
            if self.split_nested_if_lines:
                inner = self._stmt_to_string(s)
                if inner:
                    for inner_line in inner.split("\n"):
                        lines.append(f"    {inner_line}")
            else:
                lines.append(f"    {self._stmt_to_string(s)}")
        return lines

    def _indented_body(self, statements) -> list[str]:
        lines: list[str] = []
        for s in statements:
            inner = self._stmt_to_string(s)
            if inner:
                for inner_line in inner.split("\n"):
                    lines.append(f"    {inner_line}")
        return lines

    def _stmt_to_string(self, stmt) -> str:
        """Convert a Java IR statement to a Java source string."""
        from engine.transformation.java_ir import (
            JavaAssignment, JavaMethodCallStatement, JavaReturn,
            JavaComment, JavaIf, JavaBlock, JavaWhile, JavaDoWhile,
            JavaFor, JavaThrow, JavaLocalVarDecl, JavaBreak,
        )
        if isinstance(stmt, JavaAssignment):
            expr_str = self._expr_to_string(stmt.expression)
            if self.render_typed_assignment and stmt.java_type:
                return f"{stmt.java_type.to_source()} {stmt.target} = {expr_str};"
            return f"{stmt.target} = {expr_str};"
        if isinstance(stmt, JavaLocalVarDecl):
            init_str = ""
            if stmt.initializer:
                init_str = f" = {self._expr_to_string(stmt.initializer)}"
            return f"{stmt.java_type.to_source()} {stmt.name}{init_str};"
        if isinstance(stmt, JavaMethodCallStatement):
            return self._method_call_to_string(stmt.call) + ";"
        if isinstance(stmt, JavaReturn):
            if stmt.expression:
                return f"return {self._expr_to_string(stmt.expression)};"
            return "return;"
        if isinstance(stmt, JavaComment):
            return f"// {stmt.text}"
        if isinstance(stmt, JavaBreak):
            return "break;"
        if self.render_throw and isinstance(stmt, JavaThrow):
            if stmt.message:
                return f'throw new {stmt.exception_class}("{stmt.message}");'
            return f"throw new {stmt.exception_class}();"
        if isinstance(stmt, JavaIf):
            cond = self._expr_to_string(stmt.condition)
            if self.strip_if_condition_parens and _wrapped_in_one_pair(cond):
                cond = cond[1:-1]
            lines = [f"if ({cond}) {{"]
            lines.extend(self._nested(stmt.then_body))
            if stmt.else_body:
                lines.append("} else {")
                lines.extend(self._nested(stmt.else_body))
            lines.append("}")
            return "\n".join(lines)
        if isinstance(stmt, JavaDoWhile):
            cond = self._expr_to_string(stmt.condition)
            lines = ["do {", *self._indented_body(stmt.body), f"}} while ({cond});"]
            return "\n".join(lines)
        if isinstance(stmt, JavaFor):
            init_str = self._stmt_to_string(stmt.init).rstrip(";") if stmt.init else ""
            cond_str = self._expr_to_string(stmt.condition) if stmt.condition else ""
            update_str = self._stmt_to_string(stmt.update).rstrip(";") if stmt.update else ""
            lines = [f"for ({init_str}; {cond_str}; {update_str}) {{",
                     *self._indented_body(stmt.body), "}"]
            return "\n".join(lines)
        if isinstance(stmt, JavaBlock):
            if stmt.scoped:
                return "\n".join(["{", *self._indented_body(stmt.statements), "}"])
            return "\n".join(self._stmt_to_string(s) for s in stmt.statements)
        if isinstance(stmt, JavaWhile):
            cond = self._expr_to_string(stmt.condition)
            lines = [f"while ({cond}) {{", *self._indented_body(stmt.body), "}"]
            return "\n".join(lines)
        raise ValueError(
            "MISSING_REQUIRED_SEMANTIC: Java statement type "
            f"{type(stmt).__name__} has no generator mapping."
        )

    def _expr_to_string(self, expr) -> str:
        """Convert a Java IR expression to a Java source string."""
        from engine.transformation.java_ir import (
            JavaCast, JavaLiteral, JavaVariableRef, JavaBinaryOp, JavaMethodCall,
            JavaStringConcat, JavaTernary, JavaUnaryOp,
            JavaArrayAccess, JavaNewArray, JavaFilledArray, JavaNewObject,
            JavaUnsupportedExpression,
        )
        if isinstance(expr, JavaUnsupportedExpression):
            raise ValueError(
                "UNSUPPORTED_COBOL_EXPRESSION: "
                f"{expr.reason}; source={expr.source_expression!r}"
            )
        if isinstance(expr, JavaLiteral):
            if expr.value == "null" and not expr.java_type:
                return "null"
            if expr.value in ("true", "false") and not expr.java_type:
                return expr.value
            if (
                expr.java_type
                and expr.java_type.basic_type == JavaBasicType.DECIMAL
            ):
                # Decimal-exact literal: a string constructor preserves the
                # exact digits/scale of the COBOL literal (never a double).
                return (
                    f'new java.math.BigDecimal('
                    f'"{self._escape_java_string(expr.value)}")'
                )
            # String literals need quotes; numeric literals don't
            # JavaLiteral without java_type may be a condition expression — don't quote
            if expr.java_type and expr.java_type.basic_type and \
               expr.java_type.basic_type.value == "String":
                return f'"{self._escape_java_string(expr.value)}"'
            # A single-quoted value is a COBOL string literal spelling, not a
            # Java char: normalize to a double-quoted Java string literal.
            if len(expr.value) >= 2 and expr.value.startswith("'") and expr.value.endswith("'"):
                return f'"{self._escape_java_string(expr.value[1:-1])}"'
            # If it looks like a string value (not a number, not a condition)
            if not expr.value.replace(".", "").replace("-", "").isdigit() and not (
                _JAVA_LITERAL_SUFFIX_RE.match(expr.value)
            ):
                # Check if it's a condition expression (contains operators)
                if any(op in expr.value for op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||")):
                    return expr.value  # Don't quote conditions
                if not expr.value.startswith('"'):
                    return f'"{self._escape_java_string(expr.value)}"'
            return expr.value
        if isinstance(expr, JavaVariableRef):
            return expr.name
        if isinstance(expr, JavaArrayAccess):
            return (
                f"{self._expr_to_string(expr.array)}"
                f"[{self._expr_to_string(expr.index)}]"
            )
        if isinstance(expr, JavaNewArray):
            dims = "".join(f"[{d}]" for d in expr.dimensions)
            return f"new {expr.element_type.to_source()}{dims}"
        if isinstance(expr, JavaFilledArray):
            return (
                f"java.util.Collections.nCopies({expr.length}, "
                f"{self._expr_to_string(expr.fill)})"
                f".toArray(new {expr.element_type.to_source()}[0])"
            )
        if isinstance(expr, JavaCast):
            inner = self._expr_to_string(expr.expression)
            if self.spaced_cast:
                return f"({expr.target_type.to_source()}) {inner}"
            return f"({expr.target_type.to_source()})({inner})"
        if isinstance(expr, JavaBinaryOp) and expr.operator == "**":
            raise ValueError(
                "UNSUPPORTED_COBOL_EXPRESSION: exponentiation (**) is certified only as an arithmetic receiver's "
                "expression (COMPUTE / ADD / ... over integer exponents), not in this position")
        if isinstance(expr, JavaBinaryOp):
            left = self._expr_to_string(expr.left)
            right = self._expr_to_string(expr.right)
            return f"({left} {expr.operator} {right})"
        if isinstance(expr, JavaUnaryOp):
            operand = self._expr_to_string(expr.operand)
            if any(op in operand for op in ("==", "!=", "&&", "||", ">=", "<=", "<", ">")):
                depth = 0
                grouped = False
                for i, ch in enumerate(operand):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            grouped = i == len(operand) - 1
                            break
                if not grouped:
                    operand = f"({operand})"
            return f"({expr.operator}{operand})"
        if isinstance(expr, JavaNewObject):
            args = ", ".join(self._expr_to_string(a) for a in expr.arguments)
            return f"new {expr.class_name}({args})"
        if isinstance(expr, JavaMethodCall):
            return self._method_call_to_string(expr)
        if isinstance(expr, JavaStringConcat):
            parts = []
            for p in expr.parts:
                rendered = self._expr_to_string(p)
                # If it's a JavaLiteral with no type, wrap in quotes
                if isinstance(p, JavaLiteral) and not p.java_type:
                    if not rendered.startswith('"'):
                        rendered = f'"{rendered}"'
                parts.append(rendered)
            return " + ".join(parts)
        if isinstance(expr, JavaTernary):
            # Always grouped so the ternary can nest inside concatenations
            # and method calls (STRING delimiter truncation relies on this).
            cond = self._expr_to_string(expr.condition)
            true_str = self._expr_to_string(expr.true_expr)
            false_str = self._expr_to_string(expr.false_expr)
            return f"({cond} ? {true_str} : {false_str})"
        # Fail closed (audit A6): an unrendered expression must never become
        # an empty string inside otherwise valid Java.
        raise ValueError(
            "MISSING_REQUIRED_SEMANTIC: no Java rendering for expression "
            f"{type(expr).__name__}"
        )

    def _method_call_to_string(self, call) -> str:
        """Convert a Java IR method call to a Java source string."""
        from engine.transformation.java_ir import JavaStringConcat

        args = ", ".join(self._expr_to_string(a) for a in call.arguments)
        if call.is_static:
            return f"{call.class_name}.{call.method_name}({args})"
        if call.object_ref:
            obj = self._expr_to_string(call.object_ref)
            if isinstance(call.object_ref, JavaStringConcat):
                # ``a + b.length()`` would bind the method to the last
                # operand only; group the receiver so ``(a + b).length()``
                # keeps its meaning (STRING pointer/tail arithmetic).
                obj = f"({obj})"
            return f"{obj}.{call.method_name}({args})"
        return f"{call.method_name}({args})"
