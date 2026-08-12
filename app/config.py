"""Konfiguration via miljøvariabler (sættes i Portainer-stacken)."""

import os
import re
from dataclasses import dataclass

# Tabelnavne kan ikke sendes som SQL-parametre — de skal interpoleres ind i
# sætningen. Derfor valideres de som rene identifikatorer ved opstart, så en
# tastefejl (eller noget værre) fejler med det samme frem for inde i en query.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _env(name: str, default: str | None = None) -> str:
    """Hent en miljøvariabel og fjern omsluttende anførselstegn.

    Lokalt kræver docker --env-file quotes om værdier med '#' i, mens
    Portainer sætter dem uden. Vi accepterer begge dele.
    """
    raw = os.environ.get(name, default)
    if raw is None:
        raise KeyError(f"Miljøvariablen {name} mangler")
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _table(name: str) -> str:
    value = _env(name)
    if not _IDENTIFIER.match(value):
        raise ValueError(
            f"{name}={value!r} ser ikke ud som et gyldigt tabelnavn. "
            "Forventet format: skema.tabel, fx dbo.min_tabel"
        )
    return value


def _conn_str(database: str) -> str:
    driver = _env("DB_DRIVER").strip("{}")
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={_env('DB_SERVER')};"
        f"DATABASE={database};"
        f"UID={_env('DB_USERNAME')};"
        f"PWD={_env('DB_PASSWORD')};"
        "TrustServerCertificate=yes;"
    )


@dataclass(frozen=True)
class Settings:
    xflow_conn: str
    skolekube_conn: str
    request_table: str
    sensitive_table: str
    enrollment_table: str
    poll_interval_seconds: int
    max_attempts: int
    mailer: str          # "console" eller "api"
    output_dir: str      # bruges kun af console-maileren
    mail_subject: str
    # Bruges kun af api-maileren
    mail_api_url: str
    mail_api_key: str
    shared_dir: str
    mail_api_timeout: int


def load_settings() -> Settings:
    mailer = _env("MAILER", "console")

    # API-nøglen er kun påkrævet, når vi faktisk sender. Kræves den altid,
    # kan man ikke teste med MAILER=console uden at kende den.
    if mailer == "api":
        mail_api_key = _env("MAIL_API_KEY")
        if not mail_api_key:
            raise ValueError("MAIL_API_KEY er tom, men MAILER=api")
    else:
        mail_api_key = _env("MAIL_API_KEY", "")

    return Settings(
        xflow_conn=_conn_str(_env("XFLOW_DB")),
        skolekube_conn=_conn_str(_env("SKOLEKUBE_DB")),
        request_table=_table("XFLOW_TABLE"),
        sensitive_table=_table("SKOLEKUBE_SENSITIVE_TABLE"),
        enrollment_table=_table("SKOLEKUBE_ENROLLMENT_TABLE"),
        poll_interval_seconds=int(_env("POLL_INTERVAL_SECONDS", "300")),
        max_attempts=int(_env("MAX_ATTEMPTS", "3")),
        mailer=mailer,
        output_dir=_env("OUTPUT_DIR", "/data/output"),
        mail_subject=_env("MAIL_SUBJECT", "Skolehistorik – bestilling #{request_id}"),
        mail_api_url=_env("MAIL_API_URL", "http://mail-client-api:8000"),
        mail_api_key=mail_api_key,
        shared_dir=_env("SHARED_DIR", "/shared"),
        mail_api_timeout=int(_env("MAIL_API_TIMEOUT", "30")),
    )
