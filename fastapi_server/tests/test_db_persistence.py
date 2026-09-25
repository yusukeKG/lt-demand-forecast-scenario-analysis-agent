"""DBCtx with a persisted SQLite file (deployed apps sync it via the Files API)."""

import asyncio
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import DBCtx


class SnapshotFS:
    """Stands in for DRFileSystem: get() restores the last put() snapshot."""

    def __init__(self, snapshot: Path) -> None:
        self.snapshot = snapshot

    def exists(self, path: str) -> bool:
        return self.snapshot.exists()

    def get(self, remote: str, local: str) -> None:
        shutil.copyfile(self.snapshot, local)

    def put(self, local: str, remote: str) -> None:
        shutil.copyfile(local, self.snapshot)


async def test_read_during_write_does_not_restore_stale_copy(tmp_path: Path) -> None:
    db_path = tmp_path / "database.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
    db = DBCtx(engine)
    fs = SnapshotFS(tmp_path / "remote.sqlite")
    fs.put(str(db_path), "")
    db._persistence_fs, db._db_path, db._lock = fs, str(db_path), asyncio.Lock()  # type: ignore[assignment]

    async def poll() -> None:  # e.g. an authenticated GET looking up the user
        async with db.session() as s:
            await s.execute(text("SELECT 1"))

    async with db.session(writable=True) as session:
        await session.execute(text("INSERT INTO t (id) VALUES (1)"))
        await db.commit(session)
        reader = asyncio.create_task(poll())
        await asyncio.sleep(0.2)  # the read runs between commit and refresh
        rows = [
            tuple(r) for r in (await session.execute(text("SELECT id FROM t"))).all()
        ]
        assert rows == [(1,)]
    await reader

    async with db.session() as s:
        assert [
            tuple(r) for r in (await s.execute(text("SELECT id FROM t"))).all()
        ] == [(1,)]
    await engine.dispose()
