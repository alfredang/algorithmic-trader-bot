"""Subprocess entry point for the custom-strategy sandbox (see sandbox.py). Reads JSON on stdin."""
from __future__ import annotations

import builtins
import io
import json
import sys
import traceback


def _limits(memory_mb: int, cpu_s: int) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        if sys.platform != "darwin":           # macOS does not enforce RLIMIT_AS reliably
            b = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except Exception:
        pass


SAFE_BUILTINS = {k: getattr(builtins, k) for k in ["abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "isinstance", "issubclass", "len", "list", "map", "max", "min", "print", "range", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip", "super", "object", "property", "staticmethod", "classmethod", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError", "Exception", "NotImplementedError", "RuntimeError", "ArithmeticError", "hasattr", "divmod", "pow", "repr", "hash", "iter", "next", "format", "frozenset", "complex", "bytes", "True", "False", "None"] if hasattr(builtins, k)}


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    from trader.strategies.sandbox import _module_allowed
    if not _module_allowed(name):
        raise ImportError(f"import of '{name}' is not allowed in the strategy sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


def main() -> None:
    payload = json.loads(sys.stdin.read())
    _limits(payload.get("memory_mb", 1024), payload.get("cpu_s", 30))
    import pandas as pd

    from trader.strategies.base import Strategy

    frames = {}
    for sym, js in payload["data"].items():
        df = pd.read_json(io.StringIO(js), orient="split")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        tz = payload.get("tz", {}).get(sym)
        df.index = df.index.tz_convert(tz) if tz else df.index.tz_localize(None)
        frames[sym] = df
    sb = dict(SAFE_BUILTINS)
    sb["__import__"] = _import
    sb["__build_class__"] = builtins.__build_class__
    g = {"__builtins__": sb, "__name__": "user_strategy"}
    exec(compile(payload["code"], "<strategy>", "exec"), g)
    classes = [v for v in g.values() if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy
               and v.__module__ == "user_strategy"]
    if not classes:
        raise ValueError("no Strategy subclass found")
    cls = classes[-1]
    inst = cls(**payload.get("params", {}))
    data = frames if payload["multi"] else frames["__single__"]
    sig = inst.run(data)
    ref = next(iter(frames.values())).index
    sig = sig.reindex(ref).fillna(0.0)
    multi = isinstance(sig, pd.DataFrame)
    idx = [t.isoformat() for t in sig.index]
    if multi:
        sig_js = {"index": idx, "columns": list(sig.columns), "data": sig.fillna(0.0).values.tolist()}
    else:
        sig_js = {"index": idx, "data": [float(x) for x in sig.fillna(0.0).values]}
    meta = {"name": cls.name, "class_name": cls.__name__, "params_schema": cls.schema_dict(),
            "default_params": inst.values, "multi_asset": bool(cls.multi_asset), "allow_short": bool(cls.allow_short),
            "doc": (cls.__doc__ or "").strip()}
    print(json.dumps({"ok": True, "multi": multi, "signals": sig_js, "meta": meta}))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:               # report every failure as JSON
        tb = traceback.format_exc(limit=3)
        msg = f"{type(exc).__name__}: {exc}"
        if "<strategy>" in tb:
            lines = [ln for ln in tb.splitlines() if "<strategy>" in ln]
            msg += f" ({lines[-1].strip()})" if lines else ""
        print(json.dumps({"ok": False, "error": msg}))
