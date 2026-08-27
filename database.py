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
                    sent_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                    verified INTEGER NOT NULL DEFAULT 0
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS password_reset_codes (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    sent_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                    verified INTEGER NOT NULL DEFAULT 0
                )
                """
            )

            cursor.execute(
                """
                ALTER TABLE verification_codes
                ADD COLUMN IF NOT EXISTS sent_at DOUBLE PRECISION NOT NULL DEFAULT 0
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS login_tokens (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE login_tokens
                ADD COLUMN IF NOT EXISTS expires_at DOUBLE PRECISION
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    locked_until DOUBLE PRECISION NOT NULL DEFAULT 0
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


def delete_verification_code(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM verification_codes
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()


def save_verification_code(
    email,
    code_hash,
    expires_at,
    sent_at
):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO verification_codes (
                    email,
                    code_hash,
                    expires_at,
                    sent_at,
                    verified
                )
                VALUES (%s, %s, %s, %s, 0)

                ON CONFLICT(email)
                DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at,
                    sent_at = EXCLUDED.sent_at,
                    verified = 0
                """,
                (
                    email.lower().strip(),
                    code_hash,
                    expires_at,
                    sent_at
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


def save_login_token(
    email,
    token,
    created_at
):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO login_tokens (
                    email,
                    token,
                    created_at
                )
                VALUES (%s, %s, %s)
                """,
                (
                    email.lower().strip(),
                    token,
                    created_at
                )
            )

        connection.commit()


def get_login_token(token):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            return cursor.fetchone()


def delete_login_token(token):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

        connection.commit()


def delete_login_tokens_by_email(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM login_tokens
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()


def get_login_attempt(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM login_attempts
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

            return cursor.fetchone()


def register_login_failure(email):
    email = email.lower().strip()

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO login_attempts (
                    email,
                    failed_count,
                    locked_until
                )
                VALUES (%s, 1, 0)

                ON CONFLICT(email)
                DO UPDATE SET
                    failed_count = login_attempts.failed_count + 1
                """,
                (
                    email,
                )
            )

        connection.commit()


def lock_login(email, locked_until):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO login_attempts (
                    email,
                    failed_count,
                    locked_until
                )
                VALUES (%s, 5, %s)

                ON CONFLICT(email)
                DO UPDATE SET
                    failed_count = 5,
                    locked_until = EXCLUDED.locked_until
                """,
                (
                    email.lower().strip(),
                    locked_until
                )
            )

        connection.commit()


def reset_login_attempts(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM login_attempts
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()

def get_password_reset_code(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM password_reset_codes
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

            return cursor.fetchone()


def save_password_reset_code(
    email,
    code_hash,
    expires_at,
    sent_at
):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO password_reset_codes (
                    email,
                    code_hash,
                    expires_at,
                    sent_at,
                    verified
                )
                VALUES (%s, %s, %s, %s, 0)

                ON CONFLICT(email)
                DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at,
                    sent_at = EXCLUDED.sent_at,
                    verified = 0
                """,
                (
                    email.lower().strip(),
                    code_hash,
                    expires_at,
                    sent_at
                )
            )

        connection.commit()


def set_password_reset_verified(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE password_reset_codes
                SET verified = 1
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()


def delete_password_reset_code(email):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM password_reset_codes
                WHERE email = %s
                """,
                (
                    email.lower().strip(),
                )
            )

        connection.commit()


def update_user_password(
    email,
    password_hash
):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE email = %s
                """,
                (
                    password_hash,
                    email.lower().strip()
                )
            )

        connection.commit()
