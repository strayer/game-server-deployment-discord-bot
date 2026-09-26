"""Tests for the deSEC client (discord_bot.dns); requests is mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from discord_bot import dns

TOKEN = "s3cr3t-token"
ZONE = "games.example.tld"
RRSETS_URL = f"{dns.API}/domains/{ZONE}/rrsets/"


def _response(status: int, text: str = "") -> MagicMock:
    return MagicMock(status_code=status, text=text)


@pytest.fixture
def request_mock():
    with (
        patch.object(dns.requests, "request", return_value=_response(200)) as req,
        patch.object(dns.time, "sleep"),
    ):
        yield req


@pytest.fixture
def client() -> dns.DesecClient:
    return dns.DesecClient(TOKEN, ZONE)


def _rrsets(a: list[str], aaaa: list[str]) -> list[dict]:
    return [
        {"subname": "valheim", "type": "A", "ttl": dns.TTL, "records": a},
        {"subname": "valheim", "type": "AAAA", "ttl": dns.TTL, "records": aaaa},
    ]


@pytest.mark.parametrize(
    ("ipv6", "aaaa"),
    [("2001:db8::1", ["2001:db8::1"]), (None, [])],
    ids=["dual-stack", "ipv4-only-deletes-stale-aaaa"],
)
def test_publish_sends_one_bulk_put(client, request_mock, ipv6, aaaa):
    client.publish("valheim", "203.0.113.10", ipv6)

    request_mock.assert_called_once_with(
        "PUT",
        RRSETS_URL,
        headers={"Authorization": f"Token {TOKEN}"},
        json=_rrsets(["203.0.113.10"], aaaa),
        timeout=10,
    )


def test_clear_deletes_a_and_aaaa(client, request_mock):
    client.clear("valheim")

    assert request_mock.call_args.kwargs["json"] == _rrsets([], [])


@pytest.mark.parametrize(
    ("status", "raises"), [(200, False), (401, True)], ids=["ok", "unauthorized"]
)
def test_check_gets_the_domain(client, request_mock, status, raises):
    request_mock.return_value = _response(status)

    if raises:
        with pytest.raises(dns.DnsError, match="HTTP 401"):
            client.check()
    else:
        client.check()
    assert request_mock.call_args.args == ("GET", f"{dns.API}/domains/{ZONE}/")


def test_http_error_reports_status_only_and_is_not_retried(client, request_mock):
    request_mock.return_value = _response(400, f"bad ttl; token was {TOKEN}")

    with pytest.raises(dns.DnsError) as exc_info:
        client.clear("valheim")

    assert str(exc_info.value) == f"deSEC PUT /domains/{ZONE}/rrsets/: HTTP 400"
    request_mock.assert_called_once()


def test_transport_error_reports_type_name_only(client, request_mock):
    request_mock.side_effect = requests.ConnectionError(f"Authorization: Token {TOKEN}")

    with pytest.raises(dns.DnsError) as exc_info:
        client.clear("valheim")

    assert str(exc_info.value).endswith(": ConnectionError")
    # Sentry serializes chained exceptions too.
    assert exc_info.value.__cause__ is None and exc_info.value.__context__ is None


@pytest.mark.parametrize(
    ("statuses", "raises"),
    [([503, 200], False), ([429, 502, 500], True)],
    ids=["retried-then-ok", "exhausted-after-3"],
)
def test_transient_errors_are_retried(client, request_mock, statuses, raises):
    request_mock.side_effect = [_response(s) for s in statuses]

    if raises:
        with pytest.raises(dns.DnsError, match="HTTP 500"):
            client.clear("valheim")
    else:
        client.clear("valheim")
    assert request_mock.call_count == len(statuses)


@pytest.mark.parametrize(
    ("token", "zone", "variable"),
    [
        ("", ZONE, "DESEC_TOKEN"),
        ("abc–def ghi", ZONE, "DESEC_TOKEN"),
        (TOKEN, "", "DESEC_ZONE"),
        (TOKEN, "games.example.tld; rm -rf /", "DESEC_ZONE"),
    ],
    ids=["token-missing", "token-not-printable-ascii", "zone-missing", "zone-invalid"],
)
def test_config_errors_name_the_variable(monkeypatch, token, zone, variable):
    monkeypatch.setenv("DESEC_TOKEN", token)
    monkeypatch.setenv("DESEC_ZONE", zone)

    with pytest.raises(dns.DnsError, match=variable) as exc_info:
        dns.config()

    assert token == "" or token not in str(exc_info.value)
