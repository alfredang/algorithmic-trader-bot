"""Run user-written strategy code in a restricted subprocess.

SECURITY NOTE - read before exposing the app to anyone else.
This sandbox is designed for LOCAL, TRUSTED use (a learner on their own machine).
It reduces accidents rather than stopping a determined attacker:
  * static AST checks: only an allow-list of imports (pandas, numpy, math, statistics,
    scipy, sklearn, trader.core.*, trader.strategies.base/builtin); no dunder attribute
    access; no open/exec/eval/compile/__import__/getattr/globals/... builtins
  * a separate Python process started in isolated mode (``python -I``) with a wall-clock
    timeout and, on POSIX, CPU-time and memory limits (``resource.setrlimit``)
  * data in via stdin, signals out via stdout as JSON - the code never sees the DB or keys
    (the subprocess environment is stripped of API keys and secrets)
Do not run untrusted code from other people on a shared server.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass

import pandas as pd

from trader.config import get_settings

ALLOWED_IMPORTS = {"pandas", "numpy", "math", "statistics", "scipy", "sklearn", "dataclasses", "typing", "itertools",
                   "functools", "collections", "trader.core", "trader.strategies.base", "trader.strategies.builtin",
                   "__future__"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                "delattr", "input", "breakpoint", "help", "exit", "quit", "memoryview", "__builtins__"}
SECRET_ENV = ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL")


class SandboxError(Exception):
    pass


@dataclass
class ValidationIssue:
    line: int
    message: str


def _module_allowed(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in ALLOWED_IMPORTS)


def check_source(code: str) -> list[ValidationIssue]:
    """Static checks; an empty list means the code may be executed in the sandbox."""
    issues: list[ValidationIssue] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [ValidationIssue(e.lineno or 0, f"Syntax error: {e.msg}")]
    classes = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if not _module_allowed(a.name):
                    issues.append(ValidationIssue(node.lineno, f"import of '{a.name}' is not allowed"))
        elif isinstance(node, ast.ImportFrom):
            if not _module_allowed(node.module or ""):
                issues.append(ValidationIssue(node.lineno, f"import from '{node.module}' is not allowed"))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr != "__init__":
            issues.append(ValidationIssue(node.lineno, f"access to '{node.attr}' is not allowed"))
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            issues.append(ValidationIssue(node.lineno, f"use of '{node.id}' is not allowed"))
        elif isinstance(node, ast.ClassDef):
            bases = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}
            if bases & {"Strategy", "_MLClassifier", "_ExecutionAlgo"} or any(b.endswith("Strategy") for b in bases):
                classes += 1
                has_gen = any(isinstance(n, ast.FunctionDef) and n.name == "generate_signals" for n in node.body)
                if not has_gen and "_MLClassifier" not in bases:
                    issues.append(ValidationIssue(node.lineno, f"class {node.name} must define generate_signals(self, data)"))
    if classes == 0:
        issues.append(ValidationIssue(1, "define a class that subclasses Strategy"))
    return issues


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in SECRET_ENV)}
    env["PYTHONHASHSEED"] = "0"
    return env


def run(code: str, data, params: dict | None = None, timeout: int | None = None) -> dict:
    """Execute ``code`` against ``data`` (DataFrame or {symbol: DataFrame}) and return signals + metadata."""
    issues = check_source(code)
    if issues:
        raise SandboxError("; ".join(f"line {i.line}: {i.message}" for i in issues))
    s = get_settings()
    multi = isinstance(data, dict)
    frames = data if multi else {"__single__": data}
    payload = {"code": code, "params": params or {}, "memory_mb": s.sandbox_memory_mb,
               "cpu_s": int(timeout or s.sandbox_timeout_s), "multi": multi,
               "tz": {sym: (str(df.index.tz) if getattr(df.index, "tz", None) is not None else None)
                      for sym, df in frames.items()},
               "data": {sym: df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
                        .to_json(orient="split", date_format="iso") for sym, df in frames.items()}}
    try:
        proc = subprocess.run([sys.executable, "-I", "-m", "trader.strategies.sandbox_worker"],
                              input=json.dumps(payload), capture_output=True, text=True,
                              timeout=(timeout or s.sandbox_timeout_s) + 5, env=_clean_env())
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"strategy timed out after {timeout or s.sandbox_timeout_s} s") from exc
    out = proc.stdout.strip().splitlines()
    if not out:
        if proc.returncode and proc.returncode < 0:
            raise SandboxError(f"strategy was stopped by the sandbox (signal {-proc.returncode}): CPU-time "
                               f"limit of {timeout or s.sandbox_timeout_s} s or memory limit exceeded")
        raise SandboxError((proc.stderr or "sandbox produced no output")[-2000:])
    res = json.loads(out[-1])
    if not res.get("ok"):
        raise SandboxError(res.get("error", "unknown error"))
    if res["multi"]:
        sig = pd.DataFrame(res["signals"]["data"], columns=res["signals"]["columns"])
    else:
        sig = pd.Series(res["signals"]["data"], dtype=float)
    ref = next(iter(frames.values())).index
    if len(sig) == len(ref):
        sig.index = ref                       # the worker returns signals aligned to the input bars
    else:
        idx = pd.to_datetime(res["signals"]["index"], utc=True)
        sig.index = idx.tz_convert(ref.tz) if getattr(ref, "tz", None) is not None else idx.tz_localize(None)
    res["signals"] = sig
    return res
