"""`mascloud` — the trainer's terminal client.

    mascloud login                       sign in (Turing email + password)
    mascloud run <task_folder>           pick single/multi/multi_noplan, stream live, download
    mascloud verify-only <task_folder>   replay verification for an existing
                                          execution_logs/<target_mode>/ run --
                                          no agent re-run, just a fresh reward
    mascloud runs                        my run history (tokens + cost)
    mascloud download <run_id> [folder]  fetch the result zip (task + execution_logs)
    mascloud pull-trajectory <run_id> [folder]
                                          fetch a fresh trajectory export from
                                          the run's LIVE sandbox, mid-run --
                                          no need to wait for it to finish
    mascloud logout

No Fireworks/Daytona key ever touches this machine — only your session token.
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
import zipfile
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import session

app = typer.Typer(add_completion=False, help="MAS Cloud Run trainer client")
console = Console()

_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "execution_logs",
    "daytona_test_logs",
}

# Production control plane. Override locally with MASCLOUD_ENDPOINT if needed
# (e.g. testing against a dev server) — trainers never need to set this.
_DEFAULT_ENDPOINT = "https://mascloud.mas-cloud-run.com"


def _endpoint() -> str:
    return (
        os.environ.get("MASCLOUD_ENDPOINT")
        or session.load().get("endpoint")
        or _DEFAULT_ENDPOINT
    ).rstrip("/")


def _client(auth: bool = True, timeout: httpx.Timeout | float = 60) -> httpx.Client:
    headers = {}
    if auth:
        token = session.load().get("token")
        if not token:
            raise typer.Exit("Not logged in — run `mascloud login` first.")
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=_endpoint(), headers=headers, timeout=timeout)


def _die(resp: httpx.Response) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    console.print(f"[red]API {resp.status_code}: {detail}[/red]")
    raise typer.Exit(1)


@app.command()
def login(
    email: str = typer.Option(..., prompt="Turing email"),
    password: str = typer.Option(..., prompt=True, hide_input=True),
) -> None:
    """Authenticate and store a session token."""
    base = _endpoint()
    with httpx.Client(base_url=base, timeout=30) as c:
        resp = c.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        _die(resp)
    data = resp.json()
    session.save({"endpoint": base, "token": data["token"], "email": data["email"]})
    console.print(
        f"[green]Connected as {data['display_name']} ({data['email']}).[/green]"
    )


@app.command()
def logout() -> None:
    """Sign out and forget the local token."""
    try:
        with _client() as c:
            c.delete("/auth/logout")
    except Exception:
        pass
    session.clear()
    console.print("Signed out.")


def _zip_task(task_folder: Path) -> bytes:
    if not (task_folder / "task.toml").exists():
        raise typer.Exit(f"Task folder must contain task.toml: {task_folder}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in task_folder.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(task_folder)
            if any(part in _EXCLUDE_DIRS for part in rel.parts):
                continue
            # as_posix() forces forward slashes so a Windows trainer's zip
            # extracts correctly on the Linux server (str() would use backslashes).
            zf.write(path, arcname=(Path(task_folder.name) / rel).as_posix())
    return buf.getvalue()


# `run`'s upload deliberately strips execution_logs/ (a fresh agent run will
# produce its own). `verify-only`'s upload needs the opposite: its entire
# point is replaying against an execution_logs/<target_mode>/ folder that's
# already there, so it keeps everything `run` excludes.
_VERIFY_ONLY_EXCLUDE_DIRS = _EXCLUDE_DIRS - {"execution_logs"}


def _zip_task_including_execution_logs(task_folder: Path) -> bytes:
    if not (task_folder / "task.toml").exists():
        raise typer.Exit(f"Task folder must contain task.toml: {task_folder}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in task_folder.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(task_folder)
            if any(part in _VERIFY_ONLY_EXCLUDE_DIRS for part in rel.parts):
                continue
            zf.write(path, arcname=(Path(task_folder.name) / rel).as_posix())
    return buf.getvalue()


@app.command()
def run(
    task_folder: Path = typer.Argument(..., exists=True, file_okay=False),
    mode: str = typer.Option(
        None,
        help=(
            "single | multi | multi_noplan (prompted if omitted). multi_noplan runs "
            "the same multi-agent swarm without decomposition.yaml injected. Only "
            "one run at a time per trainer -- submit a run in each mode separately."
        ),
    ),
    download_result: bool = typer.Option(True, "--download/--no-download"),
) -> None:
    """Upload a task folder, run it in the cloud, and stream progress live."""
    if mode is None:
        mode = typer.prompt("Run mode [single/multi/multi_noplan]", default="multi")
    if mode not in {"single", "multi", "multi_noplan"}:
        raise typer.Exit("mode must be single, multi, or multi_noplan")

    console.print(f"Packaging {task_folder}…")
    zip_bytes = _zip_task(task_folder.resolve())

    # Large task folders (e.g. figure/image-heavy packs) can take well over
    # 60s to upload on a slow connection -- uncap the write timeout the same
    # way _follow()/_download() already uncap read, instead of failing the
    # upload arbitrarily partway through a good-faith transfer.
    upload_timeout = httpx.Timeout(60.0, write=None)
    with _client(timeout=upload_timeout) as c:
        resp = c.post(
            "/runs",
            files={"file": (f"{task_folder.name}.zip", zip_bytes, "application/zip")},
            data={"mode": mode},
        )
    if resp.status_code != 200:
        _die(resp)
    run_ids = resp.json()["run_ids"]
    console.print(f"[green]Queued:[/green] {', '.join(run_ids)}")

    for run_id in run_ids:
        console.rule(f"[bold]{run_id}[/bold]")
        _follow(run_id)
        if download_result:
            _download(
                run_id, task_folder.parent
            )  # save the result zip beside the task folder


@app.command("verify-only")
def verify_only(
    task_folder: Path = typer.Argument(..., exists=True, file_okay=False),
    target_mode: str = typer.Option(
        ...,
        "--target-mode",
        help=(
            "single | multi | multi_noplan -- which execution_logs/ folder "
            "already present in task_folder should be re-verified. No opencode "
            "agent runs at all; the server replays verification via Harbor's "
            "built-in oracle agent against that mode's existing agent output "
            "and patches the new reward into the same folder."
        ),
    ),
    download_result: bool = typer.Option(True, "--download/--no-download"),
) -> None:
    """Re-run only the verifier for an existing execution_logs/<target_mode>/
    run, without re-running the agent (no inference cost). Unlike `run`,
    this uploads execution_logs/ too -- it's the input, not the output."""
    if target_mode not in {"single", "multi", "multi_noplan"}:
        raise typer.Exit("target_mode must be single, multi, or multi_noplan")

    console.print(f"Packaging {task_folder} (including execution_logs/)…")
    zip_bytes = _zip_task_including_execution_logs(task_folder.resolve())

    # write=None uncaps the upload leg -- this payload includes the whole
    # execution_logs/<target_mode>/ tree (raw trajectory JSON, opencode logs,
    # etc.), typically much larger than `run`'s bare task-definition upload.
    # The 60s read timeout only covers the immediate {"run_ids": [...]}
    # response -- the actual replay runs asynchronously in the job queue.
    upload_timeout = httpx.Timeout(60.0, write=None)
    with _client(timeout=upload_timeout) as c:
        resp = c.post(
            "/runs/verify-only",
            files={"file": (f"{task_folder.name}.zip", zip_bytes, "application/zip")},
            data={"target_mode": target_mode},
        )
    if resp.status_code != 200:
        _die(resp)
    run_ids = resp.json()["run_ids"]
    console.print(f"[green]Queued:[/green] {', '.join(run_ids)}")

    for run_id in run_ids:
        console.rule(f"[bold]{run_id}[/bold]")
        _follow(run_id)
        if download_result:
            _download(run_id, task_folder.parent)


def _elapsed(start: float) -> str:
    secs = int(time.monotonic() - start)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:d}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"


def _follow(run_id: str) -> None:
    """Stream SSE progress until the run reaches a terminal marker.

    Ticks a live "Elapsed: MM:SS" line the moment the run starts, independent
    of when the first server log line actually arrives (queueing/environment
    build can take a while with nothing to show otherwise) -- purely cosmetic,
    doesn't affect the streamed output itself.
    """
    token = session.load().get("token")
    url = f"{_endpoint()}/runs/{run_id}/stream"
    headers = {"Authorization": f"Bearer {token}"}
    start = time.monotonic()
    stop = threading.Event()

    def _tick(live: Live) -> None:
        while not stop.wait(1):
            live.update(f"[dim]Elapsed: {_elapsed(start)}[/dim]")

    try:
        with Live(
            f"[dim]Elapsed: {_elapsed(start)}[/dim]",
            console=console,
            refresh_per_second=1,
            transient=True,
        ) as live:
            ticker = threading.Thread(target=_tick, args=(live,), daemon=True)
            ticker.start()
            try:
                with httpx.Client(timeout=None) as c:
                    with c.stream("GET", url, headers=headers) as resp:
                        if resp.status_code != 200:
                            console.print(
                                f"[red]Could not stream ({resp.status_code}).[/red]"
                            )
                            return
                        for line in resp.iter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            import json as _json

                            payload = _json.loads(line[6:])
                            text = payload.get("line", "")
                            console.print(text)
                            if text.startswith("[DONE"):
                                return
            finally:
                stop.set()
    except KeyboardInterrupt:
        console.print("[yellow]Ctrl-C — cancelling run on the server…[/yellow]")
        with _client() as c:
            c.post(f"/runs/{run_id}/cancel")
        raise typer.Exit(130)


_DOWNLOAD_RETRIES = 3
_DOWNLOAD_BACKOFF_SEC = 2


def _download(run_id: str, out_dir: Path) -> None:
    """Save the result package (the whole task folder + execution_logs, zipped)
    into out_dir. We save the zip as-is rather than extracting — it's a
    self-contained package the trainer can keep or unzip anywhere.

    Trainers connect from all over the world over whatever network they have,
    and a multi-MB transfer over a marginal connection can drop mid-stream
    (ReadTimeout, RemoteProtocolError) even though the file on the server is
    fine and re-downloadable at any time within the 24h TTL -- retry a few
    times before giving up, instead of crashing on a transient blip.
    """
    resp = None
    for attempt in range(1, _DOWNLOAD_RETRIES + 1):
        try:
            with _client() as c:
                resp = c.get(f"/runs/{run_id}/artifact")
            break
        except httpx.TransportError as exc:
            if attempt == _DOWNLOAD_RETRIES:
                console.print(
                    f"[red]Download failed after {_DOWNLOAD_RETRIES} attempts "
                    f"({exc.__class__.__name__}): {exc}[/red]"
                )
                return
            console.print(
                f"[yellow]Download interrupted ({exc.__class__.__name__}) -- "
                f"retrying ({attempt}/{_DOWNLOAD_RETRIES})…[/yellow]"
            )
            time.sleep(_DOWNLOAD_BACKOFF_SEC * attempt)
    assert resp is not None
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = ""
        console.print(
            f"[yellow]No result package: {detail or resp.status_code}[/yellow]"
        )
        return
    # Prefer the server's suggested filename (<task-slug>-<mode>.zip).
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^";]+)"?', cd)
    fname = m.group(1) if m else f"{run_id}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / fname
    out_path.write_bytes(resp.content)
    console.print(f"[green]Result package saved to {out_path}[/green]")


@app.command()
def runs() -> None:
    """List my runs with tokens and cost."""
    with _client() as c:
        me_resp = c.get("/me")
        resp = c.get("/runs")
    if me_resp.status_code == 200:
        me = me_resp.json()
        console.print(f"Today: {me['runs_today']}/{me['daily_quota']} runs used")
    if resp.status_code != 200:
        _die(resp)
    rows = resp.json()["runs"]
    if not rows:
        console.print("No runs yet.")
        return
    table = Table(show_lines=False)
    for col in (
        "run_id",
        "mode",
        "model",
        "status",
        "reward",
        "in_tok",
        "out_tok",
        "cost_usd",
        "task",
    ):
        table.add_column(col)
    for r in rows:
        # Show just the bare model name (e.g. "kimi-k2p6") -- the full
        # "fireworks_ai/accounts/fireworks/models/..." path is too wide for
        # this table, and the trailing segment is what trainers recognize.
        model_id = r.get("model_id") or ""
        model_short = model_id.rsplit("/", 1)[-1] if model_id else "-"
        table.add_row(
            r["run_id"],
            r["mode"],
            model_short,
            r["status"],
            str(r["reward"]),
            str(r["n_input_tokens"] or "-"),
            str(r["n_output_tokens"] or "-"),
            f"{r['total_cost_usd']:.4f}" if r["total_cost_usd"] else "-",
            (r["task_slug"] or "")[:40],
        )
    console.print(table)


@app.command()
def download(run_id: str, folder: Path = typer.Argument(Path("."))) -> None:
    """Download a run's result package (task + execution_logs) as a zip into folder."""
    _download(run_id, folder)


@app.command("pull-trajectory")
def pull_trajectory(run_id: str, folder: Path = typer.Argument(Path("."))) -> None:
    """Pull a fresh trajectory export from the run's LIVE Daytona sandbox.

    Unlike `download`, this doesn't wait for the run to finish -- the server
    re-runs the export inside the still-running sandbox on demand and hands
    back a fresh zip. Only works once the run has progressed far enough for
    its sandbox id to be known (409 otherwise) and while that sandbox is
    still alive (404 if it's already been stopped/deleted).
    """
    # Uncap the read leg -- the server has to round-trip into the live
    # sandbox (re-run the export, download the zip) before it can respond,
    # which can take longer than a plain status/list call.
    with _client(timeout=httpx.Timeout(60.0, read=120.0)) as c:
        resp = c.get(f"/runs/{run_id}/sandbox/trajectory-export")
    if resp.status_code != 200:
        _die(resp)
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / f"{run_id}-trajectory.zip"
    out_path.write_bytes(resp.content)
    console.print(f"[green]Trajectory export saved to {out_path}[/green]")


if __name__ == "__main__":
    app()
