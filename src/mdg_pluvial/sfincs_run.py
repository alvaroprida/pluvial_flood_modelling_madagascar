"""Run one SFINCS model, in Docker (default) or with a native executable.

Docker uses the official Deltares image, pinned to a release in ``config/settings.yml`` so
results are reproducible. The image is published for amd64 only; on Apple Silicon Docker
emulates it, which is slower but gives the same results. On Linux (e.g. AWS) set
``run.engine: executable`` and point ``run.executable`` at a native build to skip Docker.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

LOG_NAME = "sfincs_log.txt"
MAP_NAME = "sfincs_map.nc"
FINISHED = "Simulation finished"


def sfincs_command(model_dir: Path, run_cfg: dict) -> List[str]:
    """Command line that runs the model in *model_dir*."""
    engine = run_cfg.get("engine", "docker")
    threads: Optional[int] = run_cfg.get("threads")
    if engine == "docker":
        cmd = ["docker", "run", "--rm", "-v", f"{Path(model_dir).resolve()}:/data"]
        if run_cfg.get("platform"):
            cmd += ["--platform", run_cfg["platform"]]
        if threads:
            cmd += ["-e", f"OMP_NUM_THREADS={int(threads)}"]
        return cmd + [run_cfg.get("image", "deltares/sfincs-cpu:sfincs-v2.4.1")]
    if engine == "executable":
        exe = run_cfg.get("executable")
        if not exe:
            raise ValueError("run.engine is 'executable' but run.executable is not set")
        return [str(Path(exe).expanduser())]
    raise ValueError(f"unknown run.engine '{engine}' (use 'docker' or 'executable')")


def is_complete(model_dir: Path) -> bool:
    """True when a previous run finished: output present and the log says so."""
    log_file = model_dir / LOG_NAME
    return ((model_dir / MAP_NAME).exists() and log_file.exists()
            and FINISHED in log_file.read_text(errors="replace"))


def run_sfincs(model_dir: Path, run_cfg: dict, *, overwrite: bool = False) -> Path:
    """Run SFINCS in *model_dir*; the console output goes to ``sfincs_log.txt``."""
    if not (model_dir / "sfincs.inp").exists():
        raise FileNotFoundError(f"no SFINCS model in {model_dir} - run the 'setup' step first")
    if is_complete(model_dir) and not overwrite:
        log.info("simulation complete, skipped: %s", model_dir)
        return model_dir / MAP_NAME
    for stale in ("sfincs_map.nc", "sfincs_his.nc", LOG_NAME):
        (model_dir / stale).unlink(missing_ok=True)

    cmd = sfincs_command(model_dir, run_cfg)
    env = dict(os.environ)
    if run_cfg.get("threads"):
        env["OMP_NUM_THREADS"] = str(int(run_cfg["threads"]))
    log.info("running SFINCS: %s", " ".join(cmd))
    t0 = time.time()
    with open(model_dir / LOG_NAME, "w") as fh:
        proc = subprocess.run(cmd, cwd=model_dir, stdout=fh, stderr=subprocess.STDOUT, env=env)
    text = (model_dir / LOG_NAME).read_text(errors="replace")
    if proc.returncode != 0 or FINISHED not in text:
        tail = "\n".join(text.strip().splitlines()[-15:])
        raise RuntimeError(f"SFINCS failed (exit code {proc.returncode}); last lines of "
                           f"{LOG_NAME}:\n{tail}")
    log.info("SFINCS finished in %.0fs", time.time() - t0)
    return model_dir / MAP_NAME
