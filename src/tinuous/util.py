from collections import deque
from datetime import datetime, timezone
import email.utils
import logging
import os
from pathlib import Path
import re
from string import Formatter
import subprocess
from time import time
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Union

log = logging.getLogger("tinuous")


def ensure_aware(dt: datetime) -> datetime:
    # Pygithub returns naïve datetimes for timestamps with a "Z" suffix.  Until
    # that's fixed <https://github.com/PyGithub/PyGithub/pull/1831>, we need to
    # make such datetimes timezone-aware manually.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def removeprefix(s: str, prefix: str) -> str:
    n = len(prefix)
    return s[n:] if s[:n] == prefix else s


def iterfiles(dirpath: Path) -> Iterator[Path]:
    dirs = deque([dirpath])
    while dirs:
        d = dirs.popleft()
        for p in d.iterdir():
            if p.is_dir():
                dirs.append(p)
            else:
                yield p


class LazySlicingFormatter(Formatter):
    """
    A `string.Formatter` subclass that:

    - accepts a second set of format kwargs that can refer to the main kwargs
      or each other and are only templated as needed
    - supports indexing strings & other sequences with slices
    """

    def __init__(self, var_defs: Dict[str, str]):
        self.var_defs: Dict[str, str] = var_defs
        self.expanded_vars: Dict[str, str] = {}
        super().__init__()

    def get_value(
        self, key: Union[int, str], args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> Any:
        if isinstance(key, int):
            return args[key]
        elif key in kwargs:
            return kwargs[key]
        elif key in self.expanded_vars:
            return self.expanded_vars[key]
        elif key in self.var_defs:
            self.expanded_vars[key] = self.format(self.var_defs[key], **kwargs)
            return self.expanded_vars[key]
        else:
            raise KeyError(key)

    def get_field(
        self, field_name: str, args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> Any:
        m = re.match(r"\w+", field_name)
        assert m, f"format field name {field_name!r} does not start with arg_name"
        s_key = m.group()
        assert isinstance(s_key, str)
        key: Union[int, str]
        if s_key.isdigit():
            key = int(s_key)
        else:
            key = s_key
        obj = self.get_value(key, args, kwargs)
        s = field_name[m.end() :]
        while s:
            m = re.match(r"\.(?P<attr>\w+)|\[(?P<index>[^]]+)\]", s)
            assert m, f"format field name {field_name!r} has invalid attr/index"
            s = s[m.end() :]
            attr, index = m.group("attr", "index")
            if attr is not None:
                obj = getattr(obj, attr)
            else:
                assert index is not None  # type: ignore[unreachable]
                try:
                    sl = parse_slice(index)
                except ValueError:
                    if index.isdigit():
                        obj = obj[int(index)]
                    else:
                        obj = obj[index]
                else:
                    obj = obj[sl]
        return obj, key


def expand_template(
    template_str: str, fields: Dict[str, Any], vars: Dict[str, str]
) -> str:
    return LazySlicingFormatter(vars).format(template_str, **fields)


SLICE_RGX = re.compile(r"(?P<start>-?\d+)?:(?P<stop>-?\d+)?(?::(?P<step>-?\d+)?)?")


def parse_slice(s: str) -> slice:
    if m := SLICE_RGX.fullmatch(s):
        s_start, s_stop, s_step = m.group("start", "stop", "step")
        start: Optional[int] = None if s_start is None else int(s_start)
        stop: Optional[int] = None if s_stop is None else int(s_stop)
        step: Optional[int]
        if s_step is None or s_step == "":
            step = None
        else:
            step = int(s_step)
        return slice(start, stop, step)
    else:
        raise ValueError(s)


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        r = subprocess.run(
            ["git", "config", "hub.oauthtoken"],
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError(
                "GitHub OAuth token not set.  Set via GITHUB_TOKEN"
                " environment variable or hub.oauthtoken Git config option."
            )
        token = r.stdout.strip()
    return token


def sanitize_pathname(s: str) -> str:
    return re.sub(
        r'[\0\x5C/<>:|"?*%]', lambda m: sanitize_str(m.group()), re.sub(r"\s", " ", s)
    )


def sanitize_str(s: str) -> str:
    return "".join("%{:02x}".format(b) for b in s.encode("utf-8"))


def delay_until(dt: datetime) -> float:
    # Take `max()` just in case we're right up against `dt`, and add 1 because
    # `sleep()` isn't always exactly accurate
    return max((dt - datetime.now(timezone.utc)).total_seconds(), 0) + 1


# <https://github.com/urllib3/urllib3/blob/214b184923388328919b0a4b0c15bff603aa51be/src/urllib3/util/retry.py#L304>
def parse_retry_after(retry_after: str) -> Optional[float]:
    # Whitespace: https://tools.ietf.org/html/rfc7230#section-3.2.4
    if re.fullmatch(r"\s*[0-9]+\s*", retry_after):
        return int(retry_after)
    else:
        retry_date_tuple = email.utils.parsedate_tz(retry_after)
        if retry_date_tuple is None:
            return None
        retry_date = email.utils.mktime_tz(retry_date_tuple)
        return max(retry_date - time(), 0)
