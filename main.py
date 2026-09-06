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

resend.api_key = os.getenv(
    "RESEND_API_KEY"
)

CUSTOMER_PORTAL_RETURN_URL = os.getenv(
    "CUSTOMER_PORTAL_RETURN_URL",
    "https://x.com/ShimaAnimation"
)

password_hash = PasswordHash.recommended()

initialize_database()


class SubscriptionCheckRequest(BaseModel):
    email: str


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


class RegisterRequest(BaseModel):
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
                    seat_limit,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    company_id,
                    company_name,
                    email,
                    1,
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
        "company_id": company_id
    }


class OfficeLoginRequest(BaseModel):
    email: str
    password: str


@app.post("/office/login")
def office_login(
    request: OfficeLoginRequest
):

    email = request.email.strip().lower()
    password = request.password

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

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------
            # Officeユーザー取得
            # -------------------------

            cursor.execute(
                """
                SELECT
                    id,
                    company_id,
                    email,
                    password_hash,
                    is_admin
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

            user_id = user["id"]
            company_id = user["company_id"]
            user_email = user["email"]
            hashed_password = user["password_hash"]
            is_admin = user["is_admin"]

            # -------------------------
            # パスワード確認
            # -------------------------

            password_ok = password_hash.verify(
                password,
                hashed_password
            )

            if not password_ok:
                return {
                    "success": False,
                    "reason": "invalid_password"
                }

            # -------------------------
            # 会社情報確認
            # -------------------------

            cursor.execute(
                """
                SELECT
                    company_name,
                    admin_email,
                    seat_limit,
                    stripe_customer_id,
                    stripe_subscription_id
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

            company_name = company["company_name"]
            seat_limit = company["seat_limit"]

            # -------------------------
            # 以前のOfficeトークン削除
            # -------------------------

            cursor.execute(
                """
                DELETE FROM office_login_tokens
                WHERE email = %s
                """,
                (
                    email,
                )
            )

            # -------------------------
            # 新しいトークン生成
            # -------------------------

            token = secrets.token_urlsafe(
                48
            )

            created_at = time.time()

            expires_at = (
                created_at
                + (30 * 24 * 60 * 60)
            )

            cursor.execute(
                """
                INSERT INTO office_login_tokens (
                    email,
                    token,
                    company_id,
                    created_at,
                    expires_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    email,
                    token,
                    company_id,
                    created_at,
                    expires_at
                )
            )

        connection.commit()

    return {
        "success": True,
        "token": token,
        "email": user_email,
        "company_id": company_id,
        "company_name": company_name,
        "is_admin": bool(is_admin),
        "seat_limit": seat_limit
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
                SELECT
                    company_name,
                    seat_limit
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

            seat_limit = company["seat_limit"]

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


class LoginRequest(BaseModel):
    email: str
    password: str


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

    save_login_token(
        email,
        token,
        time.time()
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
