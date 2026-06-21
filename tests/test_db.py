from discord_bot import db


class TestGetCooldown:
    """Tests for the get_cooldown function."""

    def test_returns_false_when_not_set(self, patch_db_redis):
        is_on_cooldown, ttl = db.get_cooldown("test-command")

        assert is_on_cooldown is False
        assert ttl == 0

    def test_returns_true_when_set(self, patch_db_redis):
        # Set a cooldown first
        db.set_cooldown("test-command", 60)

        is_on_cooldown, ttl = db.get_cooldown("test-command")

        assert is_on_cooldown is True
        assert ttl > 0

    def test_returns_correct_ttl(self, patch_db_redis):
        db.set_cooldown("test-command", 120)

        is_on_cooldown, ttl = db.get_cooldown("test-command")

        assert is_on_cooldown is True
        # TTL should be close to 120 (might be slightly less due to timing)
        assert 118 <= ttl <= 120


class TestSetCooldown:
    """Tests for the set_cooldown function."""

    def test_creates_key_with_expiry(self, patch_db_redis):
        db.set_cooldown("test-command", 60)

        # Verify the key exists
        assert patch_db_redis.get("cooldown_test-command") is not None

        # Verify the TTL is set
        ttl = patch_db_redis.ttl("cooldown_test-command")
        assert ttl > 0
        assert ttl <= 60

    def test_key_has_correct_value(self, patch_db_redis):
        db.set_cooldown("test-command", 60)

        value = patch_db_redis.get("cooldown_test-command")
        assert value == b"1"


class TestGetRedis:
    """Tests for the get_redis function."""

    def test_returns_redis_instance(self, patch_db_redis):
        redis_instance = db.get_redis()

        # Should return a Redis-like object
        assert redis_instance is not None
        assert hasattr(redis_instance, "get")
        assert hasattr(redis_instance, "set")


class TestCooldownIntegration:
    """Integration tests for the cooldown flow."""

    def test_full_cooldown_cycle(self, patch_db_redis):
        command = "my-command"

        # Initially not on cooldown
        is_on_cooldown, _ = db.get_cooldown(command)
        assert is_on_cooldown is False

        # Set cooldown
        db.set_cooldown(command, 60)

        # Now on cooldown
        is_on_cooldown, ttl = db.get_cooldown(command)
        assert is_on_cooldown is True
        assert ttl > 0

        # Delete the key to simulate expiry
        patch_db_redis.delete(f"cooldown_{command}")

        # No longer on cooldown
        is_on_cooldown, _ = db.get_cooldown(command)
        assert is_on_cooldown is False

    def test_different_commands_have_separate_cooldowns(self, patch_db_redis):
        db.set_cooldown("command-a", 60)

        # Command A is on cooldown
        is_on_cooldown_a, _ = db.get_cooldown("command-a")
        assert is_on_cooldown_a is True

        # Command B is not on cooldown
        is_on_cooldown_b, _ = db.get_cooldown("command-b")
        assert is_on_cooldown_b is False
