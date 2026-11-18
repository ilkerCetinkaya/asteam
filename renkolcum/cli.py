"""`renkolcum` komut satırı arayüzü (Renk Ölçüm Sistemi — dummy)."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

import requests

from . import __version__, config
from .cloud import CloudError, SupabaseClient
from .colorimetry import lab_to_lch, lab_to_srgb
from .spectro import SAMPLE_LIBRARY, SimulatedSpectrophotometer, parse_device_csv, to_device_csv
from .store import LocalStore
from .service import RenkOlcumService

_SPARK = "▁▂▃▄▅▆▇█"


def swatch(lab) -> str:
    r, g, b = lab_to_srgb(lab)
    if not sys.stdout.isatty() and not os.environ.get("FORCE_COLOR"):
        return f"[RGB {r},{g},{b}]"
    return f"\x1b[48;2;{r};{g};{b}m        \x1b[0m"


def sparkline(refl) -> str:
    return "".join(_SPARK[min(int(v / 100 * len(_SPARK)), len(_SPARK) - 1)] for v in refl)


def build_service() -> RenkOlcumService:
    cfg = config.load_config()
    cloud = None
    if cfg["supabase_url"] and cfg["supabase_anon_key"]:
        cloud = SupabaseClient(cfg["supabase_url"], cfg["supabase_anon_key"], config.load_session())
    return RenkOlcumService(LocalStore(), cloud)


def print_measurement(p: dict) -> None:
    L, C, h = lab_to_lch((p["l_star"], p["a_star"], p["b_star"]))
    print(f"  Numune : {p['sample_name']}")
    print(f"  Renk   : {swatch((p['l_star'], p['a_star'], p['b_star']))}")
    print(f"  L*a*b* : L={p['l_star']:.2f}  a={p['a_star']:.2f}  b={p['b_star']:.2f}   (C={C:.2f}, h={h:.1f}°)  D65/10°")
    print(f"  Spektrum 360→740 nm: {sparkline(p['reflectance'])}")
    if p.get("delta_e2000") is not None:
        print(f"  ΔE2000 (standarda göre): {p['delta_e2000']:.2f}  →  {p['pass_fail']}")


def try_sync(svc: RenkOlcumService, quiet: bool = False) -> None:
    if not svc.cloud_ready():
        if not quiet:
            print("  ☁  Bulut oturumu yok → ölçüm yerelde kuyruğa alındı (renkolcum giris / senkron).")
        return
    try:
        r = svc.sync()
    except CloudError as e:
        print(f"  ☁  Senkron hatası: {e}")
        return
    msg = f"  ☁  Buluta gönderildi: {r['gonderilen']}"
    if r["bekleyen"]:
        msg += f"  | bekleyen: {r['bekleyen']} (çevrimdışı olabilir)"
    print(msg)


# ---------------- komutlar ----------------

def cmd_ayar(a) -> None:
    cfg = config.load_config()
    if a.url:
        cfg["supabase_url"] = a.url.rstrip("/")
    if a.anahtar:
        cfg["supabase_anon_key"] = a.anahtar
    if a.cihaz_seri:
        cfg["instrument_serial"] = a.cihaz_seri
    config.save_config(cfg)
    print(f"Ayarlar kaydedildi: {config.home() / 'config.json'}")
    print(f"  Supabase URL : {cfg['supabase_url'] or '-'}")
    print(f"  Anahtar      : {'✔' if cfg['supabase_anon_key'] else '-'}")
    print(f"  Cihaz seri   : {cfg['instrument_serial']}")


def cmd_giris(a) -> None:
    svc = build_service()
    if svc.cloud is None:
        sys.exit("Önce bulut ayarını yapın: renkolcum ayar --url https://xxxx.supabase.co --anahtar <anon key>")
    email = a.email or input("E-posta: ")
    pw = os.environ.get("RENKOLCUM_PASSWORD") or getpass.getpass("Şifre: ")
    try:
        svc.cloud.login(email, pw)
        me = svc.cloud.me()
    except (CloudError, requests.RequestException) as e:
        sys.exit(str(e))
    if not me:
        sys.exit("Giriş yapıldı ama profil bulunamadı (kullanıcı limiti dolmuş olabilir).")
    print(f"Hoş geldiniz {me['full_name']} ({me['role']}).")
    svc.standards()
    svc.colorants()
    try_sync(svc, quiet=True)


def cmd_cikis(a) -> None:
    svc = build_service()
    if svc.cloud:
        svc.cloud.logout()
    print("Çıkış yapıldı.")


def cmd_durum(a) -> None:
    cfg = config.load_config()
    svc = build_service()
    sess = config.load_session()
    print(f"Renk Ölçüm Sistemi v{__version__}")
    print(f"  Veri klasörü : {config.home()}")
    print(f"  Bulut        : {cfg['supabase_url'] or 'yapılandırılmamış'}")
    print(f"  Kullanıcı    : {sess.get('email', 'giriş yapılmamış')}")
    print(f"  Bekleyen     : {len(svc.store.pending())} kayıt")


def _device() -> SimulatedSpectrophotometer:
    return SimulatedSpectrophotometer(serial=config.load_config()["instrument_serial"])


def cmd_cihaz(a) -> None:
    info = _device().detect()
    print("Spektrofotometre algılandı:")
    for k, v in info.items():
        print(f"  {k:9}: {v}")


def _standard(svc, key):
    if not key:
        return None
    st = svc.find_standard(key)
    if not st:
        sys.exit(f"Standart bulunamadı: {key}  (liste: renkolcum standartlar)")
    return st


def cmd_olc(a) -> None:
    svc = build_service()
    st = _standard(svc, a.standart)
    dev = _device()
    reading = dev.measure(a.numune)
    name = a.ad or f"Numune {time.strftime('%Y%m%d-%H%M%S')}"
    p = svc.record_measurement(reading, name, st)
    print(f"Ölçüm alındı ({reading.instrument_model} / {reading.instrument_serial})  id={p['client_uuid'][:8]}")
    print_measurement(p)
    if a.csv_cikti:
        Path(a.csv_cikti).write_text(to_device_csv(reading, name), "utf-8")
        print(f"  CSV yazıldı: {a.csv_cikti}")
    try_sync(svc)


def ingest_file(svc: RenkOlcumService, path: Path, standard=None) -> dict:
    name, reading = parse_device_csv(path.read_text("utf-8"))
    return svc.record_measurement(reading, name or path.stem, standard)


def cmd_izle(a) -> None:
    folder = Path(a.klasor)
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "islenen"
    done.mkdir(exist_ok=True)
    svc = build_service()
    st = _standard(svc, a.standart)
    print(f"Klasör izleniyor: {folder.resolve()}  (cihazın CSV dışa aktarımları otomatik algılanır, Ctrl+C ile çıkış)")
    try:
        while True:
            for f in sorted(folder.glob("*.csv")):
                try:
                    p = ingest_file(svc, f, st)
                    print(f"\n● Yeni ölçüm algılandı: {f.name}")
                    print_measurement(p)
                    f.rename(done / f.name)
                except ValueError as e:
                    print(f"✖ {f.name}: {e}")
                    f.rename(f.with_suffix(".hatali"))
                try_sync(svc, quiet=True)
            if a.tek_sefer:
                break
            time.sleep(a.aralik)
    except KeyboardInterrupt:
        print("\nİzleme durduruldu.")


def cmd_senkron(a) -> None:
    svc = build_service()
    if not svc.cloud_ready():
        sys.exit("Bulut oturumu yok: renkolcum giris")
    r = svc.sync()
    print(f"Gönderilen: {r['gonderilen']}  Hata: {r['hata']}  Bekleyen: {r['bekleyen']}")


def cmd_listele(a) -> None:
    svc = build_service()
    if a.bulut:
        if not svc.cloud_ready():
            sys.exit("Bulut oturumu yok: renkolcum giris")
        rows = svc.cloud.select("measurements_view", order="measured_at.desc", limit=str(a.n))
        print(f"{'ID':8}  {'Tarih':19}  {'Numune':24} {'L*':>6} {'a*':>6} {'b*':>6} {'ΔE00':>5}  Kullanıcı")
        for r in rows:
            de = f"{r['delta_e2000']:.2f}" if r.get("delta_e2000") is not None else "-"
            print(f"{r['id'][:8]}  {r['measured_at'][:19]}  {r['sample_name'][:24]:24} {r['l_star']:6.1f} "
                  f"{r['a_star']:6.1f} {r['b_star']:6.1f} {de:>5}  {r.get('measured_by_name') or ''}")
        return
    print(f"{'ID':8}  {'Durum':8}  {'Numune':24} {'L*':>6} {'a*':>6} {'b*':>6}  Renk")
    for r in svc.store.recent("measurement", a.n):
        p = r["payload"]
        durum = "☁ bulut" if r["synced"] else "bekliyor"
        print(f"{p['client_uuid'][:8]}  {durum:8}  {p['sample_name'][:24]:24} {p['l_star']:6.1f} {p['a_star']:6.1f} "
              f"{p['b_star']:6.1f}  {swatch((p['l_star'], p['a_star'], p['b_star']))}")


def cmd_recete(a) -> None:
    svc = build_service()
    if a.olcum == "son":
        recent = svc.store.recent("measurement", 1)
        entry = recent[0] if recent else None
    else:
        entry = svc.store.get(a.olcum)
    if not entry or entry["kind"] != "measurement":
        sys.exit("Ölçüm bulunamadı (renkolcum listele ile ID'ye bakın)")
    p = entry["payload"]
    target = p
    if a.standarda_gore and p.get("standard_id"):
        st = next((s for s in svc.standards() if s["id"] == p["standard_id"]), None)
        if st:
            target = st
    print(f"Hedef: {target.get('sample_name') or target.get('name')}  {swatch((target['l_star'], target['a_star'], target['b_star']))}")
    res = svc.make_recipe(target)
    cols = {c.code: c for c in svc.colorants()}
    print("Önerilen reçete:")
    for row in res.as_rows(cols):
        print(f"  {row['colorant_code']:4} {row['colorant_name']:10} %{row['amount_pct']:.4f}")
    if not res.components:
        print("  (boyarmadde gerekmiyor — zemin rengi)")
    L, A, B = res.predicted_lab
    print(f"Tahmini sonuç: L={L:.2f} a={A:.2f} b={B:.2f}   ΔE2000={res.delta_e2000:.3f}  {swatch(res.predicted_lab)}")
    if not a.kaydetme:
        svc.record_recipe({"payload": p}, res, a.ad)
        print("Reçete kaydedildi.")
        try_sync(svc)


def cmd_standartlar(a) -> None:
    svc = build_service()
    rows = svc.standards()
    if not rows:
        print("Standart yok (buluta giriş yapın ya da `renkolcum standart-ekle` kullanın).")
    for s in rows:
        print(f"{s['id'][:8]}  {s['name']:24} {s.get('customer') or '':18} L={s['l_star']:.1f} a={s['a_star']:.1f} "
              f"b={s['b_star']:.1f}  tol ΔE={s.get('tolerance_de', 1.0)}  {swatch((s['l_star'], s['a_star'], s['b_star']))}")


def cmd_standart_ekle(a) -> None:
    svc = build_service()
    if not svc.cloud_ready():
        sys.exit("Standart eklemek için bulut oturumu gerekli: renkolcum giris")
    entry = svc.store.get(a.olcum) if a.olcum != "son" else (svc.store.recent("measurement", 1) or [None])[0]
    if not entry:
        sys.exit("Ölçüm bulunamadı")
    p = entry["payload"]
    row = svc.cloud.insert("standards", {
        "name": a.ad, "customer": a.musteri, "reflectance": p["reflectance"],
        "l_star": p["l_star"], "a_star": p["a_star"], "b_star": p["b_star"], "tolerance_de": a.tolerans,
    })[0]
    svc.standards()
    print(f"Standart eklendi: {row['name']} ({row['id'][:8]})")


def _setup_logging(verbose: bool = True) -> None:
    import logging
    from logging.handlers import RotatingFileHandler
    root = logging.getLogger("renkolcum")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(config.home() / "kopru.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(fh)
    if verbose and sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root.addHandler(sh)


def cmd_mdb_kesfet(a) -> None:
    import json
    from .mdb_bridge import discover, open_reader
    reader = open_reader(Path(a.dosya), a.okuyucu, a.sifre)
    try:
        mapping, report = discover(reader)
    finally:
        reader.close()
    print(f"Dosya: {a.dosya}")
    for t in report:
        if "hata" in t:
            print(f"\n▸ {t['tablo']}: okunamadı ({t['hata']})")
            continue
        print(f"\n▸ Tablo {t['tablo']}  ({t['satir']} satır, {len(t['kolonlar'])} kolon)")
        cols = t["kolonlar"]
        print("  Kolonlar: " + ", ".join(cols[:25]) + (f" … (+{len(cols) - 25})" if len(cols) > 25 else ""))
        if t["ornek"]:
            ex = list(t["ornek"].items())[:12]
            print("  Örnek  : " + "; ".join(f"{k}={v}" for k, v in ex))
    if mapping is None:
        print("\n✖ Spektral veri otomatik bulunamadı. esleme.json dosyasını elle hazırlayın (README → .mdb köprüsü).")
        return
    print(f"\n✔ Önerilen eşleme: tablo={mapping.tablo}, anahtar={mapping.anahtar}, spektrum={mapping.spektrum['tip']}, ölçek={mapping.olcek}")
    for k, v in mapping.alanlar.items():
        print(f"    {k:14} ← {v}")
    if a.yaz:
        mapping.kaynak = a.kaynak or ""
        Path(a.yaz).write_text(json.dumps(mapping.dump(), indent=2, ensure_ascii=False), "utf-8")
        print(f"Eşleme dosyası yazıldı: {a.yaz}  (kontrol edip gerekirse düzenleyin)")


def cmd_mdb_izle(a) -> None:
    from .mdb_bridge import Mapping, MdbBridge
    _setup_logging(not a.sessiz)
    import logging
    log = logging.getLogger("renkolcum.kopru")
    svc = build_service()
    mapping = Mapping.load(Path(a.esleme))
    std_cache: dict = {}

    def lookup(name: str):
        if name not in std_cache:
            std_cache[name] = svc.find_standard(name)
        return std_cache[name]

    bridge = MdbBridge(Path(a.klasor), mapping, svc.store, standards_lookup=lookup, reader_kind=a.okuyucu,
                       password=a.sifre, stable_seconds=0 if a.tek_sefer else a.bekle, pattern=a.desen)
    log.info("Köprü başladı: klasör=%s eşleme=%s bulut=%s", Path(a.klasor).resolve(), a.esleme,
             "bağlı" if svc.cloud_ready() else "YOK (kayıtlar kuyrukta bekleyecek)")
    last_sync = 0.0
    try:
        while True:
            results = bridge.scan_once()
            changed = any(r.get("yeni") or r.get("guncellenen") for r in results)
            if svc.cloud_ready() and (changed or svc.store.pending()) and (changed or time.time() - last_sync > 60):
                try:
                    r = svc.sync()
                    last_sync = time.time()
                    if r["gonderilen"] or r["hata"]:
                        log.info("Bulut: gönderilen=%d hata=%d bekleyen=%d", r["gonderilen"], r["hata"], r["bekleyen"])
                except Exception as e:  # noqa: BLE001
                    log.warning("Senkron hatası (sonra tekrar denenecek): %s", e)
            if a.tek_sefer:
                break
            time.sleep(a.aralik)
    except KeyboardInterrupt:
        log.info("Köprü durduruldu.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="renkolcum", description="Renk Ölçüm Sistemi (dummy) + Supabase bulut senkronu")
    ap.add_argument("--version", action="version", version=__version__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("ayar", help="Supabase URL/anahtar ve cihaz ayarı")
    p.add_argument("--url"); p.add_argument("--anahtar", help="Supabase anon (publishable) key")
    p.add_argument("--cihaz-seri"); p.set_defaults(fn=cmd_ayar)

    p = sp.add_parser("giris", help="Buluta e-posta + şifre ile giriş")
    p.add_argument("--email"); p.set_defaults(fn=cmd_giris)
    sp.add_parser("cikis", help="Oturumu kapat").set_defaults(fn=cmd_cikis)
    sp.add_parser("durum", help="Bağlantı ve kuyruk durumu").set_defaults(fn=cmd_durum)
    sp.add_parser("cihaz", help="Spektrofotometreyi algıla").set_defaults(fn=cmd_cihaz)

    p = sp.add_parser("olc", help="Spektrofotometreyle ölçüm al (simüle)")
    p.add_argument("--ad", help="Numune adı")
    p.add_argument("--numune", choices=list(SAMPLE_LIBRARY), help="Simülatörde ölçülecek numune (boşsa rastgele)")
    p.add_argument("--standart", help="Karşılaştırılacak standart (ad veya ID)")
    p.add_argument("--csv-cikti", help="Ölçümü cihaz CSV formatında da yaz")
    p.set_defaults(fn=cmd_olc)

    p = sp.add_parser("izle", help="Cihaz dışa aktarım klasörünü izle, yeni CSV'leri otomatik al")
    p.add_argument("klasor"); p.add_argument("--standart"); p.add_argument("--aralik", type=float, default=2.0)
    p.add_argument("--tek-sefer", action="store_true", help="Klasörü bir kez tara ve çık")
    p.set_defaults(fn=cmd_izle)

    sp.add_parser("senkron", help="Bekleyen kayıtları buluta gönder").set_defaults(fn=cmd_senkron)

    p = sp.add_parser("listele", help="Ölçümleri listele")
    p.add_argument("--bulut", action="store_true", help="Tüm kullanıcıların bulut ölçümleri")
    p.add_argument("-n", type=int, default=20); p.set_defaults(fn=cmd_listele)

    p = sp.add_parser("recete", help="Ölçümden reçete hesapla (Kubelka-Munk)")
    p.add_argument("olcum", help="Ölçüm ID'si (ilk 8 karakter yeter) veya 'son'")
    p.add_argument("--standarda-gore", action="store_true", help="Hedef olarak ölçümün bağlı olduğu standardı kullan")
    p.add_argument("--ad"); p.add_argument("--kaydetme", action="store_true", help="Sadece göster, kaydetme")
    p.set_defaults(fn=cmd_recete)

    sp.add_parser("standartlar", help="Renk standartlarını listele").set_defaults(fn=cmd_standartlar)
    p = sp.add_parser("standart-ekle", help="Bir ölçümü renk standardı yap")
    p.add_argument("olcum"); p.add_argument("--ad", required=True); p.add_argument("--musteri")
    p.add_argument("--tolerans", type=float, default=1.0); p.set_defaults(fn=cmd_standart_ekle)

    p = sp.add_parser("mdb-kesfet", help="Uygulamanın .mdb dosyasını incele, eşleme önerisi üret")
    p.add_argument("dosya"); p.add_argument("--yaz", metavar="esleme.json", help="Önerilen eşlemeyi dosyaya yaz")
    p.add_argument("--kaynak", help="Bu bilgisayar/lab için kısa ad (ör. LAB1)")
    p.add_argument("--okuyucu", choices=["auto", "odbc", "parser"], default="auto")
    p.add_argument("--sifre", help=".mdb dosyası şifreliyse"); p.set_defaults(fn=cmd_mdb_kesfet)

    p = sp.add_parser("mdb-izle", help="Uygulamanın .mdb klasörünü izle, yeni ölçümleri buluta gönder (köprü)")
    p.add_argument("klasor"); p.add_argument("--esleme", required=True, help="esleme.json")
    p.add_argument("--desen", default="*.mdb", help="Dosya deseni (varsayılan *.mdb)")
    p.add_argument("--okuyucu", choices=["auto", "odbc", "parser"], default="auto")
    p.add_argument("--sifre"); p.add_argument("--aralik", type=float, default=5.0, help="Tarama aralığı (sn)")
    p.add_argument("--bekle", type=float, default=3.0, help="Dosya yazımı bitti saymak için bekleme (sn)")
    p.add_argument("--tek-sefer", action="store_true"); p.add_argument("--sessiz", action="store_true")
    p.set_defaults(fn=cmd_mdb_izle)

    # Windows'ta çıktı dosyaya/boruya yönlendirildiğinde (cp1252/cp857) Türkçe karakter ve
    # simgeler programı çökertmesin: önce UTF-8 dene, olmazsa karakteri değiştir.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
