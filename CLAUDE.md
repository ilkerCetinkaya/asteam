# CLAUDE.md — Proje bağlamı (devralan geliştirici / Claude Code için)

## Amaç
Firmanın 20 yıllık **hazır Windows renk ölçüm uygulaması** (spektrofotometreden kumaş ölçer, analizi kendisi yapar)
ölçüm sonuçlarını **.mdb (Access)** dosyalarına yazıyor. Müşteri bu verilerin **bulutta** da olmasını,
**10 kullanıcının şifreyle** görebilmesini istiyor. Hedef: **ücretsiz servislerle** kurulmuş bir bulut sistemi.

## Kesinleşmiş kısıtlar / kararlar
- Uygulamanın **kaynak koduna erişim yok**; sadece ölçüm anında oluşan/güncellenen `.mdb` dosyalarına erişim var.
- Bu yüzden çözüm: uygulamanın yanında çalışan **.mdb köprüsü** (`renkolcum/mdb_bridge.py`, `renkolcum mdb-izle`).
  Köprü .mdb'ye **asla yazmaz**, geçici kopyasını okur.
- Bulut: **Supabase Free** (Postgres + Auth + RLS + Realtime). Web portalı: statik (`web/`), GitHub Pages/Vercel.
- Spektral veri: 360–740 nm, 10 nm, % yansıma (39 nokta). DB'de `valid_spectrum()` ile zorunlu.
- Uygulamanın hesapladığı L\*a\*b\*/ΔE varsa **onlar kullanılır**; eşlenmeyen kolonlar `meta.ham`'da saklanır.
- Yönlendirme tek yönlü varsayıldı (uygulama → bulut). Çift yönlü (buluttan .mdb'ye yazma) **istenmedi/önerilmedi**.
- Simülatör (`spectro.py`, `recipe.py`, `kubelka_munk.py`) başlangıçtaki dummy prototipten kaldı; gerçek akış için
  zorunlu değil ama testlerde ve demo verisinde kullanılıyor.

## Durum
- 38 pytest testi + `supabase/tests/run_local.sh` RLS testleri geçiyor (CI: `.github/workflows/ci.yml`).
- Windows exe'leri GitHub Actions'ta derleniyor ve duman testi geçiyor (`.github/workflows/windows-exe.yml`).
- **Yapılmadı / doğrulanmadı:**
  - Gerçek Supabase projesi kurulmadı (müşteri hesabında kurulacak; README → Kurulum).
  - **Gerçek uygulamanın .mdb dosyası henüz görülmedi.** Test .mdb'leri (`tests/mdb/`) tahmini bir yapıyla üretildi.
    İlk iş: gerçek dosyada `renkolcum mdb-kesfet <dosya.mdb>` çalıştırıp `esleme.json`'u doğrulamak.
  - `renkolcum-kopru.exe` (noconsole) ve `windows/kur.ps1` (Zamanlanmış Görev) gerçek Windows'ta denenmedi.
  - Şifreli .mdb için ODBC yolu (`--okuyucu odbc --sifre`) test edilmedi.
  - GitHub Pages workflow'u `main` dalına push'ta çalışır; şu an `main` dalı yok.

## Sıradaki adımlar (öneri)
1. Gerçek .mdb örneğiyle eşlemeyi kesinleştir; gerekirse `discover()`/`extract_measurements()` uyarla ve
   o dosyadan anonimleştirilmiş bir test fikstürü ekle.
2. Müşteri Supabase projesini kur: migration'lar + `seed.sql`, sign-up kapalı, `scripts/create_users.py` ile kullanıcılar.
3. Bir Windows makinede exe + `kur.ps1` ile uçtan uca dene; `%USERPROFILE%\.renkolcum\kopru.log`'a bak.
4. `web/config.js`'e URL/anon key yazıp portalı yayınla.

## Geliştirme
```bash
pip install -e ".[test,mdb]" "psycopg[binary]"
pytest -q                          # PostgreSQL (initdb) yoksa bulut testleri atlanır
bash supabase/tests/run_local.sh   # şema + RLS
python scripts/gen_seed.py > supabase/seed.sql      # boyarmadde/standart seed'i
python scripts/gen_web_demo.py                      # web/demo-data.js
python tests/mdb/olustur.py <jackcess-jar-klasörü>  # test .mdb'leri (Java + Jackcess)
```
- Testlerde `tests/fake_supabase.py` Supabase Auth/REST'i taklit eder; arkada gerçek Postgres + gerçek RLS çalışır.
- Kullanıcıya dönük metinler, komutlar ve dokümantasyon **Türkçe**.
- Gizli anahtar (service_role) repoya, `web/config.js`'e veya ölçüm bilgisayarlarına konmaz; `anon` anahtarı public'tir.
- Şema değişikliği = `supabase/migrations/` altına **yeni** dosya (eskileri değiştirme), sonra `run_local.sh`.
