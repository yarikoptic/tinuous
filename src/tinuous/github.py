from datetime import datetime, timezone
from functools import cached_property, wraps
from pathlib import Path
from time import sleep
from typing import Any, Callable, Dict, Iterator, List, Tuple

from github import Github
from github.GitRelease import GitRelease
from github.GitReleaseAsset import GitReleaseAsset
from github.GithubException import RateLimitExceededException
from github.Repository import Repository
from github.Workflow import Workflow
from github.WorkflowRun import WorkflowRun
from pydantic import BaseModel, Field
import requests
from urllib3.util.retry import Retry

from .base import (
    APIClient,
    Artifact,
    BuildAsset,
    BuildLog,
    CISystem,
    EventType,
    GHWorkflowSpec,
)
from .util import (
    delay_until,
    ensure_aware,
    expand_template,
    get_github_token,
    iterfiles,
    log,
    sanitize_pathname,
)


def retry_ratelimit(func: Callable) -> Callable:
    @wraps(func)
    def wrapped(gha: "GitHubActions", *args: Any, **kwargs: Any) -> Any:
        while True:
            try:
                return func(gha, *args, **kwargs)
            except RateLimitExceededException:
                delay = delay_until(
                    ensure_aware(gha.client.get_rate_limit().core.reset)
                )
                log.warning("Rate limit exceeded; sleeping for %s seconds", delay)
                sleep(delay)

    return wrapped


class GitHubActions(CISystem):
    workflow_spec: GHWorkflowSpec
    hash2pr: Dict[str, str] = Field(default_factory=dict)

    @staticmethod
    def get_auth_tokens() -> Dict[str, str]:
        return {"github": get_github_token()}

    @cached_property
    def client(self) -> Github:
        return Github(
            self.token,
            retry=Retry(
                total=12,
                backoff_factor=1.25,
                status_forcelist=[500, 502, 503, 504],
            ),
        )

    @cached_property
    def extra_client(self) -> APIClient:
        """
        Client for downloading resources and other actions not supported by
        Pygithub
        """
        return APIClient(
            "https://api.github.com",
            {"Authorization": f"token {self.token}"},
            is_github=True,
        )

    @cached_property  # type: ignore[misc]
    @retry_ratelimit
    def ghrepo(self) -> Repository:
        return self.client.get_repo(self.repo)

    @retry_ratelimit
    def get_workflows(self) -> List[Workflow]:
        workflows: List[Workflow] = []
        for wf in self.ghrepo.get_workflows():
            if self.workflow_spec.match(wf.path):
                workflows.append(wf)
        return workflows

    @retry_ratelimit
    def get_runs(self, wf: Workflow, since: datetime) -> List[WorkflowRun]:
        runs: List[WorkflowRun] = []
        for r in wf.get_runs():
            if ensure_aware(r.created_at) <= since:
                break
            runs.append(r)
        return runs

    def get_build_assets(
        self, event_types: List[EventType], logs: bool, artifacts: bool
    ) -> Iterator["BuildAsset"]:
        if not logs and not artifacts:
            log.debug("No assets requested for GitHub Actions runs")
            return
        log.info("Fetching runs newer than %s", self.since)
        if self.until is not None:
            log.info("Skipping runs newer than %s", self.until)
        for wf in self.get_workflows():
            log.info("Fetching runs for workflow %s (%s)", wf.path, wf.name)
            for run in self.get_runs(wf, self.since):
                run_event = EventType.from_gh_event(run.event)
                ts = ensure_aware(run.created_at)
                if self.until is not None and ts > self.until:
                    log.info("Run %s is too new; skipping", run.run_number)
                elif run.status != "completed":
                    log.info("Run %s not completed; skipping", run.run_number)
                    self.register_build(ts, False)
                else:
                    log.info("Found run %s", run.run_number)
                    self.register_build(ts, True)
                    if run_event in event_types:
                        event_id = self.get_event_id(run, run_event)
                        if logs:
                            yield GHABuildLog.from_workflow_run(
                                self.extra_client, wf, run, run_event, event_id
                            )
                        if artifacts:
                            for name, download_url in self.get_artifacts(run):
                                yield GHAArtifact.from_workflow_run(
                                    self.extra_client,
                                    wf,
                                    run,
                                    run_event,
                                    event_id,
                                    name,
                                    download_url,
                                )
                    else:
                        log.info("Event type is %r; skipping", run.event)

    def get_event_id(self, run: WorkflowRun, event_type: EventType) -> str:
        if event_type in (EventType.CRON, EventType.MANUAL):
            return ensure_aware(run.created_at).strftime("%Y%m%dT%H%M%S")
        elif event_type is EventType.PUSH:
            return run.head_branch
        elif event_type is EventType.PULL_REQUEST:
            if run.pull_requests:
                return str(run.pull_requests[0].number)
            elif run.head_sha in self.hash2pr:
                return self.hash2pr[run.head_sha]
            else:
                r = self.extra_client.get(
                    f"/repos/{self.repo}/commits/{run.head_sha}/pulls",
                    headers={"Accept": "application/vnd.github.groot-preview+json"},
                )
                if data := r.json():
                    pr = str(data[0]["number"])
                else:
                    # The above endpoint ignores PRs made from forks, so we
                    # have to fall back to performing an issue search to fill
                    # those in.  This should hopefully be used sparingly, as
                    # there's a 30 searches per hour rate limit.
                    while True:
                        try:
                            pr = str(
                                self.client.search_issues(
                                    f"repo:{run.repository.full_name} is:pr"
                                    f" {run.head_sha}",
                                    sort="created",
                                    order="asc",
                                )[0].number
                            )
                            break
                        except IndexError:
                            pr = "UNK"
                            break
                        except RateLimitExceededException:
                            delay = delay_until(
                                ensure_aware(self.client.get_rate_limit().search.reset)
                            )
                            log.warning(
                                "Search rate limit exceeded; sleeping for %s seconds",
                                delay,
                            )
                            sleep(delay)
                self.hash2pr[run.head_sha] = pr
                return pr
        else:
            raise AssertionError(f"Unhandled EventType: {event_type!r}")

    def get_artifacts(self, run: WorkflowRun) -> Iterator[Tuple[str, str]]:
        """Yields each artifact as a (name, download_url) pair"""
        url = run.artifacts_url
        while url is not None:
            r = self.extra_client.get(url)
            for artifact in r.json()["artifacts"]:
                if not artifact["expired"]:
                    yield (artifact["name"], artifact["archive_download_url"])
            url = r.links.get("next", {}).get("url")

    @retry_ratelimit
    def get_releases(self) -> List[GitRelease]:
        return list(self.ghrepo.get_releases())

    @retry_ratelimit
    def get_assets(self, rel: GitRelease) -> List[GitReleaseAsset]:
        return list(rel.get_assets())

    def get_release_assets(self) -> Iterator["GHReleaseAsset"]:
        log.info("Fetching releases newer than %s", self.since)
        if self.until is not None:
            log.info("Skipping releases newer than %s", self.until)
        for rel in self.get_releases():
            if rel.draft:
                log.info("Release %s is draft; skipping", rel.tag_name)
                continue
            if rel.prerelease:
                log.info("Release %s is prerelease; skipping", rel.tag_name)
                continue
            ts = ensure_aware(rel.published_at)
            if ts <= self.since or (self.until is not None and ts > self.until):
                continue
            self.register_build(ts, True)  # TODO: Set to False for drafts?
            log.info("Found release %s", rel.tag_name)
            r = self.extra_client.get(
                f"/repos/{self.repo}/git/refs/tags/{rel.tag_name}"
            )
            tagobj = r.json()["object"]
            if tagobj["type"] == "commit":
                commit = tagobj["sha"]
            elif tagobj["type"] == "tag":
                r = self.extra_client.get(tagobj["url"])
                commit = r.json()["object"]["sha"]
            else:
                raise RuntimeError(
                    f"Unexpected type for tag {rel.tag_name}: {tagobj['type']!r}"
                )
            for asset in self.get_assets(rel):
                yield GHReleaseAsset(
                    client=self.extra_client,
                    published_at=ts,
                    tag_name=rel.tag_name,
                    commit=commit,
                    name=asset.name,
                    download_url=asset.browser_download_url,
                )


class GHAAsset(BuildAsset):
    workflow_name: str
    workflow_file: str
    run_id: int

    def path_fields(self) -> Dict[str, Any]:
        fields = super().path_fields()
        fields.update(
            {
                "ci": "github",
                "wf_name": sanitize_pathname(self.workflow_name),
                "wf_file": self.workflow_file,
                "run_id": str(self.run_id),
            }
        )
        return fields


class GHABuildLog(GHAAsset, BuildLog):
    logs_url: str

    @classmethod
    def from_workflow_run(
        cls,
        client: APIClient,
        workflow: Workflow,
        run: WorkflowRun,
        event_type: EventType,
        event_id: str,
    ) -> "GHABuildLog":
        return cls(
            client=client,
            logs_url=run.logs_url,
            created_at=ensure_aware(run.created_at),
            event_type=event_type,
            event_id=event_id,
            build_commit=run.head_sha,
            commit=run.head_sha,
            workflow_name=workflow.name,
            workflow_file=workflow.path.split("/")[-1],
            number=run.run_number,
            run_id=run.id,
            status=run.conclusion,
        )

    def download(self, path: Path) -> List[Path]:
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            log.info(
                "Logs for %s (%s) #%s already downloaded to %s; skipping",
                self.workflow_file,
                self.workflow_name,
                self.number,
                path,
            )
            return []
        log.info(
            "Downloading logs for %s (%s) #%s to %s",
            self.workflow_file,
            self.workflow_name,
            self.number,
            path,
        )
        try:
            self.client.download_zipfile(self.logs_url, path)
        except requests.HTTPError as e:
            if e.response.status_code in (404, 410):
                # 404 can happen when a workflow failed to run due to, say, a
                # syntax error.  410 happens when the logs have expired.
                log.error(
                    "Request for logs returned %d; skipping", e.response.status_code
                )
                return []
            else:
                raise
        return list(path.rglob("*.txt"))


class GHAArtifact(GHAAsset, Artifact):
    name: str
    download_url: str

    @classmethod
    def from_workflow_run(
        cls,
        client: APIClient,
        workflow: Workflow,
        run: WorkflowRun,
        event_type: EventType,
        event_id: str,
        name: str,
        download_url: str,
    ) -> "GHAArtifact":
        return cls(
            client=client,
            created_at=ensure_aware(run.created_at),
            event_type=event_type,
            event_id=event_id,
            build_commit=run.head_sha,
            commit=run.head_sha,
            workflow_name=workflow.name,
            workflow_file=workflow.path.split("/")[-1],
            number=run.run_number,
            run_id=run.id,
            status=run.conclusion,
            name=name,
            download_url=download_url,
        )

    def download(self, path: Path) -> List[Path]:
        target_dir = path / self.name
        target_dir.mkdir(parents=True, exist_ok=True)
        if any(target_dir.iterdir()):
            log.info(
                "Asset %s from %s (%s) #%s already downloaded to %s; skipping",
                self.name,
                self.workflow_file,
                self.workflow_name,
                self.number,
                path,
            )
            return []
        log.info(
            "Downloading asset %s for %s (%s) #%s to %s",
            self.name,
            self.workflow_file,
            self.workflow_name,
            self.number,
            path,
        )
        self.client.download_zipfile(self.download_url, target_dir)
        return list(iterfiles(target_dir))


class GHReleaseAsset(BaseModel):
    client: APIClient
    published_at: datetime
    tag_name: str
    commit: str
    name: str
    download_url: str

    class Config:
        # To allow APIClient:
        arbitrary_types_allowed = True

    def path_fields(self) -> Dict[str, Any]:
        utc_date = self.published_at.astimezone(timezone.utc)
        return {
            "year": utc_date.strftime("%Y"),
            "month": utc_date.strftime("%m"),
            "day": utc_date.strftime("%d"),
            "hour": utc_date.strftime("%H"),
            "minute": utc_date.strftime("%M"),
            "second": utc_date.strftime("%S"),
            "ci": "github",
            "type": "release",
            "release_tag": self.tag_name,
            "build_commit": self.commit,
            "commit": self.commit,
        }

    def expand_path(self, path_template: str, vars: Dict[str, str]) -> str:
        return expand_template(path_template, self.path_fields(), vars)

    def download(self, path: Path) -> List[Path]:
        target = path / self.name
        if target.exists():
            log.info(
                "Asset %s for release %s already downloaded to %s; skipping",
                self.name,
                self.tag_name,
                target,
            )
            return []
        path.mkdir(parents=True, exist_ok=True)
        log.info(
            "Downloading asset %s for release %s to %s",
            self.name,
            self.tag_name,
            target,
        )
        self.client.download(self.download_url, target)
        return [target]
