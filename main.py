import os
import hashlib
import secrets
import time
import uuid

import stripe
import resend

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pwdlib import PasswordHash
from datetime import datetime, timezone, timedelta

from database import (
    initialize_database,
    get_connection,
    get_user_by_email,
    create_user,
    save_verification_code,
    get_verification_code,
    set_email_verified,
    save_login_token,
    get_login_token,
    delete_login_token,
    delete_login_tokens_by_email,
    get_login_attempt,
    register_login_failure,
    lock_login,
    reset_login_attempts,
    delete_verification_code,
    get_password_reset_code,
    save_password_reset_code,
    set_password_reset_verified,
    delete_password_reset_code,
    update_user_password
)


load_dotenv()

app = FastAPI()

stripe.api_key = os.getenv(
    "STRIPE_SECRET_KEY"
)

OFFICE_PRICE_ID = os.getenv(
    "STRIPE_OFFICE_PRICE_ID"
)

OFFICE_ADMIN_SECRET = os.getenv(
    "OFFICE_ADMIN_SECRET"
)

UNLIMITED_TEST_COMPANY_ID = (
    "a912da44-58e6-4222-bb2e-ef42f68cfbec"
)

UNLIMITED_TEST_SEAT_LIMIT = 999999

resend.api_key = os.getenv(
    "RESEND_API_KEY"
)


CUSTOMER_PORTAL_RETURN_URL = os.getenv(
    "CUSTOMER_PORTAL_RETURN_URL",
    "https://x.com/ShimaAnimation"
)

password_hash = PasswordHash.recommended()

initialize_database()


@app.get("/")
def root():
    return {
        "status": "MoveSpirit subscription server is running"
    }


@app.get("/stripe-check")
def stripe_check():
    account = stripe.Account.retrieve()

    return {
        "stripe_connected": True,
        "account_id": account.id
    }


class OfficeAdminUsersRequest(
    BaseModel
):
    admin_secret: str
    admin_email: str


@app.post(
    "/office/admin/users"
)
def office_admin_users(
    request: OfficeAdminUsersRequest
):

    # =========================================
    # 開発者専用認証
    # =========================================

    if (
        not OFFICE_ADMIN_SECRET
        or request.admin_secret
        != OFFICE_ADMIN_SECRET
    ):
        return {
            "success": False,
            "reason": "unauthorized"
        }

    admin_email = (
        request.admin_email
        .strip()
        .lower()
    )

    if not admin_email:
        return {
            "success": False,
            "reason": "admin_email_required"
        }

    # =========================================
    # 管理者確認
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    company_id,
                    email,
                    is_admin
                FROM office_users
                WHERE email = %s
                """,
                (
                    admin_email,
                )
            )

            admin_user = (
                cursor.fetchone()
            )

    if not admin_user:
        return {
            "success": False,
            "reason": "admin_not_found"
        }

    if not bool(
        admin_user[
            "is_admin"
        ]
    ):
        return {
            "success": False,
            "reason": "not_admin"
        }

    company_id = (
        admin_user[
            "company_id"
        ]
    )

    # =========================================
    # 会社情報取得
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    company_name
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = (
                cursor.fetchone()
            )

    if not company:
        return {
            "success": False,
            "reason": "company_not_found"
        }

    # =========================================
    # Officeユーザー一覧取得
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    email,
                    is_admin,
                    is_active,
                    created_at,
                    last_login_at,
                    last_seen_at
                FROM office_users
                WHERE company_id = %s
                ORDER BY
                    is_admin DESC,
                    email ASC
                """,
                (
                    company_id,
                )
            )

            users = (
                cursor.fetchall()
            )

    # =========================================
    # 日本時間
    # =========================================

    japan_timezone = (
        timezone(
            timedelta(
                hours=9
            )
        )
    )

    # =========================================
    # Unix時間 → 日本時間
    # =========================================

    def timestamp_to_jst(
        timestamp
    ):

        if timestamp is None:
            return None

        return (
            datetime
            .fromtimestamp(
                timestamp,
                tz=japan_timezone
            )
            .strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

    # =========================================
    # レスポンス用ユーザー一覧
    # =========================================

    user_list = []

    for user in users:

        user_list.append(
            {
                "email":
                    user[
                        "email"
                    ],

                "is_admin":
                    bool(
                        user[
                            "is_admin"
                        ]
                    ),

                "is_active":
                    bool(
                        user[
                            "is_active"
                        ]
                    ),

                "created_at":
                    timestamp_to_jst(
                        user[
                            "created_at"
                        ]
                    ),

                "last_login_at":
                    timestamp_to_jst(
                        user[
                            "last_login_at"
                        ]
                    ),

                "last_seen_at":
                    timestamp_to_jst(
                        user[
                            "last_seen_at"
                        ]
                    )
            }
        )

    # =========================================
    # 成功
    # =========================================

    return {
        "success": True,
        "company_id": company_id,
        "company_name":
            company[
                "company_name"
            ],
        "admin_email":
            admin_email,
        "user_count":
            len(
                user_list
            ),
        "users":
            user_list
    }


class OfficeAdminAllUsersRequest(BaseModel):
    admin_secret: str


@app.post("/office/admin/all-users")
def office_admin_all_users(request: OfficeAdminAllUsersRequest):

    # =========================================
    # 開発者専用認証
    # =========================================

    if not OFFICE_ADMIN_SECRET or request.admin_secret != OFFICE_ADMIN_SECRET:
        return {
            "success": False,
            "reason": "unauthorized"
        }

    # =========================================
    # 日本時間
    # =========================================

    japan_timezone = timezone(timedelta(hours=9))
    today_jst = datetime.now(japan_timezone).date()

    def timestamp_to_jst(timestamp):
        if timestamp is None:
            return None

        return datetime.fromtimestamp(
            timestamp,
            tz=japan_timezone
        ).strftime("%Y-%m-%d %H:%M:%S")

    # =========================================
    # 全企業取得
    # =========================================

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    company_id,
                    company_name,
                    admin_email,
                    seat_limit,
                    stripe_customer_id,
                    stripe_subscription_id,
                    created_at,
                    is_unlimited_trial,
                    trial_expires_at
                FROM office_companies
                ORDER BY company_name ASC
                """
            )

            companies = cursor.fetchall()

    # =========================================
    # 企業ごとのユーザー取得
    # =========================================

    company_list = []
    total_user_count = 0
    total_active_user_count = 0

    for company in companies:
        company_id = company["company_id"]

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        u.email,
                        u.is_admin,
                        u.is_active,
                        u.created_at,
                        u.last_login_at,
                        u.last_seen_at,

                        COALESCE(
                            a.server_connection_count,
                            0
                        ) AS today_server_connection_count,

                        COALESCE(
                            a.login_count,
                            0
                        ) AS today_login_count,

                        COALESCE(
                            (
                                SELECT COUNT(*)
                                FROM office_user_daily_activity AS monthly_activity
                                WHERE LOWER(monthly_activity.email) = LOWER(u.email)
                                AND monthly_activity.login_count > 0
                                AND DATE_TRUNC(
                                    'month',
                                    monthly_activity.activity_date
                                ) = DATE_TRUNC(
                                    'month',
                                    %s::date
                                )
                            ),
                            0
                        ) AS this_month_login_days

                    FROM office_users AS u

                    LEFT JOIN office_user_daily_activity AS a
                        ON LOWER(a.email) = LOWER(u.email)
                        AND a.activity_date = %s

                    WHERE u.company_id = %s

                    ORDER BY
                        u.is_admin DESC,
                        u.email ASC
                    """,
                    (
                        today_jst,
                        today_jst,
                        company_id
                    )
                )

                users = cursor.fetchall()

        user_list = []
        active_user_count = 0

        for user in users:
            is_active = bool(user["is_active"])

            if is_active:
                active_user_count += 1

            user_list.append({
                "email": user["email"],
                "is_admin": bool(user["is_admin"]),
                "is_active": is_active,
                "created_at": timestamp_to_jst(user["created_at"]),
                "last_login_at": timestamp_to_jst(user["last_login_at"]),
                "last_seen_at": timestamp_to_jst(user["last_seen_at"]),
                "today_login_count": user["today_login_count"],
                "this_month_login_days": user["this_month_login_days"],
                "today_server_connection_count": user["today_server_connection_count"]
            })

        total_user_count += len(user_list)
        total_active_user_count += active_user_count

        company_list.append({
            "company_id": company["company_id"],
            "company_name": company["company_name"],
            "admin_email": company["admin_email"],
            "seat_limit": company["seat_limit"],
            "active_user_count": active_user_count,
            "registered_user_count": len(user_list),
            "is_unlimited_trial": bool(company["is_unlimited_trial"]),
            "trial_expires_at": timestamp_to_jst(company["trial_expires_at"]),
            "stripe_customer_id": company["stripe_customer_id"],
            "stripe_subscription_id": company["stripe_subscription_id"],
            "created_at": timestamp_to_jst(company["created_at"]),
            "users": user_list
        })

    # =========================================
    # 成功
    # =========================================

    return {
        "success": True,
        "company_count": len(company_list),
        "total_user_count": total_user_count,
        "total_active_user_count": total_active_user_count,
        "companies": company_list
    }


class OfficeRegisterRequest(BaseModel):
    company_name: str
    email: str
    password: str


@app.post("/office/register")
def office_register(
    request: OfficeRegisterRequest
):

    company_name = request.company_name.strip()
    email = request.email.strip().lower()
    password = request.password

    if not company_name:
        return {
            "success": False,
            "reason": "company_name_required"
        }

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if len(password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # 既存Officeユーザー確認
            # -------------------------

            cursor.execute(
                """
                SELECT id
                FROM office_users
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            if cursor.fetchone():
                return {
                    "success": False,
                    "reason": "already_registered"
                }

            # -------------------------
            # Stripe Office契約確認
            # -------------------------

            stripe_result = find_office_subscription(
                email
            )

            if not stripe_result["success"]:
                return {
                    "success": False,
                    "reason": stripe_result["reason"]
                }

            stripe_customer_id = stripe_result[
                "customer_id"
            ]

            stripe_subscription_id = stripe_result[
                "subscription_id"
            ]

            seat_limit = stripe_result[
                "quantity"
            ]

            # -------------------------
            # 会社ID作成
            # -------------------------

            company_id = str(
                uuid.uuid4()
            )

            # -------------------------
            # パスワードをハッシュ化
            # -------------------------

            hashed_password = password_hash.hash(
                password
            )

            created_at = time.time()

            # -------------------------
            # 会社を登録
            # -------------------------

            cursor.execute(
                """
                INSERT INTO office_companies (
                    company_id,
                    company_name,
                    admin_email,
                    stripe_customer_id,
                    stripe_subscription_id,
                    seat_limit,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    company_id,
                    company_name,
                    email,
                    stripe_customer_id,
                    stripe_subscription_id,
                    seat_limit,
                    created_at
                )
            )

            # -------------------------
            # 管理者ユーザーを登録
            # -------------------------

            cursor.execute(
                """
                INSERT INTO office_users (
                    company_id,
                    email,
                    password_hash,
                    is_admin,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    company_id,
                    email,
                    hashed_password,
                    1,
                    created_at
                )
            )

        connection.commit()

    return {
        "success": True,
        "company_id": company_id,
        "seat_limit": seat_limit
    }


class OfficeTrialRegisterRequest(BaseModel):
    admin_secret: str
    company_name: str
    email: str
    password: str


@app.post("/office/register-trial")
def office_register_trial(
    request: OfficeTrialRegisterRequest
):

    # -------------------------
    # 開発者確認
    # -------------------------

    if (
        not OFFICE_ADMIN_SECRET
        or request.admin_secret
        != OFFICE_ADMIN_SECRET
    ):
        return {
            "success": False,
            "reason": "unauthorized"
        }

    company_name = (
        request.company_name
        .strip()
    )

    email = (
        request.email
        .strip()
        .lower()
    )

    password = request.password

    if not company_name:
        return {
            "success": False,
            "reason": "company_name_required"
        }

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if len(password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # 既存Officeユーザー確認
            # -------------------------

            cursor.execute(
                """
                SELECT id
                FROM office_users
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            if cursor.fetchone():
                return {
                    "success": False,
                    "reason": "already_registered"
                }

            company_id = str(
                uuid.uuid4()
            )

            hashed_password = (
                password_hash.hash(
                    password
                )
            )

            created_at = time.time()

            # -------------------------
            # 90日後
            # -------------------------

            trial_expires_at = (
                created_at
                + (
                    90
                    * 24
                    * 60
                    * 60
                )
            )

            # -------------------------
            # 会社登録
            # -------------------------

            cursor.execute(
                """
                INSERT INTO office_companies (
                    company_id,
                    company_name,
                    admin_email,
                    seat_limit,
                    created_at,
                    is_unlimited_trial,
                    trial_expires_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    company_id,
                    company_name,
                    email,
                    999999,
                    created_at,
                    1,
                    trial_expires_at
                )
            )

            # -------------------------
            # 管理者登録
            # -------------------------

            cursor.execute(
                """
                INSERT INTO office_users (
                    company_id,
                    email,
                    password_hash,
                    is_admin,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    company_id,
                    email,
                    hashed_password,
                    1,
                    created_at
                )
            )

        connection.commit()

    return {
        "success": True,
        "company_id": company_id,
        "seat_limit": 999999,
        "trial_days": 90,
        "trial_expires_at": trial_expires_at
    }


class OfficeChangeTrialExpirationRequest(
    BaseModel
):
    admin_secret: str
    company_id: str
    trial_days: int


@app.post(
    "/office/change-trial-expiration"
)
def office_change_trial_expiration(
    request: OfficeChangeTrialExpirationRequest
):

    # =========================================
    # 開発者確認
    # =========================================

    if (
        not OFFICE_ADMIN_SECRET
        or request.admin_secret
        != OFFICE_ADMIN_SECRET
    ):
        return {
            "success": False,
            "reason": "unauthorized"
        }

    company_id = (
        request.company_id
        .strip()
    )

    trial_days = (
        request.trial_days
    )

    if not company_id:
        return {
            "success": False,
            "reason": "company_id_required"
        }

    if trial_days <= 0:
        return {
            "success": False,
            "reason": "invalid_trial_days"
        }

    # =========================================
    # 新しい有効期限
    # =========================================

    now = (
        time.time()
    )

    trial_expires_at = (
        now
        + (
            trial_days
            * 24
            * 60
            * 60
        )
    )

    # =========================================
    # 会社確認 + 更新
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    company_id,
                    company_name,
                    admin_email,
                    is_unlimited_trial
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = (
                cursor.fetchone()
            )

            if not company:
                return {
                    "success": False,
                    "reason": "company_not_found"
                }

            if not bool(
                company[
                    "is_unlimited_trial"
                ]
            ):
                return {
                    "success": False,
                    "reason": "not_trial_company"
                }

            cursor.execute(
                """
                UPDATE office_companies
                SET trial_expires_at = %s
                WHERE company_id = %s
                """,
                (
                    trial_expires_at,
                    company_id
                )
            )

        connection.commit()

    # =========================================
    # 成功
    # =========================================

    return {
        "success": True,
        "company_id": company_id,
        "company_name": company[
            "company_name"
        ],
        "admin_email": company[
            "admin_email"
        ],
        "trial_days": trial_days,
        "trial_expires_at":
            trial_expires_at
    }


class OfficeConvertTrialToPaidRequest(
    BaseModel
):
    admin_secret: str
    company_id: str
    stripe_email: str


@app.post(
    "/office/convert-trial-to-paid"
)
def office_convert_trial_to_paid(
    request: OfficeConvertTrialToPaidRequest
):

    # =========================================
    # 開発者確認
    # =========================================

    if (
        not OFFICE_ADMIN_SECRET
        or request.admin_secret
        != OFFICE_ADMIN_SECRET
    ):
        return {
            "success": False,
            "reason": "unauthorized"
        }

    # =========================================
    # 入力整理
    # =========================================

    company_id = (
        request.company_id
        .strip()
    )

    stripe_email = (
        request.stripe_email
        .strip()
        .lower()
    )

    if not company_id:
        return {
            "success": False,
            "reason": "company_id_required"
        }

    if not stripe_email:
        return {
            "success": False,
            "reason": "stripe_email_required"
        }

    # =========================================
    # 会社確認
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    company_id,
                    company_name,
                    admin_email,
                    is_unlimited_trial,
                    trial_expires_at
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = (
                cursor.fetchone()
            )

            if not company:

                return {
                    "success": False,
                    "reason": "company_not_found"
                }

    # =========================================
    # Stripe Office契約検索
    # =========================================

    stripe_result = (
        find_office_subscription(
            stripe_email
        )
    )

    if not stripe_result.get(
        "success"
    ):

        return {
            "success": False,
            "reason": stripe_result.get(
                "reason",
                "office_subscription_not_active"
            )
        }

    stripe_customer_id = (
        stripe_result[
            "customer_id"
        ]
    )

    stripe_subscription_id = (
        stripe_result[
            "subscription_id"
        ]
    )

    quantity = (
        stripe_result.get(
            "quantity",
            1
        )
    )

    if not quantity:
        quantity = 1

    # =========================================
    # 無料法人 → 正式契約へ変更
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE office_companies
                SET
                    stripe_customer_id = %s,
                    stripe_subscription_id = %s,
                    seat_limit = %s,
                    is_unlimited_trial = %s
                WHERE company_id = %s
                """,
                (
                    stripe_customer_id,
                    stripe_subscription_id,
                    quantity,
                    0,
                    company_id
                )
            )

        connection.commit()

    # =========================================
    # 成功
    # =========================================

    return {
        "success": True,
        "company_id": company_id,
        "company_name": company[
            "company_name"
        ],
        "admin_email": company[
            "admin_email"
        ],
        "stripe_email": stripe_email,
        "stripe_customer_id":
            stripe_customer_id,
        "stripe_subscription_id":
            stripe_subscription_id,
        "seat_limit": quantity,
        "trial": False
    }


class OfficeLoginRequest(BaseModel):
    email: str
    password: str


@app.post("/office/login")
def office_login(
    request: OfficeLoginRequest
):

    email = (
        request.email
        .strip()
        .lower()
    )

    password = (
        request.password
    )

    # =========================================
    # 入力確認
    # =========================================

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if not password:
        return {
            "success": False,
            "reason": "password_required"
        }

    # =========================================
    # Officeユーザー取得
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    company_id,
                    email,
                    password_hash,
                    is_admin,
                    is_active
                FROM office_users
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            user = (
                cursor.fetchone()
            )

            if not user:
                return {
                    "success": False,
                    "reason": "user_not_found"
                }

            # =========================================
            # ユーザー情報
            # =========================================

            company_id = (
                user[
                    "company_id"
                ]
            )

            user_email = (
                user[
                    "email"
                ]
            )

            hashed_password = (
                user[
                    "password_hash"
                ]
            )

            is_admin = (
                user[
                    "is_admin"
                ]
            )

            is_active = bool(
                user[
                    "is_active"
                ]
            )

            # =========================================
            # 有効ユーザー確認
            # =========================================

            if not is_active:
                return {
                    "success": False,
                    "reason": "user_inactive"
                }

            # =========================================
            # パスワード確認
            # =========================================

            password_ok = (
                password_hash.verify(
                    password,
                    hashed_password
                )
            )

            if not password_ok:
                return {
                    "success": False,
                    "reason": "invalid_password"
                }

            # =========================================
            # 会社情報確認
            # =========================================

            cursor.execute(
                """
                SELECT
                    company_name,
                    admin_email,
                    seat_limit,
                    stripe_customer_id,
                    stripe_subscription_id,
                    is_unlimited_trial,
                    trial_expires_at
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = (
                cursor.fetchone()
            )

            if not company:
                return {
                    "success": False,
                    "reason": "company_not_found"
                }

            company_name = (
                company[
                    "company_name"
                ]
            )

            is_unlimited_trial = bool(
                company[
                    "is_unlimited_trial"
                ]
            )

            # =========================================
            # Office利用権確認
            # =========================================

            sync_result = (
                sync_office_seat_limit(
                    company_id
                )
            )

            if not sync_result.get(
                "success"
            ):
                return {
                    "success": False,
                    "reason": sync_result.get(
                        "reason",
                        "subscription_not_active"
                    )
                }

            seat_limit = (
                sync_result[
                    "seat_limit"
                ]
            )

            # =========================================
            # 有効ユーザー数確認
            # =========================================

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS count
                FROM office_users
                WHERE company_id = %s
                AND is_active = 1
                """,
                (
                    company_id,
                )
            )

            active_user_result = (
                cursor.fetchone()
            )

            active_user_count = (
                active_user_result[
                    "count"
                ]
            )

            # =========================================
            # 契約席数超過確認
            #
            # 管理者はユーザー整理のため
            # ログインを許可
            # =========================================

            if (
                not bool(
                    is_admin
                )
                and active_user_count
                > seat_limit
            ):
                return {
                    "success": False,
                    "reason": "over_seat_limit",
                    "seat_limit":
                        seat_limit,
                    "active_user_count":
                        active_user_count
                }

            # =========================================
            # 通常Office
            # 以前のtokenを削除
            #
            # 無料トライアル中は
            # 同一アカウントの複数PCログイン可
            # =========================================

            if not is_unlimited_trial:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE email = %s
                    """,
                    (
                        email,
                    )
                )

            # =========================================
            # 新しいtoken生成
            # =========================================

            token = (
                secrets.token_urlsafe(
                    48
                )
            )

            created_at = (
                time.time()
            )

            expires_at = (
                created_at
                + (
                    30
                    * 24
                    * 60
                    * 60
                )
            )

            # =========================================
            # ★ 最新ログイン時間を保存
            # =========================================

            cursor.execute(
                """
                UPDATE office_users
                SET
                    last_login_at = %s,
                    last_seen_at = %s
                WHERE company_id = %s
                AND email = %s
                """,
                (
                    created_at,
                    created_at,
                    company_id,
                    email
                )
            )

            # =========================================
            # 本日のログイン回数 +1
            # =========================================

            japan_timezone = timezone(timedelta(hours=9))
            today_jst = datetime.now(japan_timezone).date()

            cursor.execute(
                """
                INSERT INTO office_user_daily_activity (
                    email,
                    activity_date,
                    login_count
                )
                VALUES (%s, %s, 1)

                ON CONFLICT (email, activity_date)
                DO UPDATE SET
                    login_count =
                        office_user_daily_activity.login_count + 1
                """,
                (
                    email.strip().lower(),
                    today_jst
                )
            )

            # =========================================
            # ログイントークン保存
            # =========================================

            cursor.execute(
                """
                INSERT INTO office_login_tokens (
                    email,
                    token,
                    company_id,
                    created_at,
                    expires_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    email,
                    token,
                    company_id,
                    created_at,
                    expires_at
                )
            )

        # =========================================
        # DB反映
        # =========================================

        connection.commit()

    # =========================================
    # ログイン成功
    # =========================================

    return {
        "success": True,
        "token": token,
        "email": user_email,
        "company_id": company_id,
        "company_name": company_name,
        "is_admin": bool(
            is_admin
        ),
        "seat_limit": seat_limit,
        "is_unlimited_trial":
            is_unlimited_trial,
        "last_login_at":
            created_at
    }


class OfficeTokenCheckRequest(
    BaseModel
):
    token: str


@app.post(
    "/office/check-token"
)
def office_check_token(
    request: OfficeTokenCheckRequest
):

    token = (
        request.token
        .strip()
    )

    if not token:
        return {
            "success": False,
            "reason": "token_required"
        }

    # =========================================
    # token / ユーザー / 会社確認
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            # -------------------------
            # token取得
            # -------------------------

            cursor.execute(
                """
                SELECT
                    email,
                    company_id,
                    created_at,
                    expires_at
                FROM office_login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            token_data = (
                cursor.fetchone()
            )

            if not token_data:
                return {
                    "success": False,
                    "reason": "invalid_token"
                }

            # -------------------------
            # token有効期限確認
            # -------------------------

            if (
                time.time()
                > token_data[
                    "expires_at"
                ]
            ):

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "token_expired"
                }

            email = (
                token_data[
                    "email"
                ]
            )

            company_id = (
                token_data[
                    "company_id"
                ]
            )

            # -------------------------
            # Officeユーザー確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    email,
                    is_admin,
                    is_active
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    email,
                    company_id
                )
            )

            user = (
                cursor.fetchone()
            )

            if not user:
                return {
                    "success": False,
                    "reason": "user_not_found"
                }

            is_active = bool(
                user[
                    "is_active"
                ]
            )

            is_admin = bool(
                user[
                    "is_admin"
                ]
            )

            if not is_active:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "user_inactive"
                }

            # -------------------------
            # 会社確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    company_name
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = (
                cursor.fetchone()
            )

            if not company:
                return {
                    "success": False,
                    "reason": "company_not_found"
                }

            company_name = (
                company[
                    "company_name"
                ]
            )

    # =========================================
    # Stripe / Trial 利用権確認
    # =========================================

    sync_result = (
        sync_office_seat_limit(
            company_id
        )
    )

    if not sync_result.get(
        "success"
    ):

        # 契約が無効ならtoken削除
        with get_connection() as connection:

            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

            connection.commit()

        return {
            "success": False,
            "reason": sync_result.get(
                "reason",
                "subscription_not_active"
            )
        }

    seat_limit = (
        sync_result[
            "seat_limit"
        ]
    )

    # =========================================
    # 有効ユーザー数確認
    # =========================================

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS count
                FROM office_users
                WHERE company_id = %s
                AND is_active = 1
                """,
                (
                    company_id,
                )
            )

            active_user_count = (
                cursor.fetchone()[
                    "count"
                ]
            )

    # =========================================
    # 契約席数超過
    #
    # 管理者はユーザー整理のため利用可能
    # =========================================

    if (
        not is_admin
        and active_user_count
        > seat_limit
    ):
        return {
            "success": False,
            "reason": "over_seat_limit",
            "seat_limit":
                seat_limit,
            "active_user_count":
                active_user_count
        }

    # =========================================
    # ★ 最後にサーバーへ正常接続した時間
    # =========================================
    last_seen_at = time.time()

    japan_timezone = timezone(timedelta(hours=9))
    today_jst = datetime.now(japan_timezone).date()

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # 最終サーバー接続日時
            cursor.execute(
                """
                UPDATE office_users
                SET last_seen_at = %s
                WHERE company_id = %s
                AND email = %s
                """,
                (
                    last_seen_at,
                    company_id,
                    email
                )
            )

            # 本日のサーバー接続回数 +1
            cursor.execute(
                """
                INSERT INTO office_user_daily_activity (
                    email,
                    activity_date,
                    server_connection_count
                )
                VALUES (%s, %s, 1)

                ON CONFLICT (email, activity_date)
                DO UPDATE SET
                    server_connection_count =
                        office_user_daily_activity.server_connection_count + 1
                """,
                (
                    email.strip().lower(),
                    today_jst
                )
            )

        connection.commit()

    # =========================================
    # 成功
    # =========================================

    return {
        "success": True,
        "subscription_active": True,
        "email": email,
        "company_id": company_id,
        "company_name": company_name,
        "is_admin": is_admin,
        "seat_limit": seat_limit,
        "is_unlimited_trial": bool(
            sync_result.get(
                "trial",
                False
            )
        ),
        "trial_expires_at":
            sync_result.get(
                "trial_expires_at"
            ),
        "last_seen_at":
            last_seen_at
    }


class OfficeAddUserRequest(BaseModel):
    token: str
    email: str
    password: str

@app.post("/office/add-user")
def office_add_user(
    request: OfficeAddUserRequest
):

    token = request.token.strip()
    email = request.email.strip().lower()
    password = request.password

    if not token:
        return {
            "success": False,
            "reason": "token_required"
        }

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if len(password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # Office token確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    email,
                    company_id,
                    created_at,
                    expires_at
                FROM office_login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            token_data = cursor.fetchone()

            if not token_data:
                return {
                    "success": False,
                    "reason": "invalid_token"
                }

            # -------------------------
            # token有効期限確認
            # -------------------------

            if (
                time.time()
                > token_data["expires_at"]
            ):

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "token_expired"
                }

            admin_email = token_data["email"]
            company_id = token_data["company_id"]

            # -------------------------
            # 管理者か確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    id,
                    is_admin
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    admin_email,
                    company_id
                )
            )

            admin_user = cursor.fetchone()

            if not admin_user:
                return {
                    "success": False,
                    "reason": "admin_not_found"
                }

            if not admin_user["is_admin"]:
                return {
                    "success": False,
                    "reason": "admin_required"
                }

            # -------------------------
            # 会社情報取得
            # -------------------------
            cursor.execute(
                """
                SELECT id
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = cursor.fetchone()

            if not company:
                return {
                    "success": False,
                    "reason": "company_not_found"
                }

            sync_result = sync_office_seat_limit(
                company_id
            )

            if not sync_result["success"]:
                return {
                    "success": False,
                    "reason": sync_result["reason"]
                }

            seat_limit = sync_result["seat_limit"]

            # -------------------------
            # 既存ユーザー確認
            # -------------------------

            cursor.execute(
                """
                SELECT id
                FROM office_users
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            if cursor.fetchone():
                return {
                    "success": False,
                    "reason": "already_registered"
                }

            # -------------------------
            # 現在の登録人数
            # -------------------------

            cursor.execute(
                """
                SELECT COUNT(*) AS user_count
                FROM office_users
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            count_data = cursor.fetchone()

            current_user_count = count_data[
                "user_count"
            ]

            # -------------------------
            # 契約人数チェック
            # -------------------------

            if current_user_count >= seat_limit:
                return {
                    "success": False,
                    "reason": "seat_limit_reached",
                    "seat_limit": seat_limit,
                    "current_user_count": current_user_count
                }

            # -------------------------
            # パスワードをハッシュ化
            # -------------------------

            hashed_password = password_hash.hash(
                password
            )

            created_at = time.time()

            # -------------------------
            # 社員追加
            # -------------------------

            cursor.execute(
                """
                INSERT INTO office_users (
                    company_id,
                    email,
                    password_hash,
                    is_admin,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    company_id,
                    email,
                    hashed_password,
                    0,
                    created_at
                )
            )

        connection.commit()

    return {
        "success": True,
        "email": email,
        "company_id": company_id,
        "seat_limit": seat_limit,
        "current_user_count": (
            current_user_count + 1
        )
    }


class OfficeAddUsersRequest(BaseModel):
    token: str
    emails: list[str]
    password: str

@app.post("/office/add-users")
def office_add_users(
    request: OfficeAddUsersRequest
):

    token = request.token.strip()
    password = request.password

    if not token:
        return {
            "success": False,
            "reason": "token_required"
        }

    if len(password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    if not request.emails:
        return {
            "success": False,
            "reason": "emails_required"
        }

    if len(request.emails) > 500:
        return {
            "success": False,
            "reason": "too_many_users",
            "max_users": 500
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    email,
                    company_id,
                    expires_at
                FROM office_login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            token_data = cursor.fetchone()

            if not token_data:
                return {
                    "success": False,
                    "reason": "invalid_token"
                }

            if time.time() > token_data["expires_at"]:
                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "token_expired"
                }

            admin_email = token_data["email"]
            company_id = token_data["company_id"]

            cursor.execute(
                """
                SELECT
                    is_admin
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    admin_email,
                    company_id
                )
            )

            admin_user = cursor.fetchone()

            if not admin_user:
                return {
                    "success": False,
                    "reason": "admin_not_found"
                }

            if not admin_user["is_admin"]:
                return {
                    "success": False,
                    "reason": "admin_required"
                }

            sync_result = sync_office_seat_limit(
                company_id
            )

            if not sync_result["success"]:
                return {
                    "success": False,
                    "reason": sync_result["reason"]
                }

            seat_limit = sync_result["seat_limit"]

            cursor.execute(
                """
                SELECT COUNT(*) AS user_count
                FROM office_users
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            count_data = cursor.fetchone()

            current_user_count = (
                count_data["user_count"]
            )

            added_users = []
            skipped_users = []

            for target_email in request.emails:

                email = target_email.strip().lower()

                if not email:
                    skipped_users.append(
                        {
                            "email": email,
                            "reason": "email_required"
                        }
                    )
                    continue

                cursor.execute(
                    """
                    SELECT id
                    FROM office_users
                    WHERE email = %s
                    """,
                    (
                        email,
                    )
                )

                if cursor.fetchone():

                    skipped_users.append(
                        {
                            "email": email,
                            "reason": "already_registered"
                        }
                    )

                    continue

                if (
                    current_user_count
                    + len(added_users)
                    >= seat_limit
                ):
                    skipped_users.append(
                        {
                            "email": email,
                            "reason": "seat_limit_reached"
                        }
                    )

                    continue

                hashed_password = password_hash.hash(
                    password
                )

                created_at = time.time()

                cursor.execute(
                    """
                    INSERT INTO office_users (
                        company_id,
                        email,
                        password_hash,
                        is_admin,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        company_id,
                        email,
                        hashed_password,
                        0,
                        created_at
                    )
                )

                added_users.append(
                    email
                )

        connection.commit()

    return {
        "success": True,
        "company_id": company_id,
        "seat_limit": seat_limit,
        "added_count": len(added_users),
        "skipped_count": len(skipped_users),
        "added_users": added_users,
        "skipped_users": skipped_users
    }


class OfficeSetUserActiveRequest(BaseModel):
    token: str
    email: str
    is_active: bool


@app.post("/office/set-user-active")
def office_set_user_active(
    request: OfficeSetUserActiveRequest
):

    token = request.token.strip()
    target_email = (
        request.email
        .strip()
        .lower()
    )

    if not token:
        return {
            "success": False,
            "reason": "token_required"
        }

    if not target_email:
        return {
            "success": False,
            "reason": "email_required"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # 管理者token確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    email,
                    company_id,
                    expires_at
                FROM office_login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            token_data = cursor.fetchone()

            if not token_data:
                return {
                    "success": False,
                    "reason": "invalid_token"
                }

            if time.time() > token_data["expires_at"]:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "token_expired"
                }

            company_id = token_data[
                "company_id"
            ]

            admin_email = token_data[
                "email"
            ]

            # -------------------------
            # 管理者確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    is_admin,
                    is_active
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    admin_email,
                    company_id
                )
            )

            admin_user = cursor.fetchone()

            if not admin_user:
                return {
                    "success": False,
                    "reason": "user_not_found"
                }

            if not bool(
                admin_user["is_active"]
            ):
                return {
                    "success": False,
                    "reason": "user_inactive"
                }

            if not bool(
                admin_user["is_admin"]
            ):
                return {
                    "success": False,
                    "reason": "admin_required"
                }

            # -------------------------
            # 対象ユーザー確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    email,
                    is_admin,
                    is_active
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    target_email,
                    company_id
                )
            )

            target_user = cursor.fetchone()

            if not target_user:
                return {
                    "success": False,
                    "reason": "target_user_not_found"
                }

            # 管理者自身は無効化させない
            if (
                bool(target_user["is_admin"])
                and not request.is_active
            ):
                return {
                    "success": False,
                    "reason": "cannot_disable_admin"
                }

            # -------------------------
            # 有効化する場合は席数確認
            # -------------------------

            if request.is_active:

                sync_result = (
                    sync_office_seat_limit(
                        company_id
                    )
                )

                if not sync_result["success"]:
                    return {
                        "success": False,
                        "reason": sync_result[
                            "reason"
                        ]
                    }

                seat_limit = sync_result[
                    "seat_limit"
                ]

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM office_users
                    WHERE company_id = %s
                    AND is_active = 1
                    """,
                    (
                        company_id,
                    )
                )

                active_count = cursor.fetchone()[
                    "count"
                ]

                if (
                    not bool(
                        target_user[
                            "is_active"
                        ]
                    )
                    and active_count
                    >= seat_limit
                ):
                    return {
                        "success": False,
                        "reason": "seat_limit_reached",
                        "seat_limit": seat_limit,
                        "active_user_count":
                            active_count
                    }

            # -------------------------
            # 有効/無効切り替え
            # -------------------------

            cursor.execute(
                """
                UPDATE office_users
                SET is_active = %s
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    1
                    if request.is_active
                    else 0,
                    target_email,
                    company_id
                )
            )

            # 無効化した場合は
            # 既存tokenも全削除
            if not request.is_active:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE email = %s
                    AND company_id = %s
                    """,
                    (
                        target_email,
                        company_id
                    )
                )

        connection.commit()

    return {
        "success": True,
        "email": target_email,
        "company_id": company_id,
        "is_active": request.is_active
    }


class OfficeUsersRequest(BaseModel):
    token: str


@app.post("/office/users")
def office_users(
    request: OfficeUsersRequest
):

    token = request.token.strip()

    if not token:
        return {
            "success": False,
            "reason": "token_required"
        }

    # =========================================
    # 管理者token確認
    # =========================================

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    email,
                    company_id,
                    expires_at
                FROM office_login_tokens
                WHERE token = %s
                """,
                (
                    token,
                )
            )

            token_data = cursor.fetchone()

            if not token_data:
                return {
                    "success": False,
                    "reason": "invalid_token"
                }

            # -------------------------
            # token期限確認
            # -------------------------

            if time.time() > token_data[
                "expires_at"
            ]:

                cursor.execute(
                    """
                    DELETE FROM office_login_tokens
                    WHERE token = %s
                    """,
                    (
                        token,
                    )
                )

                connection.commit()

                return {
                    "success": False,
                    "reason": "token_expired"
                }

            admin_email = token_data[
                "email"
            ]

            company_id = token_data[
                "company_id"
            ]

            # =========================================
            # 管理者確認
            # =========================================

            cursor.execute(
                """
                SELECT
                    is_admin,
                    is_active
                FROM office_users
                WHERE email = %s
                AND company_id = %s
                """,
                (
                    admin_email,
                    company_id
                )
            )

            admin_user = cursor.fetchone()

            if not admin_user:
                return {
                    "success": False,
                    "reason": "user_not_found"
                }

            if not bool(
                admin_user["is_active"]
            ):
                return {
                    "success": False,
                    "reason": "user_inactive"
                }

            if not bool(
                admin_user["is_admin"]
            ):
                return {
                    "success": False,
                    "reason": "admin_required"
                }

    # =========================================
    # Stripeから最新seat_limit取得
    # =========================================

    sync_result = sync_office_seat_limit(
        company_id
    )

    if not sync_result["success"]:
        return {
            "success": False,
            "reason": sync_result["reason"]
        }

    seat_limit = sync_result[
        "seat_limit"
    ]

    # =========================================
    # ユーザー一覧取得
    # =========================================

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    email,
                    is_admin,
                    is_active,
                    created_at
                FROM office_users
                WHERE company_id = %s
                ORDER BY
                    is_admin DESC,
                    created_at ASC
                """,
                (
                    company_id,
                )
            )

            rows = cursor.fetchall()

    users = []

    active_user_count = 0

    for row in rows:

        user_is_active = bool(
            row["is_active"]
        )

        if user_is_active:
            active_user_count += 1

        users.append(
            {
                "email": row["email"],
                "is_admin": bool(
                    row["is_admin"]
                ),
                "is_active":
                    user_is_active
            }
        )

    # =========================================
    # 結果
    # =========================================

    return {
        "success": True,
        "company_id": company_id,
        "seat_limit": seat_limit,
        "active_user_count":
            active_user_count,
        "registered_user_count":
            len(users),
        "over_seat_limit":
            active_user_count
            > seat_limit,
        "users": users
    }


class OfficeChangePasswordRequest(BaseModel):
    email: str
    current_password: str
    new_password: str


@app.post("/office/change-password")
def office_change_password(
    request: OfficeChangePasswordRequest
):

    email = request.email.strip().lower()
    current_password = request.current_password
    new_password = request.new_password

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if not current_password:
        return {
            "success": False,
            "reason": "current_password_required"
        }

    if len(new_password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    if current_password == new_password:
        return {
            "success": False,
            "reason": "same_password"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    company_id,
                    password_hash,
                    is_active
                FROM office_users
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            user = cursor.fetchone()

            if not user:
                return {
                    "success": False,
                    "reason": "user_not_found"
                }

            if not bool(
                user["is_active"]
            ):
                return {
                    "success": False,
                    "reason": "user_inactive"
                }

            password_ok = password_hash.verify(
                current_password,
                user["password_hash"]
            )

            if not password_ok:
                return {
                    "success": False,
                    "reason": "invalid_password"
                }

            new_password_hash = (
                password_hash.hash(
                    new_password
                )
            )

            cursor.execute(
                """
                UPDATE office_users
                SET password_hash = %s
                WHERE email = %s
                """,
                (
                    new_password_hash,
                    email
                )
            )

            # パスワード変更後は
            # 全PCのログイントークンを無効化
            cursor.execute(
                """
                DELETE FROM office_login_tokens
                WHERE email = %s
                """,
                (
                    email,
                )
            )

        connection.commit()

    return {
        "success": True
    }


class PersonalAdminAllUsersRequest(BaseModel):
    admin_secret: str


@app.post("/admin/personal/all-users")
def personal_admin_all_users(request: PersonalAdminAllUsersRequest):

    # =========================================
    # 開発者専用認証
    # =========================================

    if not OFFICE_ADMIN_SECRET or request.admin_secret != OFFICE_ADMIN_SECRET:
        return {
            "success": False,
            "reason": "unauthorized"
        }

    # =========================================
    # 日本時間
    # =========================================

    japan_timezone = timezone(timedelta(hours=9))
    today_jst = datetime.now(japan_timezone).date()

    def timestamp_to_jst(timestamp):
        if timestamp is None:
            return None

        return datetime.fromtimestamp(
            timestamp,
            tz=japan_timezone
        ).strftime("%Y-%m-%d %H:%M:%S")

    # =========================================
    # 個人ユーザー取得
    # =========================================

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.email,
                    u.is_active,
                    u.created_at,
                    u.last_login_at,
                    u.last_seen_at,

                    COALESCE(
                        a.login_count,
                        0
                    ) AS today_login_count,

                    COALESCE(
                        a.server_connection_count,
                        0
                    ) AS today_server_connection_count,

                    COALESCE(
                        (
                            SELECT COUNT(*)
                            FROM user_daily_activity AS monthly_activity
                            WHERE LOWER(monthly_activity.email) = LOWER(u.email)
                            AND monthly_activity.login_count > 0
                            AND DATE_TRUNC(
                                'month',
                                monthly_activity.activity_date
                            ) = DATE_TRUNC(
                                'month',
                                %s::date
                            )
                        ),
                        0
                    ) AS this_month_login_days

                FROM users AS u

                LEFT JOIN user_daily_activity AS a
                    ON LOWER(a.email) = LOWER(u.email)
                    AND a.activity_date = %s

                ORDER BY
                    u.created_at ASC NULLS LAST,
                    u.email ASC
                """,
                (
                    today_jst,
                    today_jst
                )
            )

            rows = cursor.fetchall()

    # =========================================
    # レスポンス作成
    # =========================================

    users = []
    active_user_count = 0

    for row in rows:
        is_active = bool(row["is_active"])

        if is_active:
            active_user_count += 1

        users.append({
            "email": row["email"],
            "is_active": is_active,
            "created_at": timestamp_to_jst(row["created_at"]),
            "last_login_at": timestamp_to_jst(row["last_login_at"]),
            "last_seen_at": timestamp_to_jst(row["last_seen_at"]),
            "today_login_count": row["today_login_count"],
            "this_month_login_days": row["this_month_login_days"],
            "today_server_connection_count": row[
                "today_server_connection_count"
            ]
        })

    return {
        "success": True,
        "total_user_count": len(users),
        "total_active_user_count": active_user_count,
        "users": users
    }


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


@app.post("/register")
def register(
    request: RegisterRequest
):
    email = request.email.strip().lower()
    password = request.password

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if len(password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    existing_user = get_user_by_email(
        email
    )

    if existing_user:
        return {
            "success": False,
            "reason": "already_registered"
        }

    # -------------------------
    # メール本人確認済みか確認
    # -------------------------

    verification = get_verification_code(
        email
    )

    if not verification:
        return {
            "success": False,
            "reason": "email_not_verified"
        }

    if verification["verified"] != 1:
        return {
            "success": False,
            "reason": "email_not_verified"
        }

    # -------------------------
    # 念のためStripe契約も再確認
    # -------------------------

    if not is_subscription_active(email):
        return {
            "success": False,
            "reason": "subscription_not_active"
        }

    # -------------------------
    # パスワード保存
    # -------------------------

    hashed_password = password_hash.hash(
        password
    )

    create_user(
        email,
        hashed_password
    )

    delete_verification_code(
        email
    )

    return {
        "success": True
    }


class CustomerPortalRequest(BaseModel):
    token: str


@app.post("/login")
def login(
    request: LoginRequest
):
    email = request.email.strip().lower()
    password = request.password

    # -------------------------
    # ロック状態確認
    # -------------------------

    login_attempt = get_login_attempt(
        email
    )

    if login_attempt:
        locked_until = login_attempt[
            "locked_until"
        ]

        if locked_until > time.time():

            retry_after = int(
                locked_until - time.time()
            )

            return {
                "success": False,
                "reason": "login_locked",
                "retry_after": retry_after
            }

    user = get_user_by_email(
        email
    )

    if not user:
        return {
            "success": False,
            "reason": "user_not_found"
        }

    password_ok = password_hash.verify(
        password,
        user["password_hash"]
    )

    if not password_ok:

        register_login_failure(
            email
        )

        login_attempt = get_login_attempt(
            email
        )

        failed_count = login_attempt[
            "failed_count"
        ]

        # 5回失敗したら15分ロック
        if failed_count >= 5:

            locked_until = (
                time.time()
                + (15 * 60)
            )

            lock_login(
                email,
                locked_until
            )

            return {
                "success": False,
                "reason": "login_locked",
                "retry_after": 15 * 60
            }

        remaining_attempts = (
            5 - failed_count
        )

        return {
            "success": False,
            "reason": "invalid_password",
            "remaining_attempts": remaining_attempts
        }

    # -------------------------
    # パスワード成功
    # -------------------------

    reset_login_attempts(
        email
    )

    # -------------------------
    # Stripe確認
    # -------------------------

    if not is_subscription_active(
        email
    ):
        return {
            "success": False,
            "reason": "subscription_not_active"
        }

    # -------------------------
    # 古いtoken削除
    # -------------------------

    delete_login_tokens_by_email(
        email
    )

    # -------------------------
    # 新token発行
    # -------------------------
    token = secrets.token_urlsafe(
        48
    )
    created_at = time.time()
    expires_at = created_at + (30 * 24 * 60 * 60)

    # =========================================
    # 個人ユーザー 最新ログイン日時
    # 本日のログイン回数 +1
    # =========================================

    japan_timezone = timezone(timedelta(hours=9))
    today_jst = datetime.now(japan_timezone).date()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET
                    last_login_at = %s,
                    last_seen_at = %s
                WHERE email = %s
                """,
                (
                    created_at,
                    created_at,
                    email
                )
            )

            cursor.execute(
                """
                INSERT INTO user_daily_activity (
                    email,
                    activity_date,
                    login_count
                )
                VALUES (%s, %s, 1)
                ON CONFLICT (email, activity_date)
                DO UPDATE SET
                    login_count = user_daily_activity.login_count + 1
                """,
                (
                    email,
                    today_jst
                )
            )

        connection.commit()

    save_login_token(
        email,
        token,
        created_at
    )

    return {
        "success": True,
        "subscription_active": True,
        "token": token
    }

@app.post("/create-customer-portal")
def create_customer_portal(
    request: CustomerPortalRequest
):
    try:
        token = request.token.strip()

        # -------------------------
        # token確認
        # -------------------------

        token_data = get_login_token(
            token
        )

        if not token_data:
            return {
                "success": False,
                "reason": "invalid_token"
            }

        # -------------------------
        # token有効期限確認
        # -------------------------

        TOKEN_EXPIRE_SECONDS = (
            30 * 24 * 60 * 60
        )

        created_at = token_data[
            "created_at"
        ]

        if (
            time.time() - created_at
            > TOKEN_EXPIRE_SECONDS
        ):
            delete_login_token(
                token
            )

            return {
                "success": False,
                "reason": "token_expired"
            }

        # -------------------------
        # tokenからemail取得
        # -------------------------

        email = token_data[
            "email"
        ].strip().lower()

        print(
            "customer portal email:",
            email
        )

        # -------------------------
        # Stripe Customerを探す
        # -------------------------

        customers = stripe.Customer.list(
            email=email,
            limit=10
        )

        if not customers.data:
            return {
                "success": False,
                "reason": "customer_not_found"
            }

        # -------------------------
        # 契約中のCustomerを探す
        # -------------------------

        target_customer = None

        for customer in customers.data:

            subscriptions = stripe.Subscription.list(
                customer=customer.id,
                status="all",
                limit=100
            )

            for subscription in subscriptions.data:

                if subscription.status in (
                    "active",
                    "trialing"
                ):
                    target_customer = customer
                    break

            if target_customer:
                break

        if not target_customer:
            return {
                "success": False,
                "reason": "subscription_not_active"
            }

        # -------------------------
        # Customer Portal URL作成
        # -------------------------

        session = stripe.billing_portal.Session.create(
            customer=target_customer.id,
            return_url=CUSTOMER_PORTAL_RETURN_URL
        )

        return {
            "success": True,
            "url": session.url
        }

    except Exception as e:

        print(
            "create-customer-portal ERROR:",
            repr(e)
        )

        return {
            "success": False,
            "reason": "server_error",
            "detail": str(e)
        }

def send_verification_email(
    target_email,
    code
):
    params = {
        "from": "MoveSpirit <noreply@movespirit.net>",
        "to": [
            target_email
        ],
        "subject": "MoveSpirit Verification Code",
        "html": f"""
        <div style="font-family: Arial, sans-serif;">
            <h2>MoveSpirit</h2>

            <p>
                Your verification code is:
            </p>

            <h1>
                {code}
            </h1>

            <p>
                This code will expire in 10 minutes.
            </p>

            <p>
                If you did not request this code,
                please ignore this email.
            </p>
        </div>
        """
    }

    result = resend.Emails.send(
        params
    )

    print(
        "Resend result:",
        result
    )

    return result


def is_subscription_active(email):
    email = email.strip().lower()

    print(
        "is_subscription_active email:",
        email
    )

    customers = stripe.Customer.list(
        email=email,
        limit=10
    )

    print(
        "customer count:",
        len(customers.data)
    )

    for customer in customers.data:

        print(
            "customer:",
            customer.id,
            customer.email
        )

        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=100
        )

        for subscription in subscriptions.data:

            print(
                "subscription:",
                subscription.id,
                subscription.status,
                "cancel_at_period_end:",
                subscription.cancel_at_period_end
            )

            if subscription.status in (
                "active",
                "trialing"
            ):
                return True

    return False


def find_office_subscription(
    email
):

    email = email.strip().lower()

    if not OFFICE_PRICE_ID:
        return {
            "success": False,
            "reason": "office_price_id_not_set"
        }

    print(
        "OFFICE_PRICE_ID:",
        OFFICE_PRICE_ID
    )

    customers = stripe.Customer.list(
        email=email,
        limit=10
    )

    print(
        "customer count:",
        len(customers.data)
    )

    for customer in customers.data:

        print(
            "customer:",
            customer.id,
            customer.email
        )

        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=100
        )

        for subscription in subscriptions.data:

            print(
                "subscription:",
                subscription.id,
                subscription.status
            )

            if subscription.status not in (
                "active",
                "trialing"
            ):
                continue

            for item in subscription["items"]["data"]:

                stripe_price_id = item["price"]["id"]

                print(
                    "Stripe price ID:",
                    stripe_price_id
                )

                print(
                    "Expected Office price ID:",
                    OFFICE_PRICE_ID
                )

                if stripe_price_id != OFFICE_PRICE_ID:
                    continue

                quantity = item.quantity

                if not quantity:
                    quantity = 1

                print(
                    "OFFICE SUBSCRIPTION FOUND:",
                    quantity
                )

                return {
                    "success": True,
                    "customer_id": customer.id,
                    "subscription_id": subscription.id,
                    "quantity": quantity
                }

    return {
        "success": False,
        "reason": "office_subscription_not_active"
    }


def sync_office_seat_limit(company_id):
    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # 会社情報取得
            # -------------------------

            cursor.execute(
                """
                SELECT
                    stripe_subscription_id,
                    is_unlimited_trial,
                    trial_expires_at
                FROM office_companies
                WHERE company_id = %s
                """,
                (
                    company_id,
                )
            )

            company = cursor.fetchone()

            if not company:
                return {
                    "success": False,
                    "reason": "company_not_found"
                }

            # =========================
            # 90日無料テスト
            # =========================

            is_unlimited_trial = bool(
                company[
                    "is_unlimited_trial"
                ]
            )

            trial_expires_at = company[
                "trial_expires_at"
            ]

            if is_unlimited_trial:

                # 有効期限なしは異常
                if not trial_expires_at:
                    return {
                        "success": False,
                        "reason": "trial_expiration_not_set"
                    }

                # 90日終了
                if time.time() > trial_expires_at:
                    return {
                        "success": False,
                        "reason": "trial_expired"
                    }

                # 無料テスト中は実質無制限
                seat_limit = 999999

                cursor.execute(
                    """
                    UPDATE office_companies
                    SET seat_limit = %s
                    WHERE company_id = %s
                    """,
                    (
                        seat_limit,
                        company_id
                    )
                )

                connection.commit()

                return {
                    "success": True,
                    "seat_limit": seat_limit,
                    "trial": True,
                    "trial_expires_at": trial_expires_at
                }

            # =========================
            # ここから通常の有料Office
            # =========================

            if not OFFICE_PRICE_ID:
                return {
                    "success": False,
                    "reason": "office_price_id_not_set"
                }

            subscription_id = company[
                "stripe_subscription_id"
            ]

            if not subscription_id:
                return {
                    "success": False,
                    "reason": "stripe_subscription_not_set"
                }

            subscription = stripe.Subscription.retrieve(
                subscription_id
            )

            if subscription.status not in (
                "active",
                "trialing"
            ):
                return {
                    "success": False,
                    "reason": "subscription_not_active"
                }

            office_item = None

            for item in subscription[
                "items"
            ][
                "data"
            ]:

                stripe_price_id = item[
                    "price"
                ][
                    "id"
                ]

                if (
                    stripe_price_id
                    == OFFICE_PRICE_ID
                ):
                    office_item = item
                    break

            if not office_item:
                return {
                    "success": False,
                    "reason": "office_subscription_item_not_found"
                }

            quantity = office_item.quantity

            if not quantity:
                quantity = 1

            cursor.execute(
                """
                UPDATE office_companies
                SET seat_limit = %s
                WHERE company_id = %s
                """,
                (
                    quantity,
                    company_id
                )
            )

        connection.commit()

    return {
        "success": True,
        "seat_limit": quantity,
        "trial": False
    }


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@app.post("/verify-code")
def verify_code(
    request: VerifyCodeRequest
):
    email = request.email.strip().lower()
    code = request.code.strip()

    verification = get_verification_code(
        email
    )

    if not verification:
        return {
            "success": False,
            "reason": "verification_not_found"
        }

    # 有効期限確認
    if time.time() > verification["expires_at"]:
        return {
            "success": False,
            "reason": "verification_expired"
        }

    # 入力されたコードをハッシュ化
    input_code_hash = hashlib.sha256(
        code.encode("utf-8")
    ).hexdigest()

    # DBに保存したハッシュと比較
    if input_code_hash != verification["code_hash"]:
        return {
            "success": False,
            "reason": "invalid_code"
        }

    # 本人確認済みにする
    set_email_verified(
        email
    )

    return {
        "success": True
    }


stripe_key = os.getenv("STRIPE_SECRET_KEY")

print(
    "Stripe key exists:",
    bool(stripe_key)
)

print(
    "Stripe key prefix:",
    stripe_key[:8] if stripe_key else None
)

print(
    "Stripe key length:",
    len(stripe_key) if stripe_key else 0
)


class SendVerificationCodeRequest(BaseModel):
    email: str

@app.post("/send-verification-code")
def send_verification_code(
    request: SendVerificationCodeRequest
):
    try:
        email = request.email.strip().lower()

        if not email:
            return {
                "success": False,
                "reason": "email_required"
            }

        existing_user = get_user_by_email(
            email
        )

        if existing_user:
            return {
                "success": False,
                "reason": "already_registered"
            }

        if not is_subscription_active(
            email
        ):
            return {
                "success": False,
                "reason": "subscription_not_active"
            }

        # -------------------------
        # 60秒以内の再送を禁止
        # -------------------------

        existing_verification = (
            get_verification_code(
                email
            )
        )

        if existing_verification:

            last_sent_at = (
                existing_verification[
                    "sent_at"
                ]
            )

            elapsed = (
                time.time()
                - last_sent_at
            )

            if elapsed < 60:

                retry_after = max(
                    1,
                    int(60 - elapsed)
                )

                return {
                    "success": False,
                    "reason": "too_many_requests",
                    "retry_after": retry_after
                }

        # -------------------------
        # 6桁コード生成
        # -------------------------

        code = (
            f"{secrets.randbelow(1000000):06d}"
        )

        code_hash = hashlib.sha256(
            code.encode("utf-8")
        ).hexdigest()

        # 現在時刻
        sent_at = time.time()

        # 10分後に失効
        expires_at = (
            sent_at + 600
        )

        # -------------------------
        # メール送信
        # -------------------------

        send_verification_email(
            email,
            code
        )

        # -------------------------
        # DB保存
        # -------------------------

        save_verification_code(
            email,
            code_hash,
            expires_at,
            sent_at
        )

        return {
            "success": True
        }

        return {
            "success": True
        }

    except Exception as e:

        print(
            "send-verification-code ERROR:",
            repr(e)
        )

        return {
            "success": False,
            "reason": "server_error",
            "detail": str(e)
        }


class SendPasswordResetCodeRequest(BaseModel):
    email: str


@app.post("/send-password-reset-code")
def send_password_reset_code(
    request: SendPasswordResetCodeRequest
):
    try:
        email = request.email.strip().lower()

        if not email:
            return {
                "success": False,
                "reason": "email_required"
            }

        # -------------------------
        # 登録済みユーザーか確認
        # -------------------------

        user = get_user_by_email(
            email
        )

        if not user:
            return {
                "success": False,
                "reason": "user_not_found"
            }

        # -------------------------
        # 60秒以内の再送禁止
        # -------------------------

        existing_reset = get_password_reset_code(
            email
        )

        if existing_reset:

            last_sent_at = existing_reset[
                "sent_at"
            ]

            elapsed = (
                time.time()
                - last_sent_at
            )

            if elapsed < 60:

                retry_after = max(
                    1,
                    int(60 - elapsed)
                )

                return {
                    "success": False,
                    "reason": "too_many_requests",
                    "retry_after": retry_after
                }

        # -------------------------
        # 6桁コード生成
        # -------------------------

        code = (
            f"{secrets.randbelow(1000000):06d}"
        )

        code_hash = hashlib.sha256(
            code.encode("utf-8")
        ).hexdigest()

        sent_at = time.time()

        # 10分後に失効
        expires_at = (
            sent_at + 600
        )

        # -------------------------
        # メール送信
        # -------------------------

        params = {
            "from": "MoveSpirit <noreply@movespirit.net>",
            "to": [
                email
            ],
            "subject": "MoveSpirit Password Reset Code",
            "html": f"""
            <div style="font-family: Arial, sans-serif;">
                <h2>MoveSpirit</h2>

                <p>
                    Your password reset code is:
                </p>

                <h1>
                    {code}
                </h1>

                <p>
                    This code will expire in 10 minutes.
                </p>

                <p>
                    If you did not request a password reset,
                    please ignore this email.
                </p>
            </div>
            """
        }

        resend.Emails.send(
            params
        )

        # -------------------------
        # メール送信成功後にDB保存
        # -------------------------

        save_password_reset_code(
            email,
            code_hash,
            expires_at,
            sent_at
        )

        return {
            "success": True
        }

    except Exception as e:

        print(
            "send-password-reset-code ERROR:",
            repr(e)
        )

        return {
            "success": False,
            "reason": "server_error",
            "detail": str(e)
        }


class VerifyPasswordResetCodeRequest(BaseModel):
    email: str
    code: str


@app.post("/verify-password-reset-code")
def verify_password_reset_code(
    request: VerifyPasswordResetCodeRequest
):
    email = request.email.strip().lower()
    code = request.code.strip()

    reset_data = get_password_reset_code(
        email
    )

    if not reset_data:
        return {
            "success": False,
            "reason": "verification_not_found"
        }

    # -------------------------
    # 有効期限確認
    # -------------------------

    if time.time() > reset_data[
        "expires_at"
    ]:
        return {
            "success": False,
            "reason": "verification_expired"
        }

    # -------------------------
    # 入力コードをハッシュ化
    # -------------------------

    input_code_hash = hashlib.sha256(
        code.encode("utf-8")
    ).hexdigest()

    if (
        input_code_hash
        != reset_data["code_hash"]
    ):
        return {
            "success": False,
            "reason": "invalid_code"
        }

    # -------------------------
    # パスワード変更許可状態にする
    # -------------------------

    set_password_reset_verified(
        email
    )

    return {
        "success": True
    }


class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str


@app.post("/reset-password")
def reset_password(
    request: ResetPasswordRequest
):
    email = request.email.strip().lower()
    new_password = request.new_password

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    if len(new_password) < 8:
        return {
            "success": False,
            "reason": "password_too_short"
        }

    # -------------------------
    # 登録済みユーザーか確認
    # -------------------------

    user = get_user_by_email(
        email
    )

    if not user:
        return {
            "success": False,
            "reason": "user_not_found"
        }

    # -------------------------
    # 認証コード確認済みか確認
    # -------------------------

    reset_data = get_password_reset_code(
        email
    )

    if not reset_data:
        return {
            "success": False,
            "reason": "email_not_verified"
        }

    if reset_data[
        "verified"
    ] != 1:
        return {
            "success": False,
            "reason": "email_not_verified"
        }

    # -------------------------
    # 念のため有効期限も再確認
    # -------------------------

    if time.time() > reset_data[
        "expires_at"
    ]:
        return {
            "success": False,
            "reason": "verification_expired"
        }

    # -------------------------
    # 新しいパスワードをハッシュ化
    # -------------------------

    hashed_password = password_hash.hash(
        new_password
    )

    update_user_password(
        email,
        hashed_password
    )

    # -------------------------
    # 古いログイントークンを全削除
    # -------------------------

    delete_login_tokens_by_email(
        email
    )

    # -------------------------
    # パスワード再設定情報を削除
    # -------------------------

    delete_password_reset_code(
        email
    )

    return {
        "success": True
    }

class SubscriptionCheckRequest(BaseModel):
    email: str

@app.post("/check-subscription")
def check_subscription(request: SubscriptionCheckRequest):

    email = request.email.strip().lower()

    customers = stripe.Customer.list(
        email=email,
        limit=10
    )

    if not customers.data:
        return {
            "active": False,
            "email": email,
            "reason": "customer_not_found"
        }

    for customer in customers.data:

        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=100
        )

        for subscription in subscriptions.data:

            if subscription.status in (
                "active",
                "trialing"
            ):
                return {
                    "active": True,
                    "email": email,
                    "customer_id": customer.id,
                    "subscription_id": subscription.id,
                    "subscription_status": subscription.status
                }

    return {
        "active": False,
        "email": email,
        "reason": "active_subscription_not_found"
    }

class TokenCheckRequest(BaseModel):
    token: str


@app.post("/check-token")
def check_token(
    request: TokenCheckRequest
):
    token = request.token.strip()

    token_data = get_login_token(
        token
    )

    print(
        "token_data:",
        token_data
    )

    if not token_data:
        return {
            "success": False,
            "reason": "invalid_token"
        }

    TOKEN_EXPIRE_SECONDS = (30 * 24 * 60 * 60)

    created_at = token_data[
        "created_at"
    ]

    if (
        time.time() - created_at
        > TOKEN_EXPIRE_SECONDS
    ):
        delete_login_token(
            token
        )

        return {
            "success": False,
            "reason": "token_expired"
        }

    email = token_data[
        "email"
    ]

    print(
        "check-token email:",
        email
    )

    active = is_subscription_active(
        email
    )

    print(
        "subscription active:",
        active
    )

    if not active:
        delete_login_token(
            token
        )

        return {
            "success": False,
            "reason": "subscription_not_active"
        }

    return {
        "success": True,
        "subscription_active": True,
        "email": email
    }

class DeletePersonalUserRequest(BaseModel):
    admin_secret: str
    email: str


@app.post("/admin/personal/delete-user")
def delete_personal_user(request: DeletePersonalUserRequest):
    if not OFFICE_ADMIN_SECRET or request.admin_secret != OFFICE_ADMIN_SECRET:
        return {
            "success": False,
            "reason": "unauthorized"
        }

    email = request.email.strip().lower()

    if not email:
        return {
            "success": False,
            "reason": "email_required"
        }

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM login_tokens
                WHERE email = %s
                """,
                (email,)
            )

            cursor.execute(
                """
                DELETE FROM user_daily_activity
                WHERE email = %s
                """,
                (email,)
            )

            cursor.execute(
                """
                DELETE FROM users
                WHERE email = %s
                """,
                (email,)
            )

        connection.commit()

    return {
        "success": True,
        "email": email
    }
