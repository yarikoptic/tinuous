from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel

from .util import log

STATE_FILE = ".tinuous.state.json"
OLD_STATE_FILE = ".dlstate.json"


class State(BaseModel):
    github: Optional[datetime] = None
    travis: Optional[datetime] = None
    appveyor: Optional[datetime] = None
    circleci: Optional[datetime] = None


class StateFile(BaseModel):
    path: Path
    state: State
    migrating: bool = False
    modified: bool = False

    @classmethod
    def from_file(cls, path: Union[str, Path, None] = None) -> "StateFile":
        migrating = False
        p: Path
        if path is None:
            cwd = Path.cwd()
            if (cwd / STATE_FILE).exists():
                p = cwd / STATE_FILE
            elif (cwd / OLD_STATE_FILE).exists():
                log.debug("Statefile with old name found; will rename on first write")
                p = cwd / OLD_STATE_FILE
                migrating = True
            else:
                p = cwd / STATE_FILE
        else:
            p = Path(path)
        try:
            s = p.read_text()
        except FileNotFoundError:
            state = State()
        else:
            if s.strip() == "":
                state = State()
            else:
                state = State.parse_raw(s)
        return cls(path=p, state=state, migrating=migrating)

    def get_since(self, ciname: str) -> Optional[datetime]:
        t = getattr(self.state, ciname)
        assert t is None or isinstance(t, datetime)
        return t

    def set_since(self, ciname: str, since: datetime) -> None:
        if getattr(self.state, ciname) == since:
            return
        setattr(self.state, ciname, since)
        log.debug("%s timestamp floor updated to %s", ciname, since)
        if self.migrating:
            log.debug("Renaming old statefile %s to %s", OLD_STATE_FILE, STATE_FILE)
            newpath = self.path.with_name(STATE_FILE)
            newpath.write_text(self.state.json())
            self.path.unlink(missing_ok=True)
            self.path = newpath
            self.migrating = False
        else:
            self.path.write_text(self.state.json())
        self.modified = True
