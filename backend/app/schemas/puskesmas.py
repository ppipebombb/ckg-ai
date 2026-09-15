import ipaddress
import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator

_BASE_URL_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)

# Reserved / internal name spaces that must never be a scrape target — the
# headless browser navigates these URLs server-side, so allowing them is SSRF
# (cloud metadata, intranet hosts, loopback). Real portals live on public TLDs
# (.com / .id / .go.id …), so blocking these costs nothing.
_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_INTERNAL_SUFFIXES = (
    ".local", ".localhost", ".internal", ".intranet", ".lan",
    ".home", ".corp", ".test", ".example", ".invalid",
)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _validate_base_url(v: str) -> str:
    if not _BASE_URL_RE.match(v):
        raise ValueError(
            "must be a base domain only (e.g. 'domain.com', 'sub.domain.id') "
            "without scheme, path, query, or fragment"
        )
    host = v.lower()
    # Defensive: the regex already requires an alphabetic TLD (so bare IPv4/IPv6
    # can't match), but reject IP literals explicitly in case it's ever relaxed.
    if _is_ip_literal(host):
        raise ValueError("must be a domain name, not an IP address")
    if host in _BLOCKED_HOSTS or host.endswith(_INTERNAL_SUFFIXES):
        raise ValueError("internal/reserved hostnames are not allowed as a scrape target")
    # NOTE: this cannot stop DNS rebinding (a public name resolving to a private
    # IP). The defence-in-depth for that is network egress policy on the scraper
    # container — it must not be able to route to RFC1918 / 169.254.0.0/16.
    return v


BaseUrl = Annotated[str, AfterValidator(_validate_base_url)]


class AsikAlamatLevel(BaseModel):
    name: str
    code: str


class AsikDefaultAlamat(BaseModel):
    """The puskesmas' default domicile for the ASIK create-patient cascade.

    All four levels are required together — a partial address cannot drive the
    ASIK registration picker (each level is a click). name/code come straight
    from ASIK's teritorial-service list so they match the live cascade exactly.
    """
    provinsi: AsikAlamatLevel
    kota: AsikAlamatLevel
    kecamatan: AsikAlamatLevel
    kelurahan: AsikAlamatLevel


class PuskesmasCreate(BaseModel):
    name: str
    epus_url: BaseUrl
    asik_url: BaseUrl
    asik_default_alamat: AsikDefaultAlamat | None = None


class PuskesmasUpdate(BaseModel):
    name: str | None = None
    epus_url: BaseUrl | None = None
    asik_url: BaseUrl | None = None
    asik_default_alamat: AsikDefaultAlamat | None = None

    @model_validator(mode="after")
    def _no_clearing_urls(self) -> "PuskesmasUpdate":
        for f in ("epus_url", "asik_url"):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(
                    f"{f} cannot be cleared; must be a valid base domain"
                )
        return self


class CredIn(BaseModel):
    email: str
    password: str


class CredOut(BaseModel):
    email: str
    password: str


class PuskesmasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    epus_url: str | None
    asik_url: str | None
    asik_default_alamat: AsikDefaultAlamat | None
    created_at: datetime
    updated_at: datetime


class PuskesmasDetailOut(PuskesmasOut):
    is_epus_cred_set: bool
    is_asik_cred_set: bool
