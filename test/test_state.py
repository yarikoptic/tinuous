from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from tinuous.state import OLD_STATE_FILE, STATE_FILE, State, StateFile


def test_migration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with open(OLD_STATE_FILE, "w") as fp:
        json.dump(
            {
                "github": "2021-06-11T14:44:17+00:00",
                "travis": "2021-02-03T04:05:06+00:00",
            },
            fp,
        )
    statefile = StateFile.from_file(None)
    assert os.listdir() == [OLD_STATE_FILE]
    assert statefile.state == State(
        github=datetime(2021, 6, 11, 14, 44, 17, tzinfo=timezone.utc),
        travis=datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        appveyor=None,
        circleci=None,
    )
    assert statefile.path == tmp_path / OLD_STATE_FILE
    assert statefile.migrating
    assert not statefile.modified

    assert statefile.get_since("github") == datetime(
        2021, 6, 11, 14, 44, 17, tzinfo=timezone.utc
    )
    assert os.listdir() == [OLD_STATE_FILE]
    assert statefile.path == tmp_path / OLD_STATE_FILE
    assert statefile.migrating
    assert not statefile.modified

    statefile.set_since(
        "github", datetime(2021, 6, 11, 14, 44, 17, tzinfo=timezone.utc)
    )
    assert os.listdir() == [OLD_STATE_FILE]
    assert statefile.path == tmp_path / OLD_STATE_FILE
    assert statefile.migrating
    assert not statefile.modified

    newdt = datetime(2021, 6, 11, 14, 48, 39, tzinfo=timezone.utc)
    statefile.set_since("github", newdt)
    assert os.listdir() == [STATE_FILE]
    assert statefile.state == State(
        github=newdt,
        travis=datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        appveyor=None,
        circleci=None,
    )
    assert statefile.path == tmp_path / STATE_FILE
    assert not statefile.migrating
    assert statefile.modified  # type: ignore[unreachable]
    with open(STATE_FILE) as fp:
        data = json.load(fp)
    assert data == {
        "github": "2021-06-11T14:48:39+00:00",
        "travis": "2021-02-03T04:05:06+00:00",
        "appveyor": None,
        "circleci": None,
    }


def test_defaulting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    statefile = StateFile.from_file(None)
    assert os.listdir() == []
    assert statefile.state == State(
        github=None, travis=None, appveyor=None, circleci=None
    )
    assert statefile.path == tmp_path / STATE_FILE
    assert not statefile.migrating
    assert not statefile.modified

    assert statefile.get_since("github") is None
    assert os.listdir() == []

    newdt = datetime(2021, 6, 11, 14, 55, 1, tzinfo=timezone.utc)
    statefile.set_since("github", newdt)
    assert os.listdir() == [STATE_FILE]
    assert statefile.state == State(
        github=newdt, travis=None, appveyor=None, circleci=None
    )
    assert statefile.modified
    with open(STATE_FILE) as fp:  # type: ignore[unreachable]
        data = json.load(fp)
    assert data == {
        "github": "2021-06-11T14:55:01+00:00",
        "travis": None,
        "appveyor": None,
        "circleci": None,
    }


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "{}",
        '{"travis": null}',
        '{"github": null, "travis": null, "appveyor": null}',
        '{"github": null, "travis": null, "appveyor": null, "circleci": null}',
    ],
)
def test_empty(contents: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    f = Path(STATE_FILE)
    f.write_text(contents)
    statefile = StateFile.from_file(None)
    assert os.listdir() == [STATE_FILE]
    assert statefile.state == State(
        github=None, travis=None, appveyor=None, circleci=None
    )
    assert statefile.path == tmp_path / STATE_FILE
    assert not statefile.migrating
    assert not statefile.modified

    assert statefile.get_since("github") is None
    assert os.listdir() == [STATE_FILE]
    assert f.read_text() == contents

    newdt = datetime(2021, 6, 11, 14, 55, 1, tzinfo=timezone.utc)
    statefile.set_since("github", newdt)
    assert os.listdir() == [STATE_FILE]
    assert statefile.state == State(
        github=newdt, travis=None, appveyor=None, circleci=None
    )
    assert statefile.modified
    with f.open() as fp:  # type: ignore[unreachable]
        data = json.load(fp)
    assert data == {
        "github": "2021-06-11T14:55:01+00:00",
        "travis": None,
        "appveyor": None,
        "circleci": None,
    }


def test_populated_explicit_path(tmp_path: Path) -> None:
    f = tmp_path / OLD_STATE_FILE
    with f.open("w") as fp:
        json.dump(
            {
                "github": "2021-06-11T15:07:41+00:00",
                "travis": "2021-02-03T04:05:06+00:00",
                "appveyor": None,
                "circleci": None,
            },
            fp,
        )
    statefile = StateFile.from_file(f)
    ghdt = datetime(2021, 6, 11, 15, 7, 41, tzinfo=timezone.utc)
    travdt = datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    assert statefile.state == State(
        github=ghdt, travis=travdt, appveyor=None, circleci=None
    )
    assert statefile.path == f
    assert not statefile.migrating
    assert not statefile.modified
    assert statefile.get_since("github") == ghdt
    assert statefile.get_since("travis") == travdt
    assert statefile.get_since("appveyor") is None
    assert statefile.get_since("circleci") is None
    newdt = datetime(2021, 6, 11, 15, 11, 50, tzinfo=timezone.utc)
    statefile.set_since("github", newdt)
    assert statefile.state == State(
        github=newdt, travis=travdt, appveyor=None, circleci=None
    )
    assert statefile.path == f
    assert not statefile.migrating
    assert statefile.modified
    with f.open() as fp:  # type: ignore[unreachable]
        data = json.load(fp)
    assert data == {
        "github": "2021-06-11T15:11:50+00:00",
        "travis": "2021-02-03T04:05:06+00:00",
        "appveyor": None,
        "circleci": None,
    }
