from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from functools import cached_property
import heapq
import os
from pathlib import Path, PurePosixPath
import re
from shutil import rmtree
import tempfile
from time import sleep
from typing import Any, Dict, Iterator, List, Optional, Pattern, Tuple, Union
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, Field, validator
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError as ReqConError

from .util import delay_until, expand_template, log, sanitize_pathname

COMMON_STATUS_MAP = {
    "success": "success",
    "passed": "success",
    "failure": "failed",
    "failed": "failed",
    "errored": "errored",
    "timed_out": "errored",
    "startup_failure": "errored",
    "neutral": "incomplete",
    "action_required": "incomplete",
    "cancelled": "incomplete",
    "canceled": "incomplete",
    "skipped": "incomplete",
    "stale": "incomplete",
    # Error on unknown so we're forced to categorize them.
}

# Safeguard against typos:
assert set(COMMON_STATUS_MAP.values()) == {"success", "failed", "errored", "incomplete"}


class EventType(Enum):
    CRON = "cron"
    PUSH = "push"
    PULL_REQUEST = "pr"
    MANUAL = "manual"

    @classmethod
    def from_gh_event(cls, gh_event: str) -> Optional["EventType"]:
        return {
            "schedule": cls.CRON,
            "push": cls.PUSH,
            "pull_request": cls.PULL_REQUEST,
            "workflow_dispatch": cls.MANUAL,
            "repository_dispatch": cls.MANUAL,
        }.get(gh_event)

    @classmethod
    def from_travis_event(cls, travis_event: str) -> Optional["EventType"]:
        return {
            "cron": cls.CRON,
            "push": cls.PUSH,
            "pull_request": cls.PULL_REQUEST,
            "api": cls.MANUAL,
        }.get(travis_event)


class APIClient:
    MAX_RETRIES = 10
    ZIPFILE_RETRIES = 5

    def __init__(self, base_url: str, headers: Dict[str, str], is_github: bool = False):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.is_github = is_github

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        if path.lower().startswith(("http://", "https://")):
            url = path
        else:
            url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        i = 0
        while True:
            r = self.session.get(url, **kwargs)
            if r.status_code >= 500 and i < self.MAX_RETRIES:
                log.warning(
                    "Request to %s returned %d; waiting & retrying", url, r.status_code
                )
                i += 1
                sleep(i * i)
            elif (
                self.is_github
                and r.status_code == 403
                and "API rate limit exceeded" in r.json().get("message", "")
            ):
                delay = delay_until(
                    datetime.fromtimestamp(
                        int(r.headers["x-ratelimit-reset"]), tz=timezone.utc
                    )
                )
                log.warning("Rate limit exceeded; sleeping for %s seconds", delay)
                sleep(delay)
            else:
                r.raise_for_status()
                return r

    def download(self, path: str, filepath: Path) -> None:
        i = 0
        while True:
            try:
                try:
                    r = self.get(path, stream=True)
                    with filepath.open("wb") as fp:
                        for chunk in r.iter_content(chunk_size=8192):
                            fp.write(chunk)
                except (ChunkedEncodingError, ReqConError) as e:
                    if i < self.MAX_RETRIES:
                        log.warning(
                            "Download of %s interrupted: %s; waiting & retrying",
                            path,
                            str(e),
                        )
                        i += 1
                        sleep(i)
                    else:
                        log.error("Max retries exceeded")
                        raise
                else:
                    break
            except BaseException:
                filepath.unlink(missing_ok=True)
                raise

    def download_zipfile(self, path: str, target_dir: Path) -> None:
        fd, fpath = tempfile.mkstemp()
        os.close(fd)
        zippath = Path(fpath)
        i = 0
        while True:
            self.download(path, zippath)
            try:
                with ZipFile(zippath) as zf:
                    zf.extractall(target_dir)
            except BadZipFile:
                rmtree(target_dir)
                if i < self.ZIPFILE_RETRIES:
                    log.error("Invalid zip file retrieved; waiting and retrying")
                    i += 1
                    sleep(i * i)
                else:
                    raise
            except BaseException:
                rmtree(target_dir)
                raise
            else:
                break
            finally:
                zippath.unlink(missing_ok=True)


class CISystem(ABC, BaseModel):
    repo: str
    token: str
    since: datetime
    until: Optional[datetime]
    fetched: List[Tuple[datetime, bool]] = Field(default_factory=list)

    @staticmethod
    @abstractmethod
    def get_auth_tokens() -> Dict[str, str]:
        ...  # pragma: no cover

    @abstractmethod
    def get_build_assets(
        self, event_types: List[EventType], logs: bool, artifacts: bool
    ) -> Iterator["BuildAsset"]:
        ...  # pragma: no cover

    def register_build(self, ts: datetime, processed: bool) -> None:
        heapq.heappush(self.fetched, (ts, processed))

    def new_since(self) -> datetime:
        prev_ts = self.since
        while self.fetched:
            ts, processed = heapq.heappop(self.fetched)
            if not processed:
                break
            prev_ts = ts
        return prev_ts

    class Config:
        # <https://github.com/samuelcolvin/pydantic/issues/1241>
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)


class BuildAsset(ABC, BaseModel):
    client: APIClient
    created_at: datetime
    event_type: EventType
    event_id: str
    build_commit: str
    commit: Optional[str]
    number: int
    status: str

    class Config:
        # To allow APIClient:
        arbitrary_types_allowed = True

    def path_fields(self) -> Dict[str, Any]:
        utc_date = self.created_at.astimezone(timezone.utc)
        commit = "UNK" if self.commit is None else self.commit
        return {
            "timestamp": utc_date,
            "timestamp_local": self.created_at.astimezone(),
            "year": utc_date.strftime("%Y"),
            "month": utc_date.strftime("%m"),
            "day": utc_date.strftime("%d"),
            "hour": utc_date.strftime("%H"),
            "minute": utc_date.strftime("%M"),
            "second": utc_date.strftime("%S"),
            "type": self.event_type.value,
            "type_id": sanitize_pathname(self.event_id),
            "build_commit": self.build_commit,
            "commit": commit,
            "number": str(self.number),
            "status": self.status,
            "common_status": COMMON_STATUS_MAP[self.status],
        }

    def expand_path(self, path_template: str, vars: Dict[str, str]) -> str:
        return expand_template(path_template, self.path_fields(), vars)

    @abstractmethod
    def download(self, path: Path) -> List[Path]:
        ...  # pragma: no cover


class BuildLog(BuildAsset):
    pass


class Artifact(BuildAsset):
    pass


# These config-related classes need to go in this file to avoid a circular
# import issue:


class NoExtraModel(BaseModel):
    class Config:
        allow_population_by_field_name = True
        extra = "forbid"


class WorkflowSpec(NoExtraModel):
    regex: bool = False
    # Workflow names are stored as compiled regexes regardless of whether
    # `regex` is true in order to keep type-checking simple.
    include: List[Pattern] = Field(default_factory=lambda: [re.compile(".*")])
    exclude: List[Pattern] = Field(default_factory=list)

    @validator("include", "exclude", pre=True, each_item=True)
    def _maybe_regex(
        cls, v: Union[str, Pattern], values: Dict[str, Any]  # noqa: B902, U100
    ) -> Union[str, Pattern]:
        if not values["regex"] and isinstance(v, str):
            v = r"\A" + re.escape(v) + r"\Z"
        return v

    def match(self, wf_path: str) -> bool:
        s = PurePosixPath(wf_path).name
        return any(r.search(s) for r in self.include) and not any(
            r.search(s) for r in self.exclude
        )
