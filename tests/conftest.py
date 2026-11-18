import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def renkolcum_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RENKOLCUM_HOME", str(tmp_path / "home"))
    for k in ("RENKOLCUM_SUPABASE_URL", "RENKOLCUM_SUPABASE_ANON_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path / "home"


def _pg_bin():
    found = sorted(Path("/usr/lib/postgresql").glob("*/bin")) if Path("/usr/lib/postgresql").exists() else []
    if found:
        return found[-1]
    w = shutil.which("initdb")
    return Path(w).parent if w else None


@pytest.fixture(scope="session")
def pg_dsn():
    """Geçici PostgreSQL + stub auth + migration + seed."""
    pytest.importorskip("psycopg")
    pgbin = _pg_bin()
    if not pgbin:
        pytest.skip("PostgreSQL (initdb) bulunamadı")
    tmp = tempfile.mkdtemp(prefix="renkpg-")
    runas = []
    if os.geteuid() == 0:
        shutil.chown(tmp, "postgres")
        runas = ["runuser", "-u", "postgres", "--"]
    data = f"{tmp}/data"
    port = "54331"
    subprocess.run(runas + [str(pgbin / "initdb"), "-D", data, "-U", "postgres", "-A", "trust"],
                   check=True, capture_output=True)
    subprocess.run(runas + [str(pgbin / "pg_ctl"), "-D", data, "-o", f"-p {port} -k {tmp} -c listen_addresses=''",
                            "-l", f"{tmp}/log", "-w", "start"], check=True, capture_output=True)
    dsn = f"host={tmp} port={port} user=postgres dbname=postgres"
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute((ROOT / "supabase/tests/supabase_stub.sql").read_text())
        for f in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            c.execute(f.read_text())
        c.execute((ROOT / "supabase/seed.sql").read_text())
    yield dsn
    subprocess.run(runas + [str(pgbin / "pg_ctl"), "-D", data, "-m", "immediate", "stop"], capture_output=True)
    time.sleep(0.2)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def fake_cloud(pg_dsn):
    from tests.fake_supabase import FakeSupabase
    fs = FakeSupabase(pg_dsn)
    fs.create_user("admin@demo.local", "Admin123!", {"full_name": "Ayşe Admin"})
    fs.create_user("op1@demo.local", "Op123!", {"full_name": "Mehmet Operatör"})
    fs.create_user("op2@demo.local", "Op123!", {"full_name": "Zeynep Operatör"})
    fs.create_user("izleyici@demo.local", "View123!", {"full_name": "Can İzleyici", "role": "viewer"})
    yield fs
    fs.stop()
