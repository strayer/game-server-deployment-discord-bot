"""Publish / clear the per-game A/AAAA records in a deSEC.io zone."""

from __future__ import annotations

import os
import re
import time

import requests
from loguru import logger

API = "https://desec.io/api/v1"
TTL = 900  # the zone's deSEC minimum_ttl; change if support lowers it
_ATTEMPTS = 3


class DnsError(Exception):
    pass


def config() -> tuple[str, str]:
    token = os.environ.get("DESEC_TOKEN", "").strip()
    zone = os.environ.get("DESEC_ZONE", "").strip().rstrip(".").lower()
    # A malformed token would end up in (and leak via) requests' header errors.
    if not token or not all("!" <= c <= "~" for c in token):
        raise DnsError("DESEC_TOKEN is missing or not printable ASCII")
    if not re.fullmatch(r"[a-z0-9.-]+", zone):
        raise DnsError("DESEC_ZONE is missing or not a plain DNS name")
    return token, zone


class DesecClient:
    def __init__(self, token: str, zone: str) -> None:
        self._headers = {"Authorization": f"Token {token}"}
        self.zone = zone

    def hostname(self, subname: str) -> str:
        return f"{subname}.{self.zone}"

    def check(self) -> None:
        self._call("GET", f"/domains/{self.zone}/")

    def publish(self, subname: str, ipv4: str, ipv6: str | None) -> None:
        # AAAA=[] deletes a stale AAAA from an earlier run.
        self._write(subname, [ipv4], [ipv6] if ipv6 else [])

    def clear(self, subname: str) -> None:
        self._write(subname, [], [])

    def _write(self, subname: str, a: list[str], aaaa: list[str]) -> None:
        logger.info(
            "DNS {h}: A={a} AAAA={aaaa}", h=self.hostname(subname), a=a, aaaa=aaaa
        )
        rrsets = [
            {"subname": subname, "type": t, "ttl": TTL, "records": records}
            for t, records in (("A", a), ("AAAA", aaaa))
        ]
        self._call("PUT", f"/domains/{self.zone}/rrsets/", json=rrsets)

    def _call(self, method: str, path: str, json: list | None = None) -> None:
        # Never put response bodies or str(requests exception) in errors: they
        # may echo the token.
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                response = requests.request(
                    method, API + path, headers=self._headers, json=json, timeout=10
                )
            except requests.RequestException as exc:
                error = DnsError(f"deSEC {method} {path}: {type(exc).__name__}")
            else:
                status = response.status_code
                if status < 400:
                    return
                error = DnsError(f"deSEC {method} {path}: HTTP {status}")
                if status != 429 and status < 500:
                    raise error
            if attempt < _ATTEMPTS:
                time.sleep(2)
        raise error


def client_from_env() -> DesecClient:
    return DesecClient(*config())
