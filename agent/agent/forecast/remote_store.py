"""Persist the forecast store in DataRobot when the agent runs as a deployment.

Locally (``dr run dev``) the store is a plain SQLite file shared with the backend.
Deployed (``dr run deploy``), the agent and the backend run in separate
containers, so the agent uploads the SQLite file to the DataRobot Files API
after each write and records the current file in a Key-Value entry on its own
deployment. The backend (which knows ``AGENT_DEPLOYMENT_ID``) downloads the file
when that entry changes. The switch is automatic: it only happens when
``MLOPS_DEPLOYMENT_ID`` is set, which DataRobot does for deployed custom models.

Same pattern as ``core/persistent_fs`` (used by the backend for its own
database), but keyed to the agent deployment instead of the application.
"""

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KV_NAME = "forecast_store"
FILE_NAME = "forecast_store.sqlite"
PUSH_DEBOUNCE_S = 0.5
HTTP_TIMEOUT_S = (60, 180)


def store_deployment_id() -> str | None:
    """Deployment the store is attached to, or None for local mode.

    ``FORECAST_STORE_DEPLOYMENT_ID`` overrides (for testing against DataRobot
    from a local machine); otherwise DataRobot's ``MLOPS_DEPLOYMENT_ID``.
    """
    for name in ("FORECAST_STORE_DEPLOYMENT_ID", "MLOPS_DEPLOYMENT_ID"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def remote_local_path() -> Path:
    """Working copy shared by all worker processes in the container."""
    return Path(tempfile.gettempdir()) / "forecast_store" / FILE_NAME


def _client() -> Any:
    import datarobot as dr

    from agent.forecast.predictor import credentials

    endpoint, token = credentials()
    return dr.Client(token=token, endpoint=endpoint)


class DataRobotStoreSync:
    """Pull the store at startup; push it (debounced) after every write."""

    def __init__(
        self, deployment_id: str, local_path: Path, background: bool = True
    ) -> None:
        self.deployment_id = deployment_id
        self.local_path = local_path
        self.background = background  # False: pushes only happen on flush() (tests)
        self._client_obj: Any = None
        self._dirty = threading.Event()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self.last_error: str | None = None

    # ---------------------------------------------------------------- helpers
    @property
    def client(self) -> Any:
        if self._client_obj is None:
            self._client_obj = _client()
        return self._client_obj

    def _find_kv(self) -> Any:
        import datarobot as dr

        with self.client:
            return dr.KeyValue.find(
                self.deployment_id, dr.enums.KeyValueEntityType.DEPLOYMENT, KV_NAME
            )

    def remote_info(self) -> dict[str, Any] | None:
        kv = self._find_kv()
        return json.loads(kv.value) if kv and kv.value else None

    # ---------------------------------------------------------------- pull
    def pull(self) -> bool:
        """Download the stored file (if any) into the local working copy."""
        from agent.forecast.predictor import sanitize

        try:
            info = self.remote_info()
            if not info:
                return False
            r = self.client.get(
                f"files/{info['catalog_id']}/file/", timeout=HTTP_TIMEOUT_S
            )
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.local_path.with_suffix(".download")
            tmp.write_bytes(r.content)
            os.replace(tmp, self.local_path)
            logger.info(
                "forecast store pulled from DataRobot (%s bytes)", len(r.content)
            )
            return True
        except Exception as e:  # noqa: BLE001 - start empty rather than fail the agent
            self.last_error = sanitize(f"{type(e).__name__}: {e}")
            logger.warning("forecast store pull failed: %s", self.last_error)
            return False

    # ---------------------------------------------------------------- push
    def schedule_push(self) -> None:
        self._dirty.set()
        if not self.background:
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, name="forecast-store-push", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        while self._dirty.wait(timeout=60):
            time.sleep(PUSH_DEBOUNCE_S)  # coalesce bursts (run + issues + bands)
            self._dirty.clear()
            self.push()

    def push(self) -> bool:
        """Upload a consistent snapshot and point the Key-Value entry at it."""
        import datarobot as dr

        from agent.forecast.predictor import sanitize

        with self._lock:
            try:
                snap = self.local_path.with_suffix(".snapshot")
                src = sqlite3.connect(self.local_path, timeout=30)
                dst = sqlite3.connect(snap)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                with open(snap, "rb") as f:
                    r = self.client.post(
                        "files/fromFile/",
                        files={"file": (FILE_NAME, f)},
                        data={"useArchiveContents": "false"},
                        timeout=HTTP_TIMEOUT_S,
                    )
                catalog_id = r.json()["catalogId"]
                value = json.dumps(
                    {
                        "catalog_id": catalog_id,
                        "version": time.time(),
                        "size": snap.stat().st_size,
                    }
                )
                with self.client:
                    kv = dr.KeyValue.find(
                        self.deployment_id,
                        dr.enums.KeyValueEntityType.DEPLOYMENT,
                        KV_NAME,
                    )
                    old = (
                        json.loads(kv.value).get("catalog_id")
                        if kv and kv.value
                        else None
                    )
                    if kv:
                        kv.update(value=value)
                    else:
                        dr.KeyValue.create(
                            entity_id=self.deployment_id,
                            entity_type=dr.enums.KeyValueEntityType.DEPLOYMENT,
                            name=KV_NAME,
                            category=dr.enums.KeyValueCategory.ARTIFACT,
                            value_type=dr.enums.KeyValueType.JSON,
                            value=value,
                            description="Forecast agent store (runs, adjustment log, page data)",
                        )
                if old and old != catalog_id:
                    try:
                        self.client.delete(f"files/{old}/")
                    except Exception:  # noqa: BLE001 - stale file cleanup is best effort
                        logger.debug("could not delete old store file")
                snap.unlink(missing_ok=True)
                self.last_error = None
                return True
            except Exception as e:  # noqa: BLE001 - keep serving; retry on next write
                self.last_error = sanitize(f"{type(e).__name__}: {e}")
                logger.warning("forecast store push failed: %s", self.last_error)
                return False

    def flush(self) -> bool:
        """Push now if a write is pending (used at the end of warmup and in tests)."""
        if self._dirty.is_set():
            self._dirty.clear()
            return self.push()
        return True
