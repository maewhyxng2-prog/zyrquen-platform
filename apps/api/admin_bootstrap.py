import os
from uuid import UUID

from sqlalchemy.orm import Session

from apps.api.database import SessionLocal
from apps.api.models import User


def configured_admin_user_ids() -> set[UUID]:
    configured_ids = os.getenv("ZYRQUEN_ADMIN_USER_IDS", "")
    if not configured_ids.strip():
        raise ValueError("ZYRQUEN_ADMIN_USER_IDS must contain at least one user ID")

    try:
        user_ids = {UUID(value.strip()) for value in configured_ids.split(",")}
    except ValueError:
        raise ValueError("ZYRQUEN_ADMIN_USER_IDS must contain valid UUIDs") from None

    if not user_ids:
        raise ValueError("ZYRQUEN_ADMIN_USER_IDS must contain at least one user ID")
    return user_ids


def bootstrap_admin_users(db: Session) -> int:
    user_ids = configured_admin_user_ids()

    users = db.query(User).filter(User.id.in_(user_ids)).all()
    found_ids = {user.id for user in users}
    if found_ids != user_ids:
        db.rollback()
        raise ValueError("One or more trusted admin user IDs do not exist")

    for user in users:
        user.role = "admin"
    db.commit()
    return len(users)


def main() -> None:
    db = SessionLocal()
    try:
        count = bootstrap_admin_users(db)
    finally:
        db.close()
    print(f"Bootstrapped {count} trusted admin account(s).")


if __name__ == "__main__":
    main()
