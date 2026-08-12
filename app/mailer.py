"""Afsendelse af PDF'en til bestilleren.

ConsoleMailer gemmer PDF'en til disk og sender ingenting — nyttig til test.
ApiMailer sender via mail-client-servicen: filen lægges på det delte volume
(/shared) og refereres ved sti i POST /send, som mail-clienten selv læser.
"""

import logging
from pathlib import Path
from typing import Protocol

import requests

log = logging.getLogger(__name__)


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, pdf: bytes, filename: str) -> None:
        ...


class ConsoleMailer:
    """Gemmer PDF'en i output-mappen og logger, hvad der ville være sendt."""

    def __init__(self, output_dir: str) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def send(self, to: str, subject: str, body: str, pdf: bytes, filename: str) -> None:
        path = self._dir / filename
        path.write_bytes(pdf)
        log.info("MAILER=console: PDF gemt som %s (ville være sendt til %s, emne: %r)",
                 path, to, subject)


class ApiMailer:
    """Sender via mail-clientens POST /send.

    API'et tager ikke filindhold, men absolutte stier til filer på det delte
    volume. Vores container og mail-clienten monterer samme volume på /shared,
    så stien vi skriver til, er den samme sti API'et læser fra.
    """

    def __init__(self, base_url: str, api_key: str, shared_dir: str,
                 timeout: int) -> None:
        self._url = base_url.rstrip("/") + "/send"
        self._key = api_key
        self._dir = Path(shared_dir)
        self._timeout = timeout
        self._dir.mkdir(parents=True, exist_ok=True)

    def send(self, to: str, subject: str, body: str, pdf: bytes, filename: str) -> None:
        path = self._dir / filename
        path.write_bytes(pdf)
        try:
            response = requests.post(
                self._url,
                headers={"X-API-Key": self._key},
                json={
                    "to": to,
                    "subject": subject,
                    "body": body,
                    "files": [str(path)],
                },
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                # Svarteksten indeholder ofte den egentlige årsag, og den skal
                # med i error_message på rækken — ikke kun statuskoden.
                raise RuntimeError(
                    f"mail-client svarede {response.status_code}: "
                    f"{response.text[:500]}"
                )
            log.info("Mail sendt til %s (vedhæftning: %s)", to, path.name)
        finally:
            # PDF'en indeholder personfølsomme oplysninger og skal ikke ligge
            # på det delte volume længere end nødvendigt. Fejler oprydningen,
            # må det ikke vælte en mail der allerede er afsendt.
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Kunne ikke slette %s: %s", path, exc)


def create_mailer(settings) -> Mailer:
    if settings.mailer == "console":
        return ConsoleMailer(settings.output_dir)
    if settings.mailer == "api":
        return ApiMailer(
            base_url=settings.mail_api_url,
            api_key=settings.mail_api_key,
            shared_dir=settings.shared_dir,
            timeout=settings.mail_api_timeout,
        )
    raise ValueError(
        f"Ukendt MAILER: {settings.mailer!r} (forventede 'console' eller 'api')"
    )
