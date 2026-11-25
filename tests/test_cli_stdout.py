"""CLI girişi TextIOWrapper olmayan stdout'ta çökmez; kapı LF satır sonunu korur."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _py(kod):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")])))
    return subprocess.run([sys.executable, "-c", textwrap.dedent(kod)],
                          check=False, capture_output=True, text=True, encoding="utf-8", env=env)


def test_kapi_stringio_stdout_cikis_2():
    r = _py("""
        import io, runpy, sys
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        runpy.run_module("nobet.kapi", run_name="__main__")
    """)
    assert r.returncode == 2, r.stderr
    assert "AttributeError" not in r.stderr


def test_kapi_crlf_sarmalayici_lf_basar():
    r = _py("""
        import io, runpy, sys
        err = io.BytesIO()
        sys.stderr = io.TextIOWrapper(err, encoding="utf-8", newline="\\r\\n")
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\\r\\n")
        try:
            runpy.run_module("nobet.kapi", run_name="__main__")
        except SystemExit as e:
            sys.stderr.flush()
            data = err.getvalue()
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            print(e.code)
            print("CRLF" if b"\\r\\n" in data else "LF")
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["2", "LF"]
