""".mdb köprüsü: mevcut masaüstü uygulamasının Access (.mdb) dosyalarını okuyup buluta gönderir.

Uygulamanın kaynak koduna dokunulmaz, .mdb dosyalarına YAZILMAZ:
  1. Klasördeki .mdb dosyaları izlenir (değişiklik tarihi + boyut).
  2. Değişen dosya, yazma işlemi bitene kadar beklenir, sonra geçici bir kopyası alınır
     (uygulamanın açık tuttuğu dosya kilitlenmez).
  3. Kopyadan eşleme dosyasındaki (esleme.json) tablo/alanlar okunur.
  4. Her satır için sabit bir kimlik (UUID5) üretilir -> aynı satır iki kez gönderilmez.
     Satır sonradan değişirse (ör. analiz sonucu sonradan yazıldıysa) bulutta güncellenir.
  5. Kayıtlar yerel kuyruğa yazılır, internet varsa buluta gönderilir.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .colorimetry import WAVELENGTHS, reflectance_to_lab, validate_reflectance
from .store import LocalStore

log = logging.getLogger("renkolcum.kopru")

NAMESPACE = uuid.UUID("6f1c1d1e-6a0b-4e0e-9a51-7c2d5b1e0a11")


# ====================================================================
# Okuyucular
# ====================================================================
class MdbReader:
    def tables(self) -> list[str]: ...
    def rows(self, table: str) -> list[dict[str, Any]]: ...
    def close(self) -> None: ...


class ParserReader(MdbReader):
    """Saf Python okuyucu (access-parser). Sürücü kurulumu gerektirmez; şifreli dosyaları okuyamaz."""

    def __init__(self, path: Path):
        from access_parser import AccessParser
        self.db = AccessParser(str(path))

    def tables(self) -> list[str]:
        return [t for t in self.db.catalog if not t.startswith(("MSys", "f_"))]

    def rows(self, table: str) -> list[dict[str, Any]]:
        cols = self.db.parse_table(table)
        n = max((len(v) for v in cols.values()), default=0)
        return [{k: (v[i] if i < len(v) else None) for k, v in cols.items()} for i in range(n)]

    def close(self) -> None:
        pass


class OdbcReader(MdbReader):
    """Windows Access ODBC sürücüsü (Microsoft Access Database Engine). Şifreli dosyaları da okur."""

    DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"

    def __init__(self, path: Path, password: str | None = None):
        import pyodbc
        cs = f"DRIVER={{{self.DRIVER}}};DBQ={path};ReadOnly=1;Exclusive=0;"
        if password:
            cs += f"PWD={password};"
        self.conn = pyodbc.connect(cs, readonly=True, autocommit=True)

    @classmethod
    def available(cls) -> bool:
        try:
            import pyodbc
        except ImportError:
            return False
        return cls.DRIVER in pyodbc.drivers()

    def tables(self) -> list[str]:
        return [r.table_name for r in self.conn.cursor().tables(tableType="TABLE")]

    def rows(self, table: str) -> list[dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM [{table}]")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()


def open_reader(path: Path, kind: str = "auto", password: str | None = None) -> MdbReader:
    if kind == "odbc" or (kind == "auto" and (password or OdbcReader.available())):
        return OdbcReader(path, password)
    return ParserReader(path)


# ====================================================================
# Yardımcılar
# ====================================================================
def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _nm_of(col: str) -> int | None:
    m = re.search(r"(?<!\d)(3[6-9]\d|[4-7]\d\d)(?!\d)", col)
    return int(m.group(1)) if m else None


def resample(spec: dict[int, float]) -> list[float]:
    """Dalga boyu -> değer sözlüğünü 360-740 nm / 10 nm ızgarasına (doğrusal) çevirir."""
    if not spec:
        raise ValueError("Spektral veri yok")
    xs = sorted(spec)
    out = []
    for w in WAVELENGTHS:
        if w in spec:
            out.append(spec[w])
        elif w <= xs[0]:
            out.append(spec[xs[0]])
        elif w >= xs[-1]:
            out.append(spec[xs[-1]])
        else:
            hi = next(x for x in xs if x > w)
            lo = max(x for x in xs if x < w)
            out.append(spec[lo] + (spec[hi] - spec[lo]) * (w - lo) / (hi - lo))
    return out


def _parse_time(v: Any, tz: str) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        t = v
    else:
        s = str(v).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                    "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                t = dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if t.tzinfo is None:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo(tz))
    return t.isoformat()


_PASS = {"GEÇTİ", "GECTI", "OK", "PASS", "1", "TRUE", "EVET", "E", "-1"}
_FAIL = {"KALDI", "RED", "FAIL", "0", "FALSE", "HAYIR", "H"}


def _pass_fail(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    return "GEÇTİ" if s in _PASS else "KALDI" if s in _FAIL else None


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return f"<{len(v)} bayt>"
    return str(v)


# ====================================================================
# Eşleme (esleme.json)
# ====================================================================
@dataclass
class Mapping:
    tablo: str
    anahtar: list[str]
    alanlar: dict[str, str]
    spektrum: dict
    olcek: float = 1.0
    saat_dilimi: str = "Europe/Istanbul"
    kaynak: str = ""              # bu bilgisayar/lab için ön ek (farklı lab'larda aynı ID çakışmasın)

    @classmethod
    def load(cls, path: Path) -> "Mapping":
        d = json.loads(Path(path).read_text("utf-8"))
        d = {k: v for k, v in d.items() if not k.startswith("_")}
        if isinstance(d.get("anahtar"), str):
            d["anahtar"] = [d["anahtar"]]
        return cls(**d)

    def dump(self) -> dict:
        return {
            "_aciklama": "renkolcum mdb-kesfet ile üretildi. Alan adlarını uygulamanızın .mdb yapısına göre kontrol edin.",
            "tablo": self.tablo, "anahtar": self.anahtar, "alanlar": self.alanlar, "spektrum": self.spektrum,
            "olcek": self.olcek, "saat_dilimi": self.saat_dilimi, "kaynak": self.kaynak,
        }


FIELD_PATTERNS = {
    "sample_name": r"^(numune|numune_?ad[ıi]?|sample|sample_?name|ad[ıi]?|name|parti|lot|kod|renk_?ad[ıi]?)$",
    "measured_at": r"(tarih|date|zaman|time)",
    "operator_name": r"(operat|kullan|user|olcen)",
    "l_star": r"^(l|l\*|lstar|l_star|l_deg(er)?i?|cie_?l)$",
    "a_star": r"^(a|a\*|astar|a_star|a_deg(er)?i?|cie_?a)$",
    "b_star": r"^(b|b\*|bstar|b_star|b_deg(er)?i?|cie_?b)$",
    "delta_e2000": r"(de2000|de_?00|dE00|delta_?e|^de$|^dE$)",
    "pass_fail": r"(sonuc|result|durum|pass|onay)",
    "standard_name": r"(standart|standard|referans|hedef|target)",
}


def discover(reader: MdbReader) -> tuple[Mapping | None, list[dict]]:
    """Tabloları tarar, spektral veriyi ve alanları otomatik bulmaya çalışır."""
    report, best = [], None
    data = {}
    for t in reader.tables():
        try:
            rows = reader.rows(t)
        except Exception as e:  # noqa: BLE001
            report.append({"tablo": t, "hata": str(e)})
            continue
        cols = list(rows[0].keys()) if rows else []
        data[t] = (rows, cols)
        report.append({"tablo": t, "satir": len(rows), "kolonlar": cols, "ornek": {k: _jsonable(v) for k, v in (rows[0] if rows else {}).items()}})

    def match_fields(cols):
        out = {}
        for field, pat in FIELD_PATTERNS.items():
            for c in cols:
                if c not in out.values() and re.search(pat, c, re.I):
                    out[field] = c
                    break
        return out

    # 1) Geniş format: bir tabloda dalga boyu adlı en az 16 kolon
    for t, (rows, cols) in data.items():
        wl_cols = {c: _nm_of(c) for c in cols}
        wl_cols = {c: n for c, n in wl_cols.items() if n is not None and n % 10 == 0}
        if len(wl_cols) >= 16:
            key = next((c for c in cols if re.search(r"(^id$|_no$|^no$|olcum_?id|kayit)", c, re.I)), cols[0])
            fields = match_fields([c for c in cols if c not in wl_cols and c != key])
            best = Mapping(t, [key], fields, {"tip": "genis", "kolonlar": {str(n): c for c, n in sorted(wl_cols.items(), key=lambda kv: kv[1])}})
            break
    # 2) Uzun format: (ölçüm no, dalga boyu, değer) satırları
    if best is None:
        for t, (rows, cols) in data.items():
            for c in cols:
                vals = {_num(r[c]) for r in rows[:200]}
                if len(vals) >= 16 and all(v is not None and 360 <= v <= 780 for v in vals):
                    others = [x for x in cols if x != c]
                    num_cols = [x for x in others if all(_num(r[x]) is not None for r in rows[:50])]
                    link = next((x for x in others if re.search(r"(id|no)$", x, re.I)), others[0])
                    val = next((x for x in num_cols if x != link), None)
                    main = next((mt for mt, (mr, mc) in data.items() if mt != t and link in mc), None)
                    if val and main:
                        mcols = data[main][1]
                        fields = match_fields([x for x in mcols if x != link])
                        best = Mapping(main, [link], fields, {"tip": "uzun", "tablo": t, "baglanti": link, "dalga": c, "deger": val})
                    break
            if best:
                break
    # Ölçek: değerler 0-1 arasındaysa %'ye çevir
    if best is not None:
        sample_vals = []
        if best.spektrum["tip"] == "genis":
            for r in data[best.tablo][0][:20]:
                sample_vals += [_num(r[c]) for c in best.spektrum["kolonlar"].values()]
        else:
            sample_vals = [_num(r[best.spektrum["deger"]]) for r in data[best.spektrum["tablo"]][0][:200]]
        sample_vals = [v for v in sample_vals if v is not None]
        if sample_vals and max(sample_vals) <= 1.5:
            best.olcek = 100.0
    return best, report


# ====================================================================
# Satır -> ölçüm kaydı
# ====================================================================
def extract_measurements(reader: MdbReader, m: Mapping, file_name: str) -> list[dict]:
    rows = reader.rows(m.tablo)
    spectra: dict[str, dict[int, float]] = {}
    if m.spektrum["tip"] == "uzun":
        s = m.spektrum
        for r in reader.rows(s["tablo"]):
            k, w, v = r.get(s["baglanti"]), _num(r.get(s["dalga"])), _num(r.get(s["deger"]))
            if k is not None and w is not None and v is not None:
                spectra.setdefault(str(k), {})[int(round(w))] = v * m.olcek

    used = set(m.alanlar.values()) | set(m.anahtar)
    if m.spektrum["tip"] == "genis":
        used |= set(m.spektrum["kolonlar"].values())
    elif m.spektrum["tip"] == "metin":
        used.add(m.spektrum["kolon"])

    out = []
    for r in rows:
        key_vals = [str(r.get(k)) for k in m.anahtar]
        key = "|".join(key_vals)
        ident = f"{m.kaynak}|{file_name}|{m.tablo}|{key}"
        item = {"_kimlik": str(uuid.uuid5(NAMESPACE, ident)), "_anahtar": key, "_hata": None}
        try:
            if m.spektrum["tip"] == "genis":
                spec = {int(nm): _num(r.get(col)) for nm, col in m.spektrum["kolonlar"].items()}
                spec = {k: v * m.olcek for k, v in spec.items() if v is not None}
            elif m.spektrum["tip"] == "uzun":
                spec = spectra.get(str(r.get(m.spektrum["baglanti"])), {})
            elif m.spektrum["tip"] == "metin":
                vals = [_num(x) for x in re.split(m.spektrum.get("ayirac", r"[;\s]+"), str(r.get(m.spektrum["kolon"]) or "").strip()) if x]
                start, step = m.spektrum.get("baslangic", 360), m.spektrum.get("adim", 10)
                spec = {start + i * step: v * m.olcek for i, v in enumerate(vals) if v is not None}
            else:
                raise ValueError(f"Bilinmeyen spektrum tipi: {m.spektrum['tip']}")
            if len(spec) < 8:
                raise ValueError(f"Spektral veri eksik ({len(spec)} nokta)")
            refl = [round(v, 4) for v in validate_reflectance(resample(spec))]
        except ValueError as e:
            item["_hata"] = str(e)
            out.append(item)
            continue

        f = m.alanlar
        lab_app = [_num(r.get(f[k])) if k in f else None for k in ("l_star", "a_star", "b_star")]
        if all(v is not None for v in lab_app):
            lab, src = lab_app, "uygulama"
        else:
            lab, src = list(reflectance_to_lab(refl)), "renkolcum"
        name = r.get(f["sample_name"]) if "sample_name" in f else None
        item.update({
            "client_uuid": item["_kimlik"],
            "sample_name": str(name).strip() if name not in (None, "") else f"{file_name} #{key}",
            "reflectance": refl,
            "l_star": round(lab[0], 4), "a_star": round(lab[1], 4), "b_star": round(lab[2], 4),
            "delta_e2000": _num(r.get(f["delta_e2000"])) if "delta_e2000" in f else None,
            "pass_fail": _pass_fail(r.get(f["pass_fail"])) if "pass_fail" in f else None,
            "measured_at": _parse_time(r.get(f.get("measured_at", "")), m.saat_dilimi),
            "operator_name": (str(r.get(f["operator_name"])).strip() or None) if r.get(f.get("operator_name", "")) else None,
            "source_ref": f"{file_name}:{m.tablo}:{key}",
            "_standart_adi": r.get(f["standard_name"]) if "standard_name" in f else None,
            "meta": {"lab_kaynagi": src, "kaynak": m.kaynak or None,
                     "ham": {k: _jsonable(v) for k, v in r.items() if k not in used}},
        })
        out.append(item)
    return out


# ====================================================================
# Klasör izleyici
# ====================================================================
class MdbBridge:
    def __init__(self, folder: Path, mapping: Mapping, store: LocalStore, *, standards_lookup=None,
                 reader_kind: str = "auto", password: str | None = None, stable_seconds: float = 3.0,
                 pattern: str = "*.mdb"):
        self.folder = Path(folder)
        self.mapping = mapping
        self.store = store
        self.standards_lookup = standards_lookup or (lambda name: None)
        self.reader_kind = reader_kind
        self.password = password
        self.stable_seconds = stable_seconds
        self.pattern = pattern
        self._seen: dict[str, tuple[float, int, float]] = {}   # dosya -> (mtime, size, ilk_görülme)
        store.db.executescript(
            """
            create table if not exists mdb_files (path text primary key, mtime real, size integer, processed_at text);
            create table if not exists mdb_rows  (client_uuid text primary key, hash text not null, source_ref text);
            """
        )

    # -- dosya değişti mi, yazma bitti mi? --
    def ready_files(self) -> list[Path]:
        ready, now = [], time.time()
        for p in sorted(self.folder.glob(self.pattern)):
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            row = self.store.db.execute("select mtime, size from mdb_files where path = ?", (str(p),)).fetchone()
            if row and row[0] == st.st_mtime and row[1] == st.st_size:
                continue  # zaten işlendi
            prev = self._seen.get(str(p))
            if prev is None or prev[0] != st.st_mtime or prev[1] != st.st_size:
                self._seen[str(p)] = (st.st_mtime, st.st_size, now)  # yeni değişiklik: beklemeye başla
                if self.stable_seconds > 0:
                    continue
            elif now - prev[2] < self.stable_seconds:
                continue
            ready.append(p)
        return ready

    def process_file(self, path: Path) -> dict:
        st = path.stat()
        res = {"dosya": path.name, "yeni": 0, "guncellenen": 0, "ayni": 0, "hatali": 0, "hatalar": []}
        with tempfile.TemporaryDirectory(prefix="renkolcum-") as tmp:
            copy = Path(tmp) / path.name
            shutil.copy2(path, copy)              # uygulamanın dosyasına dokunmadan kopyadan oku
            reader = open_reader(copy, self.reader_kind, self.password)
            try:
                items = extract_measurements(reader, self.mapping, path.name)
            finally:
                reader.close()
        for it in items:
            if it["_hata"]:
                res["hatali"] += 1
                res["hatalar"].append(f"{it['_anahtar']}: {it['_hata']}")
                continue
            std_name = it.pop("_standart_adi", None)
            std = self.standards_lookup(str(std_name)) if std_name else None
            if std:
                it["standard_id"] = std["id"]
            elif std_name:
                it["meta"]["standart_adi"] = str(std_name)
            payload = {k: v for k, v in it.items() if not k.startswith("_") and v is not None}
            h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            cu = payload["client_uuid"]
            prev = self.store.db.execute("select hash from mdb_rows where client_uuid = ?", (cu,)).fetchone()
            if prev and prev[0] == h:
                res["ayni"] += 1
                continue
            existing = self.store.get(cu)
            if prev is None and existing is None:
                self.store.enqueue("measurement", cu, payload)
                res["yeni"] += 1
            elif existing and not existing["synced"]:
                self.store.enqueue("measurement", cu, payload)    # henüz gitmemiş: kuyruktakini yenile
                res["guncellenen"] += 1
            else:
                upd = {k: v for k, v in payload.items() if k not in ("client_uuid",)}
                self.store.enqueue("measurement_update", f"{cu}:{h[:12]}", {"client_uuid": cu, "values": upd})
                res["guncellenen"] += 1
            self.store.db.execute("insert or replace into mdb_rows (client_uuid, hash, source_ref) values (?,?,?)",
                                  (cu, h, payload.get("source_ref")))
        self.store.db.execute("insert or replace into mdb_files (path, mtime, size, processed_at) values (?,?,?,datetime('now'))",
                              (str(path), st.st_mtime, st.st_size))
        self.store.db.commit()
        self._seen.pop(str(path), None)
        return res

    def scan_once(self) -> list[dict]:
        results = []
        for p in self.ready_files():
            try:
                r = self.process_file(p)
            except Exception as e:  # noqa: BLE001 — dosya yarım yazılmış olabilir, sonra tekrar denenir
                log.warning("%s okunamadı (sonra tekrar denenecek): %s", p.name, e)
                self._seen.pop(str(p), None)
                results.append({"dosya": p.name, "okuma_hatasi": str(e)})
                continue
            log.info("%s: yeni=%d güncellenen=%d aynı=%d hatalı=%d", p.name, r["yeni"], r["guncellenen"], r["ayni"], r["hatali"])
            for h in r["hatalar"][:5]:
                log.warning("  %s", h)
            results.append(r)
        return results
