import logging
import os
import shlex
import subprocess
from typing import Any

from stepyard.sdk.node import NodeContext, node

logger = logging.getLogger("stepyard_builtin.shell")


@node(name="shell.run")
def shell_run(
    command: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    shell: bool = False,
    allow_outside_project: bool = False,
    ctx: NodeContext | None = None,
) -> dict[str, Any]:
    """Runs a shell command and returns execution details (stdout, stderr, exit code).

    Args:
        command: The shell command to execute.
        cwd: The working directory for the command.  Defaults to the project
            directory.  Must be inside the project directory unless
            ``allow_outside_project`` is ``true``.
        env: Additional environment variables to inject.
        shell: Whether to run through a shell interpreter.  **Use with
            caution** - this allows arbitrary shell expansion.  Defaults to
            ``false``.
        allow_outside_project: Set to ``true`` to allow ``cwd`` outside the
            project directory.  Defaults to ``false``.

    Outputs:
        stdout: Combined standard output.
        stderr: Empty string (stderr is merged into stdout).
        code: Exit code of the command.
    """
    import sys  # noqa: PLC0415

    project_dir = os.environ.get("STEPYARD_PROJECT_DIR", os.getcwd())

    # ── Sandbox: warn on shell=True ────────────────────────────────────────────
    if shell:
        logger.warning(
            "shell.run: shell=True in step '%s' - shell interpolation is active. "
            "Prefer shell=False to reduce command-injection risk.",
            ctx.step_id if ctx else "unknown",
        )

    # ── Sandbox: restrict cwd ──────────────────────────────────────────────────
    resolved_cwd: str | None
    if cwd:
        resolved_cwd = os.path.realpath(os.path.abspath(cwd))
        project_real = os.path.realpath(os.path.abspath(project_dir))
        if not resolved_cwd.startswith(project_real) and not allow_outside_project:
            raise PermissionError(
                f"shell.run: cwd '{cwd}' is outside the project directory "
                f"'{project_dir}'. Set allow_outside_project: true to override."
            )
    else:
        resolved_cwd = os.path.realpath(os.path.abspath(project_dir))

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    exec_cmd = shlex.split(command) if not shell and isinstance(command, str) else command

    res = subprocess.Popen(  # nosec B602
        exec_cmd,
        cwd=resolved_cwd,
        env=run_env,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output = []
    try:
        if res.stdout:
            for line in res.stdout:
                sys.stderr.write(line)
                sys.stderr.flush()
                output.append(line)

        res.wait()
    except BaseException:
        res.kill()
        res.wait()
        raise

    full_output = "".join(output).strip()

    return {
        "stdout": full_output,
        "stderr": "",
        "code": res.returncode,
    }


__all__ = ["shell_run"]
