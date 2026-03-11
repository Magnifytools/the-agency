"""Reset a user's password.

Usage:
  python -m backend.scripts.reset_password nacho@magnify.ing NewPassword123!
"""
import asyncio
import sys

from sqlalchemy import select

from backend.core.security import hash_password
from backend.db.database import async_session
from backend.db.models import User


async def main():
    if len(sys.argv) < 3:
        print("Usage: python -m backend.scripts.reset_password <email> <new_password>")
        sys.exit(1)

    email = sys.argv[1].lower()
    new_password = sys.argv[2]

    if len(new_password) < 8:
        print("Error: password must be at least 8 characters")
        sys.exit(1)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: user '{email}' not found")
            sys.exit(1)

        user.hashed_password = hash_password(new_password)
        await db.commit()
        print(f"✓ Password updated for {user.full_name} ({email})")


if __name__ == "__main__":
    asyncio.run(main())
