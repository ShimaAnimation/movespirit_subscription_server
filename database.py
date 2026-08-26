import sqlite3

from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "users.db"


def get_connection():
    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at REAL NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    connection.commit()
    connection.close()


def get_user_by_email(email):
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (
            email.lower().strip(),
        )
    )

    user = cursor.fetchone()

    connection.close()

    return user


def create_user(
    email,
    password_hash
):
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO users (
            email,
            password_hash
        )
        VALUES (?, ?)
        """,
        (
            email.lower().strip(),
            password_hash
        )
    )

    connection.commit()
    connection.close()


def save_verification_code(
    email,
    code_hash,
    expires_at
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO verification_codes (
            email,
            code_hash,
            expires_at,
            verified
        )
        VALUES (?, ?, ?, 0)

        ON CONFLICT(email)
        DO UPDATE SET
            code_hash = excluded.code_hash,
            expires_at = excluded.expires_at,
            verified = 0
        """,
        (
            email.lower().strip(),
            code_hash,
            expires_at
        )
    )

    connection.commit()
    connection.close()


def get_verification_code(email):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM verification_codes
        WHERE email = ?
        """,
        (
            email.lower().strip(),
        )
    )

    result = cursor.fetchone()

    connection.close()

    return result


def set_email_verified(email):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE verification_codes
        SET verified = 1
        WHERE email = ?
        """,
        (
            email.lower().strip(),
        )
    )

    connection.commit()
    connection.close()


def delete_user(email):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM users
        WHERE email = ?
        """,
        (
            email.lower().strip(),
        )
    )

    connection.commit()
    connection.close()
