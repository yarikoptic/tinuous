import pytest

from tinuous.base import GHWorkflowSpec


@pytest.mark.parametrize(
    "spec,path,r",
    [
        (
            GHWorkflowSpec(include=["build.yaml"], exclude=[], regex=False),
            ".github/workflows/build.yaml",
            True,
        ),
        (
            GHWorkflowSpec(include=["build.yaml"], exclude=[], regex=False),
            ".github/workflows/build.yml",
            False,
        ),
        (
            GHWorkflowSpec(include=[r"^build-*\.ya?ml$"], exclude=[], regex=False),
            ".github/workflows/build-foo.yml",
            False,
        ),
        (
            GHWorkflowSpec(include=[r"^build-.*\.ya?ml$"], exclude=[], regex=True),
            ".github/workflows/build-foo.yml",
            True,
        ),
        (
            GHWorkflowSpec(include=[r"^build-.*\.ya?ml$"], exclude=[], regex=True),
            ".github/workflows/build-foo.yaml",
            True,
        ),
        (
            GHWorkflowSpec(
                include=[r"^build-.*\.ya?ml$"],
                exclude=[r"^build-box\.yaml$"],
                regex=True,
            ),
            ".github/workflows/build-foo.yaml",
            True,
        ),
        (
            GHWorkflowSpec(
                include=[r"^build-.*\.ya?ml$"],
                exclude=[r"^build-box\.yaml$"],
                regex=True,
            ),
            ".github/workflows/build-box.yaml",
            False,
        ),
        (
            GHWorkflowSpec(include=["build.yaml", "test.yml"], exclude=[], regex=True),
            ".github/workflows/build.yaml",
            True,
        ),
        (
            GHWorkflowSpec(include=["build.yaml", "test.yml"], exclude=[], regex=True),
            ".github/workflows/test.yml",
            True,
        ),
    ],
)
def test_workflowspec_match(spec: GHWorkflowSpec, path: str, r: bool) -> None:
    assert spec.match(path) is r
