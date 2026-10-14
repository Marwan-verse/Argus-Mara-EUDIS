"""Start the isolated local SOC stack without blocking the Tk event loop."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

from argus.collab_client import SOCClient, ClientError

ROOT = Path(__file__).resolve().parent.parent
LOCAL_URL = "https://localhost:8443"


class StartupError(RuntimeError):
    pass


def docker_path():
    found = shutil.which("docker")
    if found:
        return found
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe",
                  Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"),
                  Path("/Applications/Docker.app/Contents/Resources/bin/docker")]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise StartupError("Install Docker Desktop first, then retry. Offline mode is available without Docker.")


def run_command(command, *, timeout=30):
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise StartupError("Docker timed out. Check Docker Desktop and retry.") from None
    except OSError:
        raise StartupError("Could not start Docker. Check its installation and retry.") from None


def prepare_credentials(directory):
    """Never overwrite existing credentials or include them in logs/arguments.

    An existing file only gains passwords for accounts it lacks, such as
    Mykhailo's in a file made when the first sample account was Marwan.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "demo.env"
    try:
        descriptor = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = os.open(target, os.O_RDWR | os.O_APPEND)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
        stream.seek(0)
        existing = stream.read()
        present = {line.split("=", 1)[0] for line in existing.splitlines() if "=" in line}
        if existing and not existing.endswith("\n"):
            stream.write("\n")
        for account in ("MYKHAILO", "IGOR", "ADMIN"):
            if f"ARGUS_DEMO_{account}_PASSWORD" not in present:
                stream.write(f"ARGUS_DEMO_{account}_PASSWORD={secrets.token_urlsafe(24)}\n")
    return target


def start_local(progress, cancelled):
    """Return a verified HTTPS origin and CA path; leave shared containers running."""
    docker = docker_path()

    def check_cancelled():
        if cancelled.is_set():
            raise StartupError("Startup cancelled.")

    def wait_for(probe, message, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            check_cancelled()
            if probe():
                return
            if cancelled.wait(1):
                check_cancelled()
        raise StartupError(message)

    check_cancelled()
    progress("Checking Docker engine…")
    if run_command([docker, "info"], timeout=15).returncode:
        progress("Starting Docker Desktop…")
        result = run_command([docker, "desktop", "start", "--detach"])
        if result.returncode:
            if os.name == "nt":
                desktop = Path(docker).parents[2] / "Docker Desktop.exe"
                if not desktop.is_file():
                    raise StartupError("Start Docker Desktop manually, then retry.")
                subprocess.Popen([str(desktop)], creationflags=subprocess.CREATE_NO_WINDOW)
            elif sys.platform == "darwin":
                run_command(["open", "-a", "Docker"])
            else:
                raise StartupError("Start Docker Engine or Docker Desktop, then retry.")
        wait_for(lambda: run_command([docker, "info"], timeout=15).returncode == 0,
                 "Docker engine is not ready. Check Docker Desktop and retry.")
    private = ROOT / "data/soc-local"
    prepare_credentials(private)
    compose = [docker, "compose", "-f", str(ROOT / "soc/compose.local.yml")]
    progress("Starting local SOC containers (first build may take several minutes)…")
    check_cancelled()
    if run_command(compose + ["up", "-d", "--build", "relay", "https"], timeout=600).returncode:
        raise StartupError("Container startup failed. Inspect docker compose -f soc/compose.local.yml logs --tail 50.")
    check_cancelled()
    progress("Preparing local accounts…")
    if run_command(compose + ["run", "--rm", "seed"], timeout=120).returncode:
        raise StartupError("Account setup failed. Check data/soc-local/demo.env and soc/LOCAL-DEMO.md.")
    ca_file = private / "caddy-root.crt"
    progress("Waiting for verified local HTTPS…")

    def ready():
        if run_command(compose + ["cp", "https:/data/caddy/pki/authorities/local/root.crt", str(ca_file)]).returncode:
            return False
        try:
            return SOCClient(LOCAL_URL, ca_file=str(ca_file)).request("GET", "/healthz").get("ready") is True
        except (ClientError, OSError, ValueError):
            return False

    wait_for(ready, "Local HTTPS did not become ready. Check the relay and https container logs.", 60)
    check_cancelled()
    return LOCAL_URL, str(ca_file)


def open_second_client(url, ca_file):
    environment = os.environ.copy()
    environment["ARGUS_SOC_CA_FILE"] = ca_file
    return subprocess.Popen([sys.executable, str(ROOT / "run_gui.py"), "--soc", url, "--soc-client"],
                            cwd=ROOT, env=environment,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
