"""Common test utilities."""

from engine.domain.identities import ContentHash


def make_hash(data: str = "test") -> ContentHash:
    """Create a content hash for testing."""
    return ContentHash.from_string(data)
