from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from functools import cached_property
import os
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel
from yaml import safe_load

from .base import APIClient
from .base import Artifact as BaseArtifact
from .base import BuildAsset, BuildLog, CISystem, EventType, WorkflowSpec
from .util import log, sanitize_pathname


class CircleCI(CISystem):
    workflow_spec: WorkflowSpec

    @staticmethod
    def get_auth_tokens() -> dict[str, str]:
        token = os.environ.get("CIRCLECI_CLI_TOKEN")
        if not token:
            try:
                with (Path.home() / ".circleci" / "cli.yml").open() as fp:
                    token = safe_load(fp)["token"]
            except Exception:
                raise RuntimeError(
                    "CircleCI token not set.  Set via CIRCLECI_CLI_TOKEN"
                    " environment variable or log in with `circleci` client."
                    "  See <https://github.com/con/tinuous#circleci> for more"
                    " information."
                )
            if not token or not isinstance(token, str):
                raise RuntimeError(
                    "CircleCI token not set.  Set via CIRCLECI_CLI_TOKEN"
                    " environment variable or log in with `circleci` client."
                    "  See <https://github.com/con/tinuous#circleci> for more"
                    " information."
                )
        return {"circleci": token}

    @cached_property
    def client(self) -> APIClient:
        return APIClient(
            "https://circleci.com/api",
            {"Circle-Token": self.token},
        )

    def paginate(
        self, path: str, params: Optional[dict[str, str]] = None
    ) -> Iterator[dict]:
        while True:
            data = self.client.get(path, params=params).json()
            yield from data["items"]
            next_page_token = data["next_page_token"]
            if next_page_token is None:
                break
            if params is None:
                params = {}
            params["page-token"] = next_page_token

    def get_pipelines(self) -> Iterator[Pipeline]:
        for item in self.paginate(f"/v2/project/gh/{self.repo}/pipeline"):
            yield Pipeline.parse_obj(item)

    def get_workflows(self, pipeline_id: str) -> Iterator[Workflow]:
        for item in self.paginate(f"/v2/pipeline/{pipeline_id}/workflow"):
            wf = Workflow.parse_obj(item)
            if self.workflow_spec.match(wf.name):
                yield wf

    def get_jobs(self, workflow_id: str) -> Iterator[Job]:
        for item in self.paginate(f"/v2/workflow/{workflow_id}/job"):
            yield Job.parse_obj(item)

    def get_artifacts(self, job_number: int) -> Iterator[Artifact]:
        for item in self.paginate(f"/v2/project/gh/{self.repo}/{job_number}/artifacts"):
            yield Artifact.parse_obj(item)

    def get_jobv1(self, job_number: int) -> Jobv1:
        return Jobv1.parse_obj(
            self.client.get(f"/v1.1/project/gh/{self.repo}/{job_number}").json()
        )

    def get_build_assets(
        self, event_types: list[EventType], logs: bool, artifacts: bool
    ) -> Iterator[BuildAsset]:
        if not logs and not artifacts:
            log.debug("No assets requested for CircleCI runs")
            return
        log.info("Fetching pipelines newer than %s", self.since)
        if self.until is not None:
            log.info("Skipping pipelines newer than %s", self.until)
        for pipeline in self.get_pipelines():
            if pipeline.vcs is None or pipeline.vcs.provider_name.lower() != "github":
                log.debug(
                    "Skipping pipeline %d as it is not associated with GitHub",
                    pipeline.number,
                )
                continue
            # QUESTION: Can a pipeline gain workflows after being created?  If
            # so, we are in trouble.
            if pipeline.created_at <= self.since:
                break
            elif self.until is not None and pipeline.created_at > self.until:
                log.info("Pipeline %d is too new; skipping", pipeline.number)
            workflows = list(self.get_workflows(pipeline.id))
            if any(not wf.status.finished() for wf in workflows):
                log.info("Pipeline %d not completed; skipping", pipeline.number)
                self.register_build(pipeline.created_at, False)
            else:
                log.info(
                    "Found pipeline %d with %d workflow(s)",
                    pipeline.number,
                    len(workflows),
                )
                self.register_build(pipeline.created_at, True)
                run_event = pipeline.trigger.type.as_event_type()
                if run_event in event_types:
                    if run_event in (EventType.CRON, EventType.MANUAL):
                        event_id = pipeline.created_at.strftime("%Y%m%dT%H%M%S")
                    elif run_event is EventType.PUSH:
                        if pipeline.vcs.branch is not None:
                            event_id = pipeline.vcs.branch
                        else:
                            assert pipeline.vcs.tag is not None
                            event_id = pipeline.vcs.tag
                    else:
                        raise AssertionError(f"Unhandled EventType: {run_event!r}")
                    for wf in workflows:
                        for job in self.get_jobs(wf.id):
                            if logs:
                                for step in self.get_jobv1(job.job_number).steps:
                                    for action in step.actions:
                                        yield CCIActionLog(
                                            client=self.client,
                                            created_at=pipeline.created_at,
                                            event_type=run_event,
                                            event_id=event_id,
                                            build_commit=pipeline.vcs.revision,
                                            commit=pipeline.vcs.revision,
                                            number=pipeline.number,
                                            status=action.status.value,
                                            repo=self.repo,
                                            pipeline_id=pipeline.id,
                                            workflow_id=wf.id,
                                            workflow_name=sanitize_pathname(wf.name),
                                            job=job.job_number,
                                            job_id=job.id,
                                            job_name=sanitize_pathname(job.name),
                                            step=str(action.step)
                                            if action.step is not None
                                            else "UNK",
                                            step_name=sanitize_pathname(step.name),
                                            index=action.index,
                                        )
                            if artifacts:
                                for ar in self.get_artifacts(job.job_number):
                                    yield CCIArtifact(
                                        client=self.client,
                                        created_at=pipeline.created_at,
                                        event_type=run_event,
                                        event_id=event_id,
                                        build_commit=pipeline.vcs.revision,
                                        commit=pipeline.vcs.revision,
                                        number=pipeline.number,
                                        status=action.status.value,
                                        repo=self.repo,
                                        pipeline_id=pipeline.id,
                                        workflow_id=wf.id,
                                        workflow_name=wf.name,
                                        job=job.job_number,
                                        job_id=job.id,
                                        job_name=job.name,
                                        path=ar.path,
                                        url=ar.url,
                                    )
                else:
                    log.info(
                        "Event type is %r (%s); skipping",
                        run_event,
                        pipeline.trigger.type.value,
                    )


class PipelineError(BaseModel):
    type: str
    message: str


class PipelineState(Enum):
    CREATED = "created"
    ERRORED = "errored"
    SETUP_PENDING = "setup-pending"
    SETUP = "setup"
    PENDING = "pending"


class TriggerType(Enum):
    SCHEDULED = "scheduled-pipeline"
    EXPLICIT = "explicit"
    API = "api"
    WEBHOOK = "webhook"

    def as_event_type(self) -> EventType:
        if self is TriggerType.SCHEDULED:
            return EventType.CRON
        elif self is TriggerType.EXPLICIT:
            return EventType.MANUAL
        elif self is TriggerType.API:
            # TODO: Is this correct?  Are builds for GitHub pushes ever
            # triggered via the API?
            # Note that the initial run after setting up a project on CircleCI
            # counts as being triggered by the API.
            return EventType.MANUAL
        elif self is TriggerType.WEBHOOK:
            # CircleCI only runs jobs for pushes, not for PR creation
            return EventType.PUSH
        else:
            raise AssertionError(f"Unexpected TriggerType {self!r}")


class Actor(BaseModel):
    login: str
    avatar_url: str


class Trigger(BaseModel):
    type: TriggerType
    received_at: datetime
    actor: Actor


class Commit(BaseModel):
    subject: str
    body: str


class VCS(BaseModel):
    provider_name: str
    target_repository_url: str
    branch: Optional[str] = None
    review_id: Optional[str] = None
    review_url: Optional[str] = None
    revision: str
    tag: Optional[str] = None
    commit: Optional[Commit] = None
    origin_repository_url: str


class Pipeline(BaseModel):
    id: str
    errors: List[PipelineError]
    project_slug: str
    updated_at: Optional[datetime] = None
    number: int
    # trigger_parameters: List[Any] = Field(default_factory=list)
    state: PipelineState
    created_at: datetime
    trigger: Trigger
    vcs: Optional[VCS] = None


class WorkflowStatus(Enum):
    SUCCESS = "success"
    RUNNING = "running"
    NOT_RUN = "not_run"
    FAILED = "failed"
    ERROR = "error"
    FAILING = "failing"
    ON_HOLD = "on_hold"
    CANCELED = "canceled"
    UNAUTHORIZED = "unauthorized"

    def finished(self) -> bool:
        return self in {
            WorkflowStatus.SUCCESS,
            WorkflowStatus.FAILED,
            WorkflowStatus.ERROR,
            WorkflowStatus.CANCELED,
        }


class Workflow(BaseModel):
    pipeline_id: str
    canceled_by: Optional[str] = None
    id: str
    name: str
    project_slug: str
    errored_by: Optional[str] = None
    tag: Optional[str] = None  # Workflow tag, not Git tag
    status: WorkflowStatus
    started_by: str
    pipeline_number: int
    created_at: datetime
    stopped_at: Optional[datetime] = None


class JobStatus(Enum):
    SUCCESS = "success"
    RUNNING = "running"
    NOT_RUN = "not_run"
    FAILED = "failed"
    RETRIED = "retried"
    QUEUED = "queued"
    NOT_RUNNING = "not_running"
    INFRASTRUCTURE_FAIL = "infrastructure_fail"
    TIMEDOUT = "timedout"
    ON_HOLD = "on_hold"
    TERMINATED_UNKNOWN = "terminated-unknown"
    BLOCKED = "blocked"
    CANCELED = "canceled"
    UNAUTHORIZED = "unauthorized"


class JobType(Enum):
    BUILD = "build"
    APPROVAL = "approval"


class Job(BaseModel):
    canceled_by: Optional[str] = None
    dependencies: List[str]
    job_number: int
    id: str
    started_at: Optional[datetime] = None
    name: str
    approved_by: Optional[str] = None
    project_slug: str
    status: JobStatus
    type: JobType
    stopped_at: Optional[datetime] = None
    approval_request_id: Optional[str] = None


class Lifecycle(Enum):
    QUEUED = "queued"
    NOT_RUN = "not_run"
    NOT_RUNNING = "not_running"
    RUNNING = "running"
    FINISHED = "finished"


class Outcome(Enum):
    CANCELED = "canceled"
    INFRASTRUCTURE_FAIL = "infrastructure_fail"
    TIMEDOUT = "timedout"
    FAILED = "failed"
    NO_TESTS = "no_tests"
    SUCCESS = "success"


class Jobv1Status(Enum):
    RETRIED = "retried"
    CANCELED = "canceled"
    INFRASTRUCTURE_FAIL = "infrastructure_fail"
    TIMEDOUT = "timedout"
    NOT_RUN = "not_run"
    RUNNING = "running"
    FAILED = "failed"
    QUEUED = "queued"
    NOT_RUNNING = "not_running"
    NO_TESTS = "no_tests"
    FIXED = "fixed"
    SUCCESS = "success"


class Action(BaseModel):
    bash_command: Optional[str] = None
    run_time_millis: int
    start_time: datetime
    end_time: datetime
    name: str
    exit_code: Optional[int] = None
    type: str
    index: int
    status: Jobv1Status
    step: Optional[int] = None
    source: Optional[str] = None
    failed: Optional[bool] = None
    parallel: bool = False
    # output_url: str
    # messages: List[str?] = Field(default_factory=list)
    # continue: Optional[???] = None
    # timedout: Optional[???] = None
    # infrastructure_fail: Optional[???] = None


class Step(BaseModel):
    name: str
    actions: List[Action]


class Jobv1(BaseModel):
    vcs_url: str
    build_url: str
    build_num: int
    branch: str
    vcs_revision: str
    committer_name: Optional[str] = None
    committer_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    why: str
    # dont_build: Optional[str?]
    queued_at: Optional[datetime] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    build_time_millis: int
    username: str
    reponame: str
    lifecycle: Lifecycle
    outcome: Outcome
    status: Jobv1Status
    retry_of: Optional[int] = None
    steps: List[Step]


class Artifact(BaseModel):
    path: str
    node_index: int
    url: str


class CCIActionLog(BuildLog):
    repo: str
    pipeline_id: str
    workflow_id: str
    workflow_name: str
    job: int
    job_id: str
    job_name: str
    step: str
    step_name: str
    index: int

    @property
    def id(self) -> str:
        return f"job {self.job}, step {self.step}-{self.index}"

    def path_fields(self) -> dict[str, Any]:
        fields = super().path_fields()
        fields.update(
            {
                "ci": "circleci",
                "pipeline_id": self.pipeline_id,
                "wf_id": self.workflow_id,
                "wf_name": self.workflow_name,
                "job": self.job,
                "job_id": self.job_id,
                "job_name": self.job_name,
                "step": self.step,
                "step_name": self.step_name,
                "index": self.index,
            }
        )
        return fields

    def download(self, path: Path) -> list[Path]:
        if path.exists():
            log.info(
                "Logs for %s already downloaded to %s; skipping",
                self.id,
                path,
            )
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("Downloading logs for %s to %s", self.id, path)
        self.client.download(
            f"/v1.1/project/github/{self.repo}/{self.job}/output/{self.step}/{self.index}?file=true",
            path,
        )
        return [path]


class CCIArtifact(BaseArtifact):
    repo: str
    pipeline_id: str
    workflow_id: str
    workflow_name: str
    job: int
    job_id: str
    job_name: str
    path: str
    url: str

    def path_fields(self) -> dict[str, Any]:
        fields = super().path_fields()
        fields.update(
            {
                "ci": "circleci",
                "pipeline_id": self.pipeline_id,
                "wf_id": self.workflow_id,
                "wf_name": self.workflow_name,
                "job": self.job,
                "job_id": self.job_id,
                "job_name": self.job_name,
            }
        )
        return fields

    def download(self, path: Path) -> List[Path]:
        target = path / self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            log.info(
                "Artifact %r from %s #%d, job #%d already downloaded to %s; skipping",
                self.path,
                self.workflow_name,
                self.number,
                self.job,
                path,
            )
            return []
        log.info(
            "Downloading artifact %r for %s #%d, job #%d, to %s",
            self.path,
            self.workflow_name,
            self.number,
            self.job,
            path,
        )
        self.client.download(self.url, target)
        return [target]
