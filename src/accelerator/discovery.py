"""Compatibility re-export of secure discovery from etl-migration-core."""

from __future__ import annotations

from typing import IO

from etl_migration_core.discovery import (
    DEFAULT_ADAPTER_VERSIONS as DEFAULT_ADAPTER_VERSIONS,
)
from etl_migration_core.discovery import (
    DiscoveryService as _CoreDiscoveryService,
)
from etl_migration_core.discovery import (
    InputRejectedError as InputRejectedError,
)
from etl_migration_core.discovery import (
    _hash_stream as _hash_stream,
)
from etl_migration_core.discovery import (
    validate_member_path as validate_member_path,
)


class DiscoveryService(_CoreDiscoveryService):
    """Compatibility subclass honoring module-level `_hash_stream` monkeypatches."""

    def _stream_digest(self, stream: IO[bytes]) -> str:
        return _hash_stream(stream)
