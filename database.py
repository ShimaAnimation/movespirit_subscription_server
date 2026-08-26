import os

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


def get_connection():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def initialize_database():
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_codes (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0
                )
                """
            )

        connection.commit()


def get_user_by_email(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

            return cursor.fetchone()


def create_user(
    email,
    password_hash
):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    password_hash
                )
                VALUES (%s, %s)
                """,
                (
                    email.lower().strip(),
                    password_hash
                )
            )

        connection.commit()


def save_verification_code(
    email,
    code_hash,
    expires_at
):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO verification_codes (
                    email,
                    code_hash,
                    expires_at,
                    verified
                )
                VALUES (%s, %s, %s, 0)

                ON CONFLICT(email)
                DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at,
                    verified = 0
                """,
                (
                    email.lower().strip(),
                    code_hash,
                    expires_at
                )
            )

        connection.commit()


def get_verification_code(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM verification_codes
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

            return cursor.fetchone()


def set_email_verified(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE verification_codes
                SET verified = 1
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()


def delete_user(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM users
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()