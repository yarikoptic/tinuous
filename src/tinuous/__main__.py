import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Match, Optional, Pattern

import click
from click_loglevel import LogLevel
from dotenv import load_dotenv
from in_place import InPlace
from yaml import safe_load

from . import __version__
from .base import Artifact, BuildLog
from .config import Config, GHPathsDict
from .github import GitHubActions
from .state import STATE_FILE, StateFile
from .util import log


@click.group()
@click.version_option(
    __version__,
    "-V",
    "--version",
    message="%(prog)s %(version)s",
)
@click.option(
    "-c",
    "--config",
    type=click.Path(dir_okay=False),
    default="tinuous.yaml",
    help="Read configuration from the given file",
    show_default=True,
)
@click.option(
    "-E",
    "--env",
    type=click.Path(exists=True, dir_okay=False),
    help="Load environment variables from given .env file",
)
@click.option(
    "-l",
    "--log-level",
    type=LogLevel(),
    default="INFO",
    help="Set logging level",
    show_default=True,
)
@click.pass_context
def main(ctx: click.Context, config: str, log_level: int, env: Optional[str]) -> None:
    """
    Download build logs from GitHub Actions, Travis, Appveyor, and CircleCI
    """
    load_dotenv(env)
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        level=log_level,
    )
    log.info("tinuous %s", __version__)
    ctx.obj = config


@main.command()
@click.option(
    "--sanitize-secrets",
    is_flag=True,
    help="Sanitize strings matching secret patterns",
)
@click.option(
    "-S",
    "--state",
    "state_path",
    type=click.Path(dir_okay=False, writable=True),
    help=f"Store program state in the given file  [default: {STATE_FILE}]",
)
@click.pass_obj
def fetch(config_file: str, state_path: Optional[str], sanitize_secrets: bool) -> None:
    """Download logs"""
    try:
        with open(config_file) as fp:
            cfg = Config.parse_obj(safe_load(fp))
    except FileNotFoundError:
        raise click.UsageError(f"Configuration file not found: {config_file}")
    if sanitize_secrets and not cfg.secrets:
        log.warning("--sanitize-secrets set but no secrets given in configuration")
    statefile = StateFile.from_file(state_path)
    # Fetch tokens early in order to catch failures early:
    tokens: Dict[str, Dict[str, str]] = {}
    for name, cicfg in cfg.ci.items():
        tokens[name] = cicfg.get_auth_tokens()
    if cfg.datalad.enabled:
        try:
            from datalad.api import Dataset
        except ImportError:
            raise click.UsageError("datalad.enabled set, but datalad is not installed")
        ds = Dataset(os.curdir)
        if not ds.is_installed():
            ds.create(force=True, cfg_proc=cfg.datalad.cfg_proc)
    logs_added = 0
    artifacts_added = 0
    relassets_added = 0
    for name, cicfg in cfg.ci.items():
        if not cicfg.gets_builds() and not cicfg.gets_releases():
            log.info("No paths configured for %s; skipping", name)
            continue
        log.info("Fetching resources from %s", name)
        since = cfg.get_since(statefile.get_since(name))
        ci = cicfg.get_system(
            repo=cfg.repo, since=since, until=cfg.until, tokens=tokens[name]
        )
        artifacts_path = getattr(cicfg.paths, "artifacts", None)
        if cicfg.gets_builds():
            for obj in ci.get_build_assets(
                cfg.types,
                logs=cicfg.paths.logs is not None,
                artifacts=artifacts_path is not None,
            ):
                if isinstance(obj, BuildLog):
                    assert cicfg.paths.logs is not None
                    path = obj.expand_path(cicfg.paths.logs, cfg.vars)
                elif isinstance(obj, Artifact):
                    assert artifacts_path is not None
                    path = obj.expand_path(artifacts_path, cfg.vars)
                else:
                    raise AssertionError(f"Unexpected asset type {type(obj).__name__}")
                if cfg.datalad.enabled:
                    ensure_datalad(ds, path, cfg.datalad.cfg_proc)
                paths = obj.download(Path(path))
                if isinstance(obj, BuildLog):
                    logs_added += len(paths)
                    if sanitize_secrets and cfg.secrets:
                        for p in paths:
                            sanitize(p, cfg.secrets, cfg.allow_secrets_regex)
                elif isinstance(obj, Artifact):
                    artifacts_added += len(paths)
        if cicfg.gets_releases():
            assert isinstance(ci, GitHubActions)
            assert isinstance(cicfg.paths, GHPathsDict)
            releases_path = cicfg.paths.releases
            assert releases_path is not None
            for asset in ci.get_release_assets():
                path = asset.expand_path(releases_path, cfg.vars)
                if cfg.datalad.enabled:
                    ensure_datalad(ds, path, cfg.datalad.cfg_proc)
                paths = asset.download(Path(path))
                relassets_added += len(paths)
        statefile.set_since(name, ci.new_since())
    log.info("%d logs downloaded", logs_added)
    log.info("%d artifacts downloaded", artifacts_added)
    log.info("%d release assets downloaded", relassets_added)
    if cfg.datalad.enabled:
        if logs_added or artifacts_added or relassets_added:
            msg = f"[tinuous] {logs_added} logs added"
            if artifacts_added:
                msg += f", {artifacts_added} artifacts added"
            if relassets_added:
                msg += f", {relassets_added} release assets added"
            msg += f"\n\nProduced by tinuous {__version__}"
            ds.save(recursive=True, message=msg)
        elif statefile.modified:
            msg = f"[tinuous] Updated statefile\n\nProduced by tinuous {__version__}"
            ds.save(recursive=True, message=msg)


@main.command("sanitize")
@click.argument(
    "path", type=click.Path(exists=True, dir_okay=False, writable=True), nargs=-1
)
@click.pass_obj
def sanitize_cmd(config_file: str, path: List[str]) -> None:
    """Sanitize secrets in logs"""
    try:
        with open(config_file) as fp:
            cfg = Config.parse_obj(safe_load(fp))
    except FileNotFoundError:
        raise click.UsageError(f"Configuration file not found: {config_file}")
    for p in path:
        sanitize(Path(p), cfg.secrets, cfg.allow_secrets_regex)


def sanitize(
    p: Path, secrets: Dict[str, Pattern], allow_secrets: Optional[Pattern]
) -> None:
    def replace(m: Match) -> str:
        s = m.group()
        assert isinstance(s, str)
        if allow_secrets is not None and allow_secrets.search(s):
            return s
        else:
            return "*" * len(s)

    log.info("Sanitizing %s", p)
    with InPlace(p, mode="t", encoding="utf-8", newline="") as fp:
        for i, line in enumerate(fp, start=1):
            for name, rgx in secrets.items():
                newline = rgx.sub(replace, line)
                if newline != line:
                    log.info("Found %s secret on line %d", name, i)
                line = newline
            fp.write(line)


def ensure_datalad(ds: Any, path: str, cfg_proc: Optional[str]) -> None:
    # `ds` is actually a datalad Dataset, but the import is optional.
    dspaths = path.split("//")
    if "" in dspaths:
        raise click.UsageError("Path contains empty '//'-delimited segment")
    for i in range(1, len(dspaths)):
        dsp = "/".join(dspaths[:i])
        if not Path(dsp).exists():
            ds.create(dsp, cfg_proc=cfg_proc)


if __name__ == "__main__":
    main()
