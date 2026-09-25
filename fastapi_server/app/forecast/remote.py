"""Fetch the agent's forecast store from DataRobot when running as a deployed app.

When deployed, the agent (a DataRobot deployment) uploads its SQLite store to
the Files API and points a Key-Value entry on its deployment at the latest file
(agent/agent/forecast/remote_store.py). This module mirrors that file into a
local working copy, re-checking the entry at most every few seconds.

Selected automatically: only when ``APPLICATION_ID`` is set (DataRobot sets it
for custom applications, same switch as the app's own persistent database) and
the agent deployment ID is known. ``FORECAST_STORE_DEPLOYMENT_ID`` forces it
(for testing from a local machine).
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KV_NAME = "forecast_store"  # must match the agent side
REFRESH_INTERVAL_S = 3.0
HTTP_TIMEOUT_S = (60, 180)


def store_deployment_id() -> str | None:
    forced = os.environ.get("FORECAST_STORE_DEPLOYMENT_ID", "").strip()
    if forced:
        return forced
    if not os.environ.get("APPLICATION_ID"):
        return None
    from datarobot.core.config import getenv

    value = str(getenv("AGENT_DEPLOYMENT_ID") or "").strip()
    return value if value and value != "SET_VIA_PULUMI_OR_MANUALLY" else None


class RemoteStoreCache:
    def __init__(self, deployment_id: str) -> None:
        self.deployment_id = deployment_id
        self.path = (
            Path(tempfile.gettempdir())
            / "forecast_store_mirror"
            / "forecast_store.sqlite"
        )
        self._catalog_id: str | None = None
        self._checked_at = 0.0
        self._lock = threading.Lock()
        self._client: Any = None

    def _dr(self) -> Any:
        import datarobot as dr
        from datarobot.core.config import getenv

        if self._client is None:
            self._client = dr.Client(
                token=str(getenv("DATAROBOT_API_TOKEN") or ""),
                endpoint=str(getenv("DATAROBOT_ENDPOINT") or ""),
            )
        return self._client

    def refresh(self) -> Path:
        """Download a newer store file if the agent published one."""
        with self._lock:
            if time.monotonic() - self._checked_at < REFRESH_INTERVAL_S:
                return self.path
            self._checked_at = time.monotonic()
            try:
                import datarobot as dr

                client = self._dr()
                with client:
                    kv = dr.KeyValue.find(
                        self.deployment_id,
                        dr.enums.KeyValueEntityType.DEPLOYMENT,
                        KV_NAME,
                    )
                if not kv or not kv.value:
                    return self.path
                catalog_id = json.loads(kv.value)["catalog_id"]
                if catalog_id == self._catalog_id and self.path.exists():
                    return self.path
                r = client.get(f"files/{catalog_id}/file/", timeout=HTTP_TIMEOUT_S)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".download")
                tmp.write_bytes(r.content)
                os.replace(tmp, self.path)
                self._catalog_id = catalog_id
            except Exception as e:  # noqa: BLE001 - keep serving the last copy
                logger.warning("forecast store refresh failed (%s)", type(e).__name__)
            return self.path


_cache: RemoteStoreCache | None = None
_cache_lock = threading.Lock()


def remote_store_path() -> Path | None:
    """Local mirror of the deployed agent's store, or None when running locally."""
    global _cache
    dep = store_deployment_id()
    if not dep:
        return None
    with _cache_lock:
        if _cache is None or _cache.deployment_id != dep:
            _cache = RemoteStoreCache(dep)
    return _cache.refresh()
