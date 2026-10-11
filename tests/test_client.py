"""Client error paths that must not leak the credentials."""
import asyncio

import aiohttp
import pytest
import yarl

from hon import HonClient, HonError


class FailingSession:
    """/ciam/authorize answering an HTML error page, as in maintenance."""

    def get(self, url, params, headers):

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def json(self):
                info = aiohttp.RequestInfo(yarl.URL(url).with_query(params), "GET", {}, yarl.URL(url))
                raise aiohttp.ContentTypeError(info, (), status=200, message="text/html")

        return Response()


def test_login_errors_keep_the_password_out():
    client = HonClient(FailingSession(), "user@example.com", "hunter2")
    with pytest.raises(HonError) as raised:
        asyncio.run(client.login())
    assert "hunter2" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
