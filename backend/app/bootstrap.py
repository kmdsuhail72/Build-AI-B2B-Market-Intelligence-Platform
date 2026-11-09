import os

from sqlalchemy import select

from app.main import SessionLocal, User, password_hash


def main() -> None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    with SessionLocal() as db:
        existing_admin = db.scalar(select(User.id).where(User.role == "admin").limit(1))
        if existing_admin:
            return
        if not email or len(password) < 12:
            raise RuntimeError(
                "Set BOOTSTRAP_ADMIN_EMAIL and a BOOTSTRAP_ADMIN_PASSWORD of at least 12 "
                "characters before starting a new database."
            )
        if db.scalar(select(User.id).where(User.email == email)):
            raise RuntimeError("The bootstrap email already belongs to a non-admin account.")
        db.add(User(email=email, password_hash=password_hash.hash(password), role="admin"))
        db.commit()
        print(f"Created initial administrator account: {email}")


if __name__ == "__main__":
    main()
