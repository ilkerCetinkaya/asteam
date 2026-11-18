"""Uçtan uca: CLI servisi -> (sahte) Supabase REST -> RLS'li PostgreSQL."""
import pytest
import requests

from renkolcum import config
from renkolcum.cli import main
from renkolcum.cloud import CloudError, SupabaseClient
from renkolcum.service import RenkOlcumService
from renkolcum.spectro import SimulatedSpectrophotometer
from renkolcum.store import LocalStore


def svc_for(fake, email, password, home, monkeypatch):
    monkeypatch.setenv("RENKOLCUM_HOME", str(home))
    client = SupabaseClient(fake.url, fake.anon_key)
    client.login(email, password)
    return RenkOlcumService(LocalStore(home / "yerel.db"), client)


def test_wrong_password(fake_cloud):
    with pytest.raises(CloudError, match="hatalı"):
        SupabaseClient(fake_cloud.url, fake_cloud.anon_key).login("op1@demo.local", "yanlis")


def test_shared_database_flow(fake_cloud, tmp_path, monkeypatch):
    op1 = svc_for(fake_cloud, "op1@demo.local", "Op123!", tmp_path / "op1", monkeypatch)
    std = op1.find_standard("STD-001")
    assert std is not None, "seed standartları buluttan gelmeli"
    dev = SimulatedSpectrophotometer(serial="SIM-OP1", seed=11)
    m = op1.record_measurement(dev.measure("kirmizi"), "Parti 1 kırmızı", std)
    assert m["pass_fail"] in ("GEÇTİ", "KALDI")
    res = op1.make_recipe(m)
    op1.record_recipe({"payload": m}, res)
    r = op1.sync()
    assert r == {"gonderilen": 2, "hata": 0, "bekleyen": 0}

    # İkinci kullanıcı aynı veritabanını görür
    op2 = svc_for(fake_cloud, "op2@demo.local", "Op123!", tmp_path / "op2", monkeypatch)
    rows = op2.cloud.select("measurements_view", client_uuid=f"eq.{m['client_uuid']}")
    assert len(rows) == 1
    assert rows[0]["measured_by_name"] == "Mehmet Operatör"
    assert rows[0]["standard_name"] == "STD-001 Kırmızı"
    assert len(rows[0]["reflectance"]) == 39
    rec = op2.cloud.select("recipes_view", client_uuid=f"eq.{op1.store.recent('recipe', 1)[0]['client_uuid']}")
    assert rec[0]["measurement_id"] == rows[0]["id"]
    assert rec[0]["components"][0]["colorant_code"] == "R03"

    # op2, op1'in kaydını değiştiremez (RLS: 0 satır)
    assert op2.cloud.update("measurements", {"id": rows[0]["id"]}, {"sample_name": "değişti"}) == []
    # admin değiştirebilir
    adm = svc_for(fake_cloud, "admin@demo.local", "Admin123!", tmp_path / "adm", monkeypatch)
    assert adm.cloud.me()["role"] == "admin"
    assert len(adm.cloud.update("recipes", {"id": rec[0]["id"]}, {"status": "onaylı"})) == 1


def test_viewer_cannot_write(fake_cloud, tmp_path, monkeypatch):
    v = svc_for(fake_cloud, "izleyici@demo.local", "View123!", tmp_path / "v", monkeypatch)
    v.record_measurement(SimulatedSpectrophotometer(seed=1).measure("mavi"), "izleyici denemesi")
    r = v.sync()
    assert r["hata"] == 1 and r["bekleyen"] == 1
    assert "row-level security" in v.store.pending()[0]["error"]


def test_offline_queue_then_sync_is_idempotent(fake_cloud, tmp_path, monkeypatch):
    s = svc_for(fake_cloud, "op1@demo.local", "Op123!", tmp_path / "off", monkeypatch)
    good_url = s.cloud.url
    s.cloud.url = "http://127.0.0.1:9"  # bağlantı yok
    m = s.record_measurement(SimulatedSpectrophotometer(seed=5).measure("sari"), "Çevrimdışı ölçüm")
    r = s.sync()
    assert r["hata"] == 1 and r["bekleyen"] == 1
    s.cloud.url = good_url
    assert s.sync()["gonderilen"] == 1
    # aynı kaydı yeniden göndermek çift kayıt oluşturmaz
    s.store.db.execute("update outbox set synced = 0")
    s.store.db.commit()
    assert s.sync()["gonderilen"] == 1
    assert len(s.cloud.select("measurements", client_uuid=f"eq.{m['client_uuid']}")) == 1


def test_expired_token_is_refreshed(fake_cloud, tmp_path, monkeypatch):
    s = svc_for(fake_cloud, "op2@demo.local", "Op123!", tmp_path / "exp", monkeypatch)
    fake_cloud.expire_all_tokens()
    assert s.cloud.me()["email"] == "op2@demo.local"


def test_cli_end_to_end(fake_cloud, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RENKOLCUM_PASSWORD", "Op123!")
    main(["ayar", "--url", fake_cloud.url, "--anahtar", fake_cloud.anon_key, "--cihaz-seri", "SIM-CLI"])
    main(["giris", "--email", "op2@demo.local"])
    main(["olc", "--ad", "CLI lacivert", "--numune", "lacivert", "--standart", "STD-002"])
    out = capsys.readouterr().out
    assert "Hoş geldiniz Zeynep Operatör" in out and "Buluta gönderildi: 1" in out
    # cihaz CSV klasörü izleme
    csv_dir = tmp_path / "cihaz"
    main(["olc", "--ad", "CSV numune", "--numune", "bej", "--csv-cikti", str(tmp_path / "x.csv")])
    csv_dir.mkdir()
    (tmp_path / "x.csv").rename(csv_dir / "olcum1.csv")
    main(["izle", str(csv_dir), "--tek-sefer"])
    assert (csv_dir / "islenen" / "olcum1.csv").exists()
    main(["recete", "son"])
    main(["listele", "--bulut", "-n", "50"])
    out = capsys.readouterr().out
    assert "Yeni ölçüm algılandı: olcum1.csv" in out
    assert "CLI lacivert" in out and "Zeynep Operatör" in out
    assert "Reçete kaydedildi" in out
    main(["cikis"])
    assert config.load_session() == {}
