from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


LineCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool
    killed: bool
    log_file: Path | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.killed


@dataclass
class RunningProcess:
    process: subprocess.Popen[str]
    command: list[str]
    pgid: int | None = None
    log_file: Path | None = None
    started_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class KillReport:
    pid: int
    pgid: int | None
    command: tuple[str, ...] = ()
    elapsed_sec: float = 0.0
    signals: tuple[str, ...] = ()
    children: tuple[int, ...] = ()
    success: bool = False
    message: str = ""

    def to_line(self) -> str:
        signals = ", ".join(self.signals) or "nenhum"
        children = ", ".join(str(pid) for pid in self.children) or "nenhum"
        return (
            f"pid={self.pid} pgid={self.pgid} elapsed={self.elapsed_sec:.2f}s "
            f"signals={signals} children={children} success={self.success} {self.message}"
        )


class ProcessRunner:
    """Run external commands without blocking on stdout/stderr pipes."""

    _active: dict[int, RunningProcess] = {}
    _last_cancel_reports: tuple[KillReport, ...] = ()
    _lock = threading.Lock()

    @classmethod
    def run(
        cls,
        command: list[str],
        timeout_sec: int = 120,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        log_file: Path | str | None = None,
        on_line: LineCallback | None = None,
    ) -> ProcessResult:
        started = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        log_path = Path(log_file).expanduser() if log_file else None
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except Exception:
            pgid = proc.pid
        with cls._lock:
            cls._active[proc.pid] = RunningProcess(proc, command, pgid=pgid, log_file=log_path)
        if log_path:
            with log_path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"[runner] started pid={proc.pid} pgid={pgid} command={' '.join(command)}\n")

        def read_stream(name: str, stream, bucket: list[str]) -> None:
            try:
                for line in iter(stream.readline, ""):
                    bucket.append(line)
                    if log_path:
                        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
                            handle.write(f"[{name}] {line}")
                    if on_line:
                        on_line(name, line)
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        out_thread = threading.Thread(target=read_stream, args=("stdout", proc.stdout, stdout_lines), daemon=True)
        err_thread = threading.Thread(target=read_stream, args=("stderr", proc.stderr, stderr_lines), daemon=True)
        out_thread.start()
        err_thread.start()

        timed_out = False
        killed = False
        try:
            returncode = proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_report = cls.kill_process_tree(proc.pid)
            killed = kill_report.success
            cls._append_log(log_path, f"[runner] timeout kill: {kill_report.to_line()}\n")
            try:
                returncode = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                kill_report = cls.kill_process_tree(proc.pid)
                killed = kill_report.success or killed
                cls._append_log(log_path, f"[runner] timeout force kill: {kill_report.to_line()}\n")
                returncode = None
        finally:
            out_thread.join(timeout=3)
            err_thread.join(timeout=3)
            with cls._lock:
                cls._active.pop(proc.pid, None)

        elapsed = time.monotonic() - started
        if returncode is not None and returncode < 0:
            killed = True
        message = "process completed"
        if timed_out:
            message = f"timeout after {timeout_sec}s"
        elif killed:
            message = f"process killed by signal {-returncode}" if returncode is not None and returncode < 0 else "process killed"
        elif returncode != 0:
            message = f"process exited with {returncode}"
        if log_path:
            with log_path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"\n[runner] returncode={returncode} timeout={timed_out} killed={killed} elapsed={elapsed:.3f}s\n")
        return ProcessResult(
            command=tuple(command),
            returncode=returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            elapsed_sec=elapsed,
            timed_out=timed_out,
            killed=killed,
            log_file=log_path,
            message=message,
        )

    @classmethod
    def cancel_all(cls) -> int:
        with cls._lock:
            active = list(cls._active.items())
        if not active:
            cls._last_cancel_reports = (
                KillReport(pid=0, pgid=None, success=False, message="nenhum processo ativo rastreado"),
            )
            return 0
        reports: list[KillReport] = []
        count = 0
        for pid, running in active:
            report = cls.kill_process_tree(pid, running=running)
            reports.append(report)
            cls._append_log(running.log_file, f"[runner] cancel: {report.to_line()}\n")
            if report.success:
                count += 1
        cls._last_cancel_reports = tuple(reports)
        return count

    @classmethod
    def last_cancel_report_lines(cls) -> list[str]:
        return [report.to_line() for report in cls._last_cancel_reports]

    @classmethod
    def kill_process_tree(cls, pid: int, running: RunningProcess | None = None) -> KillReport:
        started_at = running.started_at if running else time.monotonic()
        command = tuple(running.command) if running else ()
        try:
            pgid = running.pgid if running and running.pgid is not None else os.getpgid(pid)
        except Exception:
            pgid = pid
        signals: list[str] = []
        children = cls._process_group_members(pgid)
        try:
            os.killpg(pgid, signal.SIGTERM)
            signals.append("SIGTERM")
        except ProcessLookupError:
            return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, False, "processo ja finalizado")
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
                signals.append("SIGTERM(pid)")
            except Exception:
                return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, False, "falha ao enviar SIGTERM")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not cls._is_alive(pid):
                return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, True, "encerrado com SIGTERM")
            time.sleep(0.1)
        try:
            os.killpg(pgid, signal.SIGKILL)
            signals.append("SIGKILL")
            return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, True, "SIGKILL enviado")
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
                signals.append("SIGKILL(pid)")
                return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, True, "SIGKILL enviado ao PID")
            except Exception:
                return KillReport(pid, pgid, command, time.monotonic() - started_at, tuple(signals), children, False, "falha ao enviar SIGKILL")

    @staticmethod
    def _append_log(log_path: Path | None, text: str) -> None:
        if not log_path:
            return
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)

    @staticmethod
    def _is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True

    @staticmethod
    def _process_group_members(pgid: int | None) -> tuple[int, ...]:
        if pgid is None:
            return ()
        try:
            proc = subprocess.run(
                ["pgrep", "-g", str(pgid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                check=False,
            )
            return tuple(int(line) for line in proc.stdout.splitlines() if line.strip().isdigit())
        except Exception:
            return ()
