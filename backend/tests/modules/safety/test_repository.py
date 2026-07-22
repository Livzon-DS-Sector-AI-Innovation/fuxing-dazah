"""Tests for SafetyRepository data access."""


class TestSafetyRepository:
    async def test_get_checks_with_filters(self, db_session) -> None:
        pass

    async def test_soft_delete(self, db_session) -> None:
        """Test that delete sets is_deleted=True rather than removing row."""
        pass

    async def test_count_queries(self, db_session) -> None:
        pass
