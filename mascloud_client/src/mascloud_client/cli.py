"""`mascloud` — the trainer's terminal client.

    mascloud login                       sign in (Turing email + password)
    mascloud run <task_folder>           pick single/multi, stream live, download
    mascloud runs                        my run history (tokens + cost)
    mascloud download <run_id> [folder]  fetch the result zip (task + execution_logs)
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

_EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", "execution_logs", "daytona_test_logs"}

# Production control plane. Override locally with MASCLOUD_ENDPOINT if needed
# (e.g. testing against a dev server) — trainers never need to set this.
_DEFAULT_ENDPOINT = "https://mascloud.mas-cloud-run.com"


def _endpoint() -> str:
    return (
        os.environ.get("MASCLOUD_ENDPOINT")
        or session.load().get("endpoint")
        or _DEFAULT_ENDPOINT
    ).rstrip("/")


def _client(auth: bool = True) -> httpx.Client:
    headers = {}
    if auth:
        token = session.load().get("token")
        if not token:
            raise typer.Exit("Not logged in — run `mascloud login` first.")
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=_endpoint(), headers=headers, timeout=60)


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
    console.print(f"[green]Connected as {data['display_name']} ({data['email']}).[/green]")


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


@app.command()
def run(
    task_folder: Path = typer.Argument(..., exists=True, file_okay=False),
    mode: str = typer.Option(None, help="single | multi (prompted if omitted). Run the other in a second terminal."),
    download_result: bool = typer.Option(True, "--download/--no-download"),
) -> None:
    """Upload a task folder, run it in the cloud, and stream progress live."""
    if mode is None:
        mode = typer.prompt("Run mode [single/multi]", default="multi")
    if mode not in {"single", "multi"}:
        raise typer.Exit("mode must be single or multi")

    console.print(f"Packaging {task_folder}…")
    zip_bytes = _zip_task(task_folder.resolve())

    with _client() as c:
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
            _download(run_id, task_folder.parent)   # save the result zip beside the task folder


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
        with Live(f"[dim]Elapsed: {_elapsed(start)}[/dim]", console=console, refresh_per_second=1, transient=True) as live:
            ticker = threading.Thread(target=_tick, args=(live,), daemon=True)
            ticker.start()
            try:
                with httpx.Client(timeout=None) as c:
                    with c.stream("GET", url, headers=headers) as resp:
                        if resp.status_code != 200:
                            console.print(f"[red]Could not stream ({resp.status_code}).[/red]")
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
        console.print(f"[yellow]No result package: {detail or resp.status_code}[/yellow]")
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
        resp = c.get("/runs")
    if resp.status_code != 200:
        _die(resp)
    rows = resp.json()["runs"]
    if not rows:
        console.print("No runs yet.")
        return
    table = Table(show_lines=False)
    for col in ("run_id", "mode", "status", "reward", "in_tok", "out_tok", "cost_usd", "task"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["run_id"], r["mode"], r["status"],
            str(r["reward"]), str(r["n_input_tokens"] or "-"),
            str(r["n_output_tokens"] or "-"),
            f'{r["total_cost_usd"]:.4f}' if r["total_cost_usd"] else "-",
            (r["task_slug"] or "")[:40],
        )
    console.print(table)


@app.command()
def download(run_id: str, folder: Path = typer.Argument(Path("."))) -> None:
    """Download a run's result package (task + execution_logs) as a zip into folder."""
    _download(run_id, folder)


if __name__ == "__main__":
    app()