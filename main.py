import os
import hashlib
import secrets
import time

import stripe
import resend

from database import (
    initialize_database,
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

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from pwdlib import PasswordHash

from database import (
    initialize_database,
    get_user_by_email,
    create_user
)

load_dotenv()
resend.api_key = os.getenv("RESEND_API_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


app = FastAPI()
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


class LoginRequest(BaseModel):
    email: str
    password: str


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
