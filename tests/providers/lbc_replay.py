"""Feed recorded Leboncoin responses to the real `lbc` client, in place of its HTTP session."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lbc
from curl_cffi.requests import Response

FIXTURES = Path(__file__).parent.parent / "fixtures" / "leboncoin"
SEARCH_URL = "https://api.leboncoin.fr/finder/search"
AD_URL = "https://api.leboncoin.fr/api/adfinder/v1/classified/{}"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@dataclass
class Recorded:
    status: int
    body: str


@dataclass
class ReplaySession:
    """Stands in for lbc's curl_cffi session: answers recorded bodies by URL, 404s the rest."""

    answers: dict[str, Recorded]
    sent: list[tuple[str, str, Any]] = field(default_factory=list)

    def request(self, method: str, url: str, json: Any = None, **_: Any) -> Response:
        self.sent.append((method, url, json))
        answer = self.answers.get(url, Recorded(404, "not recorded"))
        response = Response()
        response.status_code = answer.status
        response.ok = 200 <= answer.status < 400  # as curl_cffi's own session sets it
        response.content = answer.body.encode()
        response.encoding = "utf-8"
        return response

    def close(self) -> None:
        pass

    def payloads(self) -> list[Any]:
        return [payload for _, url, payload in self.sent if url == SEARCH_URL]


def replaying_client(session: ReplaySession) -> lbc.Client:
    """A real lbc.Client whose HTTP session is the replay, so lbc's own parsing still runs."""

    class ReplayClient(lbc.Client):
        def _init_session(self, *args: Any, **kwargs: Any) -> Any:
            return session

    return ReplayClient(max_retries=0)
