"""Worker-loop: poll request-loggen, generér PDF og send til bestilleren.

Kør med:
    python -m app.main            # loop for evigt (produktion)
    python -m app.main --once     # én kørsel og exit (test)
    python -m app.main --check    # verificér DB-adgang, behandl intet

GDPR-bemærkning: der logges aldrig CPR-numre — kun bestillingens id.
"""

import argparse
import logging
import os
import sys
import time

from . import db
from .config import Settings, load_settings
from .mailer import Mailer, create_mailer
from .pdf import render_mail_body, render_pdf

log = logging.getLogger("skolehistorik")


class CprNotFound(Exception):
    pass


class QuietThirdParty(logging.Filter):
    """Dropper DEBUG/INFO fra støjende biblioteker, men beholder advarsler.

    WeasyPrint subsetter fonte via fontTools, som logger hvert glyph-opslag —
    flere hundrede linjer pr. PDF. At sætte niveauet på deres loggere rækker
    ikke: fontTools sætter selv niveauet undervejs og overskriver vores. Et
    filter på handleren tjekkes derimod ved hver udskrivning.

    Advarsler og fejl slipper igennem, så en manglende font eller ugyldig CSS
    stadig er synlig.
    """

    NOISY = ("fontTools", "weasyprint", "PIL", "urllib3")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(self.NOISY)


def setup_logging() -> None:
    """Vores egne logs på LOG_LEVEL (standard INFO), tredjepart dæmpet."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(QuietThirdParty())


def process_request(request: db.Request, skolekube, mailer: Mailer,
                    settings: Settings) -> None:
    student_id = db.lookup_student_id(
        skolekube, settings.sensitive_table, request.child_cpr
    )
    if student_id is None:
        raise CprNotFound(f"CPR ikke fundet i {settings.sensitive_table}")

    enrollments = db.fetch_enrollments(
        skolekube, settings.enrollment_table, student_id
    )
    pdf = render_pdf(request, enrollments)

    subject = settings.mail_subject.format(request_id=request.id)
    body = render_mail_body(request, enrollments)
    mailer.send(
        to=request.request_user_email,
        subject=subject,
        body=body,
        pdf=pdf,
        filename=f"skolehistorik_bestilling_{request.id}.pdf",
    )


def run_once(settings: Settings, mailer: Mailer) -> None:
    with db.connect(settings.xflow_conn) as xflow, \
         db.connect(settings.skolekube_conn) as skolekube:
        pending = db.fetch_pending(xflow, settings.request_table,
                                   settings.max_attempts)
        if not pending:
            log.debug("Ingen nye bestillinger")
            return

        log.info("Behandler %d bestilling(er)", len(pending))
        for request in pending:
            try:
                process_request(request, skolekube, mailer, settings)
            except Exception as exc:
                # Én fejlende bestilling må ikke blokere resten af køen.
                log.error("Bestilling %d fejlede: %s", request.id, exc)
                db.mark_failed(xflow, settings.request_table, request.id, str(exc))
            else:
                db.mark_sent(xflow, settings.request_table, request.id)
                log.info("Bestilling %d sendt til bestilleren", request.id)


def check(settings: Settings) -> int:
    """Verificér adgang til begge databaser og de forventede kolonner."""
    ok = True

    try:
        with db.connect(settings.xflow_conn) as xflow:
            pending = db.fetch_pending(xflow, settings.request_table,
                                       settings.max_attempts)
            log.info("XFlow OK — %s, %d ubehandlet bestilling(er) i køen",
                     settings.request_table, len(pending))
            for request in pending:
                log.info("  bestilling %d, bestilt %s, %d tidligere forsøg",
                         request.id, request.timestamp, request.attempts)
    except Exception as exc:
        log.error("XFlow FEJLEDE (%s): %s", settings.request_table, exc)
        log.error("  Tjek DB_SERVER/DB_USERNAME/DB_PASSWORD og XFLOW_DB/XFLOW_TABLE, "
                  "og at kolonnerne status, processed_at, error_message og "
                  "attempts findes på tabellen.")
        ok = False

    try:
        with db.connect(settings.skolekube_conn) as skolekube:
            db.assert_columns(skolekube, settings.sensitive_table,
                              db.SENSITIVE_COLUMNS)
            db.assert_columns(skolekube, settings.enrollment_table,
                              db.ENROLLMENT_COLUMNS)
            log.info("Skolekube OK — alle kolonner findes i %s og %s",
                     settings.sensitive_table, settings.enrollment_table)
    except Exception as exc:
        log.error("Skolekube FEJLEDE: %s", exc)
        log.error("  Tjek SKOLEKUBE_DB samt at tabelnavnene er kvalificeret "
                  "med skema (fx dw.tabel) — et ukvalificeret navn slås kun op "
                  "i brugerens standardskema.")
        ok = False

    log.info("Tjek %s", "bestået" if ok else "FEJLET")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="kør én runde og afslut")
    parser.add_argument("--check", action="store_true",
                        help="verificér DB-adgang uden at behandle bestillinger")
    args = parser.parse_args()

    setup_logging()
    # Foer load_settings: fejler konfigurationen, er versionen netop det man
    # har brug for at kende. Lokale builds uden --build-arg viser "ukendt".
    log.info("Version %s (%s)", os.environ.get("APP_VERSION", "ukendt"),
             os.environ.get("GIT_SHA", "ukendt")[:7])
    settings = load_settings()

    if args.check:
        sys.exit(check(settings))

    mailer = create_mailer(settings)

    if args.once:
        log.info("Enkelt kørsel (mailer: %s)", settings.mailer)
        run_once(settings, mailer)
        return

    log.info("Starter worker (interval: %ds, mailer: %s)",
             settings.poll_interval_seconds, settings.mailer)
    while True:
        try:
            run_once(settings, mailer)
        except Exception:
            # Databasen kan være utilgængelig — log og prøv igen næste runde.
            log.exception("Kørslen fejlede; prøver igen om %ds",
                          settings.poll_interval_seconds)
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
