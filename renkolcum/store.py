"""Yerel SQLite deposu: çevrimdışı ölçüm kuyruğu + bulut önbelleği.

İnternet yokken alınan ölçümler burada `synced=0` olarak bekler,
`renkolcum senkron` (veya bir sonraki ölçüm) ile buluta gönderilir.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config


class LocalStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (config.home() / "yerel.db")
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            create table if not exists outbox (
                client_uuid text primary key,
                kind        text not null,          -- measurement | recipe
                payload     text not null,
                synced      integer not null default 0,
                cloud_id    text,
                error       text,
                created_at  text not null default (datetime('now'))
            );
            create table if not exists cache (
                kind text not null, id text not null, payload text not null,
                primary key (kind, id)
            );
            """
        )

    def enqueue(self, kind: str, client_uuid: str, payload: dict) -> None:
        self.db.execute("insert or replace into outbox (client_uuid, kind, payload) values (?,?,?)",
                        (client_uuid, kind, json.dumps(payload, ensure_ascii=False)))
        self.db.commit()

    def pending(self, kind: str | None = None) -> list[dict]:
        q = "select * from outbox where synced = 0"
        args: tuple = ()
        if kind:
            q += " and kind = ?"
            args = (kind,)
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in self.db.execute(q + " order by created_at", args)]

    def mark_synced(self, client_uuid: str, cloud_id: str | None) -> None:
        self.db.execute("update outbox set synced = 1, cloud_id = ?, error = null where client_uuid = ?",
                        (cloud_id, client_uuid))
        self.db.commit()

    def mark_error(self, client_uuid: str, error: str) -> None:
        self.db.execute("update outbox set error = ? where client_uuid = ?", (error, client_uuid))
        self.db.commit()

    def recent(self, kind: str = "measurement", limit: int = 20) -> list[dict]:
        rows = self.db.execute("select * from outbox where kind = ? order by created_at desc, rowid desc limit ?",
                               (kind, limit))
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in rows]

    def get(self, client_or_cloud_id: str) -> dict | None:
        r = self.db.execute("select * from outbox where client_uuid = ? or cloud_id = ? or client_uuid like ?",
                            (client_or_cloud_id, client_or_cloud_id, client_or_cloud_id + "%")).fetchone()
        return dict(r) | {"payload": json.loads(r["payload"])} if r else None

    def cache_put(self, kind: str, rows: list[dict]) -> None:
        self.db.execute("delete from cache where kind = ?", (kind,))
        self.db.executemany("insert into cache (kind, id, payload) values (?,?,?)",
                            [(kind, str(r["id"]), json.dumps(r, ensure_ascii=False)) for r in rows])
        self.db.commit()

    def cache_get(self, kind: str) -> list[dict]:
        return [json.loads(r["payload"]) for r in self.db.execute("select payload from cache where kind = ?", (kind,))]
