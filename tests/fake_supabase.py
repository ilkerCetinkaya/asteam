"""Test amaçlı mini 'Supabase': Auth (password/refresh) + PostgREST alt kümesi.

Arkada gerçek PostgreSQL çalışır; her istek `authenticated` rolüyle ve
`request.jwt.claim.sub` ayarıyla yürütülür, yani RLS politikaları gerçekten test edilir.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

import psycopg
from psycopg import sql

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class FakeSupabase:
    def __init__(self, dsn: str, anon_key: str = "anon-test-key"):
        self.dsn = dsn
        self.anon_key = anon_key
        self.users: dict[str, tuple[str, str]] = {}   # email -> (password, uid)
        self.tokens: dict[str, str] = {}              # token -> uid
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def create_user(self, email: str, password: str, meta: dict | None = None) -> str:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            uid = c.execute("insert into auth.users (email, raw_user_meta_data) values (%s, %s) returning id",
                            (email, json.dumps(meta or {}))).fetchone()[0]
        self.users[email] = (password, str(uid))
        return str(uid)

    def expire_all_tokens(self) -> None:
        self.tokens.clear()

    def stop(self) -> None:
        self.server.shutdown()

    # ------------------------------------------------------------------
    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body=None):
                data = b"" if body is None else json.dumps(body, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n)) if n else None

            def _route(self, method: str):
                u = urlparse(self.path)
                q = parse_qsl(u.query)
                if self.headers.get("apikey") != fake.anon_key:
                    return self._send(401, {"message": "Invalid API key"})
                if u.path == "/auth/v1/token":
                    return self._token(dict(q).get("grant_type"), self._body())
                if u.path == "/auth/v1/logout":
                    return self._send(204)
                m = re.match(r"^/rest/v1/([a-z_]+)$", u.path)
                if not m:
                    return self._send(404, {"message": "not found"})
                auth = self.headers.get("Authorization", "")
                uid = fake.tokens.get(auth.removeprefix("Bearer "))
                if not uid:
                    return self._send(401, {"message": "JWT expired"})
                try:
                    return self._rest(method, m.group(1), q, uid)
                except psycopg.errors.InsufficientPrivilege as e:
                    return self._send(403, {"message": str(e).splitlines()[0]})
                except psycopg.Error as e:
                    return self._send(400, {"message": str(e).splitlines()[0]})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PATCH(self):
                self._route("PATCH")

            def _token(self, grant, body):
                if grant == "password":
                    rec = fake.users.get(body.get("email"))
                    if not rec or rec[0] != body.get("password"):
                        return self._send(400, {"error_description": "Invalid login credentials"})
                    uid = rec[1]
                elif grant == "refresh_token":
                    uid = body.get("refresh_token", "").removeprefix("rt-")
                    if uid not in {u for _, u in fake.users.values()}:
                        return self._send(400, {"error_description": "Invalid Refresh Token"})
                else:
                    return self._send(400, {"error_description": "bad grant"})
                tok = "at-" + uuid.uuid4().hex
                fake.tokens[tok] = uid
                email = next(e for e, (_, u) in fake.users.items() if u == uid)
                return self._send(200, {"access_token": tok, "refresh_token": "rt-" + uid, "expires_in": 3600,
                                        "user": {"id": uid, "email": email}})

            def _rest(self, method, table, q, uid):
                params = [(k, v) for k, v in q if k not in ("select", "order", "limit", "on_conflict")]
                opts = dict(q)
                where, args = [], []
                for k, v in params:
                    assert IDENT.match(k), k
                    op, _, val = v.partition(".")
                    assert op == "eq", op
                    where.append(sql.SQL("{} = %s").format(sql.Identifier(k)))
                    args.append(val)
                where_sql = sql.SQL(" where ") + sql.SQL(" and ").join(where) if where else sql.SQL("")
                with psycopg.connect(fake.dsn) as c:
                    c.execute("set local role authenticated")
                    c.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid,))
                    if method == "GET":
                        cols = opts.get("select", "*")
                        col_sql = sql.SQL("*") if cols == "*" else sql.SQL(", ").join(
                            sql.Identifier(x) for x in cols.split(","))
                        order = sql.SQL("")
                        if "order" in opts:
                            col, _, d = opts["order"].partition(".")
                            order = sql.SQL(" order by {} {}").format(sql.Identifier(col),
                                                                       sql.SQL("desc" if d == "desc" else "asc"))
                        limit = sql.SQL(" limit {}").format(sql.Literal(int(opts["limit"]))) if "limit" in opts else sql.SQL("")
                        inner = sql.SQL("select {} from public.{}").format(col_sql, sql.Identifier(table)) + where_sql + order + limit
                        rows = c.execute(sql.SQL("select coalesce(json_agg(t), '[]') from (") + inner + sql.SQL(") t"),
                                         args).fetchone()[0]
                        return self._send(200, rows)
                    body = self._body()
                    if method == "POST":
                        rows_in = body if isinstance(body, list) else [body]
                        out = []
                        for r in rows_in:
                            keys = list(r)
                            ins = sql.SQL("insert into public.{} ({}) select {} from json_populate_record(null::public.{}, %s)").format(
                                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, keys)),
                                sql.SQL(", ").join(map(sql.Identifier, keys)), sql.Identifier(table))
                            if "on_conflict" in opts and "ignore-duplicates" in self.headers.get("Prefer", ""):
                                ins += sql.SQL(" on conflict ({}) do nothing").format(sql.Identifier(opts["on_conflict"]))
                            ins += sql.SQL(" returning row_to_json({}.*)").format(sql.Identifier(table))
                            res = c.execute(ins, (json.dumps(r),)).fetchone()
                            if res:
                                out.append(res[0])
                        return self._send(201, out)
                    if method == "PATCH":
                        sets = sql.SQL(", ").join(sql.SQL("{} = (json_populate_record(null::public.{}, %s)).{}").format(
                            sql.Identifier(k), sql.Identifier(table), sql.Identifier(k)) for k in body)
                        upd = sql.SQL("update public.{} set ").format(sql.Identifier(table)) + sets + where_sql + \
                            sql.SQL(" returning row_to_json({}.*)").format(sql.Identifier(table))
                        rows = [r[0] for r in c.execute(upd, [json.dumps(body)] * len(body) + args).fetchall()]
                        return self._send(200, rows)

        return H
