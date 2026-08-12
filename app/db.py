"""Databaseadgang: request-loggen i XFlow og opslagene i Skolekube.

Tabelnavne kommer fra konfigurationen og interpoleres ind i sætningerne —
de er valideret som identifikatorer i config.py. Alle *værdier* sendes som
rigtige parametre.
"""

from dataclasses import dataclass
from datetime import datetime

import pyodbc


@dataclass
class Request:
    id: int
    child_cpr: str
    reason: str | None
    timestamp: datetime
    request_user: str | None
    request_user_email: str
    attempts: int


@dataclass
class Enrollment:
    school_code: str | None
    school_name: str | None
    school_type_code: str | None
    class_name: str | None
    student_grade_level: str | None
    from_date_id: int | None
    to_date_id: int | None


# Kolonnelisterne står ét sted, så --check validerer præcis de kolonner, de
# rigtige forespørgsler bruger. Ellers kan et forkert kolonnenavn slippe
# gennem tjekket og først fejle midt i en behandling.
REQUEST_COLUMNS = """id, child_cpr, reason, timestamp, request_user,
                     request_user_email, attempts"""
SENSITIVE_COLUMNS = "student_id, cpr_nr"
ENROLLMENT_COLUMNS = """school_code, school_name, school_type_code, class_name,
                        student_grade_level, from_date_id, to_date_id"""


def connect(conn_str: str) -> pyodbc.Connection:
    return pyodbc.connect(conn_str, timeout=15)


def assert_columns(cnx: pyodbc.Connection, table: str, columns: str) -> None:
    """Bekræft at tabel og kolonner findes, uden at hente data.

    WHERE 1 = 0 får SQL Server til at validere hele SELECT-listen og fejle
    på et ukendt navn, men returnere nul rækker — så intet personfølsomt
    passerer gennem et tjek.
    """
    cnx.execute(f"SELECT {columns} FROM {table} WHERE 1 = 0").fetchall()


# --- XFlow: request-log ------------------------------------------------------

def fetch_pending(cnx: pyodbc.Connection, table: str,
                  max_attempts: int) -> list[Request]:
    """Nye rækker (status IS NULL) samt fejlede med retries tilbage."""
    rows = cnx.execute(
        f"""
        SELECT {REQUEST_COLUMNS}
        FROM {table}
        WHERE status IS NULL
           OR (status = 'failed' AND attempts < ?)
        ORDER BY id
        """,
        max_attempts,
    ).fetchall()
    return [Request(*row) for row in rows]


def mark_sent(cnx: pyodbc.Connection, table: str, request_id: int) -> None:
    cnx.execute(
        f"""
        UPDATE {table}
        SET status = 'sent', processed_at = GETDATE(), error_message = NULL,
            attempts = attempts + 1
        WHERE id = ?
        """,
        request_id,
    )
    cnx.commit()


def mark_failed(cnx: pyodbc.Connection, table: str, request_id: int,
                error: str) -> None:
    cnx.execute(
        f"""
        UPDATE {table}
        SET status = 'failed', processed_at = GETDATE(), error_message = ?,
            attempts = attempts + 1
        WHERE id = ?
        """,
        error[:4000],
        request_id,
    )
    cnx.commit()


# --- Skolekube: opslag -------------------------------------------------------

def lookup_student_id(cnx: pyodbc.Connection, table: str, cpr: str) -> int | None:
    rows = cnx.execute(
        f"SELECT DISTINCT student_id FROM {table} WHERE cpr_nr = ?", cpr
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(
            f"CPR matcher {len(rows)} forskellige student_id'er i {table}"
        )
    return rows[0][0]


def fetch_enrollments(cnx: pyodbc.Connection, table: str,
                      student_id: int) -> list[Enrollment]:
    rows = cnx.execute(
        f"""
        SELECT {ENROLLMENT_COLUMNS}
        FROM {table}
        WHERE student_id = ?
        ORDER BY from_date_id
        """,
        student_id,
    ).fetchall()
    return [Enrollment(*row) for row in rows]
