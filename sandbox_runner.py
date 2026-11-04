# sandbox_runner.py
import contextlib
import os
import subprocess
import sys
import tempfile
import threading
from typing import TypedDict


class SandboxResult(TypedDict):
    passed: bool
    stdout: str
    stderr: str
    exit_code: int
    backend: str


# ============================================================================
# 1. MODAL DEFINITIONS
# ============================================================================

try:
    import modal

    MODAL_INSTALLED = True
except ImportError:
    modal = None
    MODAL_INSTALLED = False

if MODAL_INSTALLED:
    app = modal.App("podai-sandbox-runner")
    image = modal.Image.debian_slim(python_version="3.11").pip_install(
        "pytest>=8.0.0",
        "pydantic>=2.0.0",
        "fastapi>=0.110.0",
        "httpx>=0.27.0",
    )

    @app.function(image=image, timeout=60)
    def _modal_remote_runner(payload: dict) -> dict:
        import os
        import subprocess
        import tempfile

        files_map = payload.get("files", {})
        cmd = payload.get("test_command", "pytest")

        with tempfile.TemporaryDirectory(prefix="modal_ws_") as tmpdir:
            for rel_path, content in files_map.items():
                target = os.path.join(tmpdir, rel_path)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(content)

            env = os.environ.copy()
            env["PYTHONPATH"] = (
                f"{tmpdir}:{env.get('PYTHONPATH', '')}".rstrip(":")
            )

            res = subprocess.run(
                cmd,
                shell=True,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env=env,
            )
            return {
                "passed": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
            }


_modal_session_active = False
_modal_lock = threading.Lock()


@contextlib.contextmanager
def sandbox_session(backend: str = "modal"):
    """Maintains a warm Modal execution session across all parallel worker threads."""
    global _modal_session_active
    target_backend = (
        backend or os.getenv("SANDBOX_BACKEND", "modal")
    ).lower().strip()

    if target_backend == "modal" and MODAL_INSTALLED and app is not None:
        with _modal_lock:
            if _modal_session_active:
                yield
                return
            _modal_session_active = True
        try:
            with app.run():
                yield
        finally:
            with _modal_lock:
                _modal_session_active = False
    else:
        yield


def _verify_modal(
    files: dict[str, str], test_command: str, timeout: int = 60
) -> SandboxResult:
    """Dispatches verification to Modal."""
    global _modal_session_active

    if _modal_session_active:
        output = _modal_remote_runner.remote(
            {"files": files, "test_command": test_command}
        )
    else:
        with _modal_lock:
            with app.run():
                output = _modal_remote_runner.remote(
                    {"files": files, "test_command": test_command}
                )

    return {
        "passed": output["passed"],
        "stdout": output["stdout"],
        "stderr": output["stderr"],
        "exit_code": output["exit_code"],
        "backend": "modal_micro_vm",
    }


# ============================================================================
# 2. LOCAL SUBPROCESS RUNNER (Fallback)
# ============================================================================


def _verify_local(
    files: dict[str, str], test_command: str, timeout: int = 45
) -> SandboxResult:
    with tempfile.TemporaryDirectory(prefix="podai_sandbox_") as tmpdir:
        for rel_path, content in files.items():
            full_path = os.path.join(tmpdir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

        env = os.environ.copy()
        venv_bin = os.path.dirname(sys.executable)
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        env["PYTHONPATH"] = (
            f"{tmpdir}:{env.get('PYTHONPATH', '')}".rstrip(":")
        )

        cmd = test_command
        if cmd.strip().startswith("pytest"):
            cmd = f'"{sys.executable}" -m ' + cmd.strip()

        try:
            process = subprocess.run(
                cmd,
                shell=True,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
            return {
                "passed": process.returncode == 0,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "exit_code": process.returncode,
                "backend": "local_subprocess",
            }
        except Exception as e:
            return {
                "passed": False,
                "stdout": "",
                "stderr": f"Local runner exception: {str(e)}",
                "exit_code": -1,
                "backend": "local_subprocess",
            }


# ============================================================================
# 3. UNIFIED DRIVER INTERFACE
# ============================================================================


def run_sandbox_verification(
    files: dict[str, str],
    test_command: str,
    backend: str | None = None,
    timeout: int = 45,
) -> SandboxResult:
    target_backend = (
        backend or os.getenv("SANDBOX_BACKEND", "modal")
    ).lower().strip()

    if target_backend == "modal":
        try:
            return _verify_modal(files, test_command, timeout=timeout)
        except Exception as e:
            print(
                f"[WARNING] Modal execution failed ({e}). Falling back to local sandbox."
            )
            return _verify_local(files, test_command, timeout=timeout)

    return _verify_local(files, test_command, timeout=timeout)