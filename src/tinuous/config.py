from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Iterator, List, Optional, Pattern, Tuple

from pydantic import Field, validator
from pydantic.fields import ModelField

from .appveyor import Appveyor
from .base import CISystem, EventType, GHWorkflowSpec, NoExtraModel, WorkflowSpec
from .circleci import CircleCI
from .github import GitHubActions
from .travis import Travis
from .util import log


class PathsDict(NoExtraModel):
    logs: Optional[str] = None

    def gets_builds(self) -> bool:
        return self.logs is not None

    def gets_releases(self) -> bool:
        return False


class GHPathsDict(PathsDict):
    artifacts: Optional[str] = None
    releases: Optional[str] = None

    def gets_builds(self) -> bool:
        return self.logs is not None or self.artifacts is not None

    def gets_releases(self) -> bool:
        return self.releases is not None


class CCIPathsDict(PathsDict):
    artifacts: Optional[str] = None

    def gets_builds(self) -> bool:
        return self.logs is not None or self.artifacts is not None


class CIConfig(NoExtraModel, ABC):
    paths: PathsDict = Field(default_factory=PathsDict)

    @staticmethod
    @abstractmethod
    def get_auth_tokens() -> Dict[str, str]:
        ...  # pragma: no cover

    @abstractmethod
    def get_system(
        self,
        repo: str,
        since: datetime,
        until: Optional[datetime],
        tokens: Dict[str, str],
    ) -> CISystem:
        ...  # pragma: no cover

    def gets_builds(self) -> bool:
        return self.paths.gets_builds()

    def gets_releases(self) -> bool:
        return self.paths.gets_releases()


class GitHubConfig(CIConfig):
    paths: GHPathsDict = Field(default_factory=GHPathsDict)
    workflows: GHWorkflowSpec = Field(default_factory=GHWorkflowSpec)

    @validator("workflows", pre=True)
    def _workflow_list(cls, v: Any) -> Any:  # noqa: B902, U100
        if isinstance(v, list):
            return {"include": v}
        else:
            return v

    @staticmethod
    def get_auth_tokens() -> Dict[str, str]:
        return GitHubActions.get_auth_tokens()

    def get_system(
        self,
        repo: str,
        since: datetime,
        until: Optional[datetime],
        tokens: Dict[str, str],
    ) -> GitHubActions:
        return GitHubActions(
            repo=repo,
            since=since,
            until=until,
            token=tokens["github"],
            workflow_spec=self.workflows,
        )


class TravisConfig(CIConfig):
    @staticmethod
    def get_auth_tokens() -> Dict[str, str]:
        return Travis.get_auth_tokens()

    def get_system(
        self,
        repo: str,
        since: datetime,
        until: Optional[datetime],
        tokens: Dict[str, str],
    ) -> Travis:
        return Travis(
            repo=repo,
            since=since,
            until=until,
            token=tokens["travis"],
            gh_token=tokens["github"],
        )


class AppveyorConfig(CIConfig):
    accountName: str
    projectSlug: Optional[str] = None

    @staticmethod
    def get_auth_tokens() -> Dict[str, str]:
        return Appveyor.get_auth_tokens()

    def get_system(
        self,
        repo: str,
        since: datetime,
        until: Optional[datetime],
        tokens: Dict[str, str],
    ) -> Appveyor:
        return Appveyor(
            repo=repo,
            since=since,
            until=until,
            token=tokens["appveyor"],
            accountName=self.accountName,
            projectSlug=self.projectSlug,
        )


class CircleCIConfig(CIConfig):
    paths: CCIPathsDict = Field(default_factory=CCIPathsDict)
    workflows: WorkflowSpec = Field(default_factory=WorkflowSpec)

    @staticmethod
    def get_auth_tokens() -> dict[str, str]:
        return CircleCI.get_auth_tokens()

    def get_system(
        self,
        repo: str,
        since: datetime,
        until: Optional[datetime],
        tokens: dict[str, str],
    ) -> CircleCI:
        return CircleCI(
            repo=repo,
            since=since,
            until=until,
            token=tokens["circleci"],
            workflow_spec=self.workflows,
        )


class CIConfigDict(NoExtraModel):
    github: Optional[GitHubConfig] = None
    travis: Optional[TravisConfig] = None
    appveyor: Optional[AppveyorConfig] = None
    circleci: Optional[CircleCIConfig] = None

    def items(self) -> Iterator[Tuple[str, CIConfig]]:
        if self.github is not None:
            yield ("github", self.github)
        if self.travis is not None:
            yield ("travis", self.travis)
        if self.appveyor is not None:
            yield ("appveyor", self.appveyor)
        if self.circleci is not None:
            yield ("circleci", self.circleci)


class DataladConfig(NoExtraModel):
    enabled: bool = False
    cfg_proc: Optional[str] = None


class Config(NoExtraModel):
    repo: str
    vars: Dict[str, str] = Field(default_factory=dict)
    ci: CIConfigDict
    since: Optional[datetime] = None
    max_days_back: int = Field(30, alias="max-days-back")
    until: Optional[datetime] = None
    types: List[EventType] = Field(default_factory=lambda: list(EventType))
    secrets: Dict[str, Pattern] = Field(default_factory=dict)
    allow_secrets_regex: Optional[Pattern] = Field(None, alias="allow-secrets-regex")
    datalad: DataladConfig = Field(default_factory=DataladConfig)

    @validator("repo")
    def _validate_repo(cls, v: str) -> str:  # noqa: B902, U100
        if not re.fullmatch(r"[^/]+/[^/]+", v):
            raise ValueError("Repo must be in the form 'OWNER/NAME'")
        return v

    @validator("since", "until")
    def _validate_datetimes(
        cls, v: Optional[datetime], field: ModelField  # noqa: B902, U100
    ) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError(f"{field.name!r} timestamp must include timezone offset")
        return v

    def get_since(self, state_since: Optional[datetime]) -> datetime:
        max_dt_back = datetime.now(timezone.utc) - timedelta(days=self.max_days_back)
        if state_since is None:
            return self.since if self.since is not None else max_dt_back
        elif self.since is None or self.since <= state_since:
            return max(state_since, max_dt_back)
        else:
            if self.since < max_dt_back:
                # Because state_since < self.since, assume the user explicitly
                # edited `since` and thus wants it to take precedence over
                # max-days-back (but still warn that's what we're doing)
                log.warning(
                    "`since` option appears to have been manually updated;"
                    " ignoring `max-days-back`"
                )
            return self.since
