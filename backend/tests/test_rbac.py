import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from backend.api.deps import require_module
from backend.db.models import User, UserRole, UserPermission


class TestRequireModule:
    @pytest.mark.asyncio
    async def test_admin_bypasses_all(self):
        admin = MagicMock(spec=User)
        admin.role = UserRole.admin

        checker = require_module("clients")
        result = await checker(admin)
        assert result == admin

    @pytest.mark.asyncio
    async def test_member_with_read_permission(self):
        member = MagicMock(spec=User)
        member.role = UserRole.member
        perm = MagicMock(spec=UserPermission)
        perm.module = "clients"
        perm.can_read = True
        perm.can_write = False
        member.permissions = [perm]

        checker = require_module("clients")
        result = await checker(member)
        assert result == member

    @pytest.mark.asyncio
    async def test_member_without_permission_blocked(self):
        member = MagicMock(spec=User)
        member.role = UserRole.member
        member.permissions = []

        checker = require_module("clients")
        with pytest.raises(HTTPException) as exc_info:
            await checker(member)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_read_only_blocked_on_write(self):
        member = MagicMock(spec=User)
        member.role = UserRole.member
        perm = MagicMock(spec=UserPermission)
        perm.module = "clients"
        perm.can_read = True
        perm.can_write = False
        member.permissions = [perm]

        checker = require_module("clients", write=True)
        with pytest.raises(HTTPException) as exc_info:
            await checker(member)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_with_write_permission_allowed(self):
        member = MagicMock(spec=User)
        member.role = UserRole.member
        perm = MagicMock(spec=UserPermission)
        perm.module = "clients"
        perm.can_read = True
        perm.can_write = True
        member.permissions = [perm]

        checker = require_module("clients", write=True)
        result = await checker(member)
        assert result == member
