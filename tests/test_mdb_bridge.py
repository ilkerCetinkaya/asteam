""".mdb köprüsü testleri: gerçek Access (Jet4) dosyaları -> yerel kuyruk -> (sahte) Supabase -> RLS'li PostgreSQL."""
import os
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("access_parser")

from renkolcum.cli import main  # noqa: E402
from renkolcum.cloud import SupabaseClient  # noqa: E402
from renkolcum.mdb_bridge import (Mapping, MdbBridge, ParserReader, discover, extract_measurements,  # noqa: E402
                                  resample)
from renkolcum.service import RenkOlcumService  # noqa: E402
from renkolcum.store import LocalStore  # noqa: E402

MDB = Path(__file__).parent / "mdb"


def put(src: str, folder: Path, name: str) -> Path:
    """Uygulamanın dosyayı yazmasını taklit et (mtime'ı değiştirerek)."""
    dst = folder / name
    shutil.copyfile(MDB / src, dst)
    t = time.time() + (os.stat(dst).st_mtime_ns % 1000) / 1e6 + 1
    os.utime(dst, (t, t))
    return dst


def test_discover_wide_and_long():
    m, report = discover(ParserReader(MDB / "genis_v1.mdb"))
    assert m.tablo == "OLCUMLER" and m.anahtar == ["OLCUM_NO"] and m.spektrum["tip"] == "genis"
    assert len(m.spektrum["kolonlar"]) == 39
    assert m.alanlar["l_star"] == "L_DEG" and m.alanlar["sample_name"] == "NUMUNE_ADI"
    assert m.alanlar["operator_name"] == "OPERATOR" and m.alanlar["standard_name"] == "STANDART"
    m2, _ = discover(ParserReader(MDB / "tek_olcum_a.mdb"))
    assert m2.spektrum == {"tip": "uzun", "tablo": "SPEKTRUM", "baglanti": "OLCUM_NO", "dalga": "DALGA_BOYU",
                           "deger": "YANSIMA"}


def test_extract_uses_app_lab_and_keeps_raw_fields():
    m, _ = discover(ParserReader(MDB / "genis_v2.mdb"))
    items = extract_measurements(ParserReader(MDB / "genis_v2.mdb"), m, "olcumler.mdb")
    ok = [i for i in items if not i["_hata"]]
    bad = [i for i in items if i["_hata"]]
    assert len(ok) == 3 and len(bad) == 1 and "eksik" in bad[0]["_hata"]
    first = ok[0]
    assert len(first["reflectance"]) == 39
    assert first["meta"]["lab_kaynagi"] == "uygulama"
    assert first["meta"]["ham"]["ACIKLAMA"] == "uygulama kaydı"     # eşlenmemiş alanlar kaybolmaz
    assert first["operator_name"] == "AHMET"
    assert first["measured_at"].startswith("2026-11-18T09:01:00+03:00")


def test_fraction_scale_text_spectrum_and_resample():
    class FakeReader:
        def rows(self, table):
            return [{"ID": 7, "SPEK": ";".join(str(0.5) for _ in range(31))}]   # 400-700 nm, 0-1 ölçeği

    m = Mapping("T", ["ID"], {}, {"tip": "metin", "kolon": "SPEK", "ayirac": ";", "baslangic": 400, "adim": 10},
                olcek=100.0)
    it = extract_measurements(FakeReader(), m, "x.mdb")[0]
    assert it["reflectance"] == [50.0] * 39                    # 360-390 ve 710-740 kenardan uzatıldı
    assert it["meta"]["lab_kaynagi"] == "renkolcum"           # uygulamada Lab yoksa hesaplanır
    assert resample({360: 10, 380: 30})[1] == pytest.approx(20)


def _svc(fake, home, monkeypatch):
    monkeypatch.setenv("RENKOLCUM_HOME", str(home))
    c = SupabaseClient(fake.url, fake.anon_key)
    c.login("op1@demo.local", "Op123!")
    return RenkOlcumService(LocalStore(home / "yerel.db"), c)


def test_bridge_end_to_end_with_updates(fake_cloud, tmp_path, monkeypatch):
    svc = _svc(fake_cloud, tmp_path / "home", monkeypatch)
    folder = tmp_path / "UygulamaVeri"
    folder.mkdir()
    mapping, _ = discover(ParserReader(MDB / "genis_v1.mdb"))
    mapping.kaynak = "LAB1"
    bridge = MdbBridge(folder, mapping, svc.store, standards_lookup=svc.find_standard, stable_seconds=0.3)

    # 1) Uygulama ölçümü yazdı -> dosya sabitlenene kadar beklenir
    put("genis_v1.mdb", folder, "olcumler.mdb")
    assert bridge.scan_once() == []          # yeni değişti, henüz bekleniyor
    time.sleep(0.35)
    r = bridge.scan_once()[0]
    assert (r["yeni"], r["guncellenen"], r["hatali"]) == (2, 0, 0)
    assert svc.sync()["gonderilen"] == 2

    rows = svc.cloud.select("measurements_view", source_ref="eq.olcumler.mdb:OLCUMLER:1")
    assert rows[0]["sample_name"] == "Parti 2401 Kırmızı"
    assert rows[0]["operator_name"] == "AHMET"
    assert rows[0]["standard_name"] == "STD-001 Kırmızı"      # bulut standardına bağlandı
    assert rows[0]["meta"]["kaynak"] == "LAB1"

    # 2) Değişmeyen dosya tekrar işlenmez
    time.sleep(0.35)
    assert bridge.scan_once() == []

    # 3) Uygulama 1. satırı düzeltti, 2 satır ekledi (biri spektrumsuz)
    put("genis_v2.mdb", folder, "olcumler.mdb")
    bridge.scan_once()
    time.sleep(0.35)
    r = bridge.scan_once()[0]
    assert (r["yeni"], r["guncellenen"], r["ayni"], r["hatali"]) == (1, 1, 1, 1)
    s = svc.sync()
    assert s["gonderilen"] == 2 and s["bekleyen"] == 0
    rows = svc.cloud.select("measurements", source_ref="eq.olcumler.mdb:OLCUMLER:1")
    assert len(rows) == 1 and rows[0]["sample_name"] == "Parti 2401 Kırmızı (düzeltildi)"
    bej = svc.cloud.select("measurements", source_ref="eq.olcumler.mdb:OLCUMLER:3")[0]
    assert bej["standard_id"] is None and bej["meta"]["standart_adi"] == "STANDART-YOK"

    # 4) Yerel durum silinse bile (yeniden kurulum) bulutta çift kayıt oluşmaz
    svc2 = _svc(fake_cloud, tmp_path / "home2", monkeypatch)
    b2 = MdbBridge(folder, mapping, svc2.store, standards_lookup=svc2.find_standard, stable_seconds=0)
    b2.scan_once()
    svc2.sync()
    assert len(svc.cloud.select("measurements", source_ref="eq.olcumler.mdb:OLCUMLER:2")) == 1


def test_one_file_per_measurement_and_partial_file(fake_cloud, tmp_path, monkeypatch):
    svc = _svc(fake_cloud, tmp_path / "home", monkeypatch)
    folder = tmp_path / "Tekli"
    folder.mkdir()
    mapping, _ = discover(ParserReader(MDB / "tek_olcum_a.mdb"))
    bridge = MdbBridge(folder, mapping, svc.store, stable_seconds=0)
    put("tek_olcum_a.mdb", folder, "olcum_0001.mdb")
    put("tek_olcum_b.mdb", folder, "olcum_0002.mdb")
    (folder / "olcum_0003.mdb").write_bytes((MDB / "tek_olcum_a.mdb").read_bytes()[:5000])   # yarım yazılmış dosya
    res = bridge.scan_once()
    assert sum(r.get("yeni", 0) for r in res) == 2                       # aynı OLCUM_NO=1, farklı dosya -> 2 kayıt
    assert any("okuma_hatasi" in r for r in res)
    assert svc.sync()["gonderilen"] == 2
    # yarım dosya tamamlanınca işlenir
    put("tek_olcum_b.mdb", folder, "olcum_0003.mdb")
    res = bridge.scan_once()
    assert res[0]["dosya"] == "olcum_0003.mdb" and res[0]["yeni"] == 1


def test_cli_mdb_commands(fake_cloud, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RENKOLCUM_PASSWORD", "Op123!")
    main(["ayar", "--url", fake_cloud.url, "--anahtar", fake_cloud.anon_key])
    main(["giris", "--email", "op2@demo.local"])
    esleme = tmp_path / "esleme.json"
    main(["mdb-kesfet", str(MDB / "genis_v1.mdb"), "--yaz", str(esleme), "--kaynak", "LAB2"])
    folder = tmp_path / "veri"
    folder.mkdir()
    put("genis_v1.mdb", folder, "OLCUM.MDB".lower())
    main(["mdb-izle", str(folder), "--esleme", str(esleme), "--tek-sefer"])
    out = capsys.readouterr().out
    assert "Önerilen eşleme" in out and "yeni=2" in out and "gönderilen=2" in out
    rows = SupabaseClient.from_config().select("measurements_view", source_ref="eq.olcum.mdb:OLCUMLER:2")
    assert rows[0]["measured_by_name"] == "Zeynep Operatör" and rows[0]["meta"]["kaynak"] == "LAB2"
