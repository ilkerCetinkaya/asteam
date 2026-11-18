"""Supabase'de kullanıcı oluşturur (admin işlemi).

service_role anahtarı GİZLİDİR: sadece yöneticinin bilgisayarında, ortam değişkeni
olarak kullanın; repoya, web portalına veya ölçüm bilgisayarlarına koymayın.

Kullanım:
  export SUPABASE_URL=https://xxxx.supabase.co
  export SUPABASE_SERVICE_ROLE_KEY=...      # Dashboard → Project Settings → API Keys
  python scripts/create_users.py kullanicilar.csv

kullanicilar.csv (başlıklı):
  email,full_name,role,password
  ayse@firma.com,Ayşe Yılmaz,admin,
  mehmet@firma.com,Mehmet Kaya,operator,
Şifre boşsa güçlü rastgele şifre üretilip ekrana yazılır. İlk oluşturulan kullanıcı admin olur.
"""
import csv
import os
import secrets
import string
import sys

import requests


def main(path: str) -> None:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    alphabet = string.ascii_letters + string.digits + "!@#%*"
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pw = row.get("password") or "".join(secrets.choice(alphabet) for _ in range(14))
            r = requests.post(f"{url}/auth/v1/admin/users", headers=h, timeout=20, json={
                "email": row["email"], "password": pw, "email_confirm": True,
                "user_metadata": {"full_name": row.get("full_name") or row["email"], "role": row.get("role") or "operator"},
            })
            if r.status_code in (200, 201):
                print(f"✔ {row['email']:30} şifre: {pw if not row.get('password') else '(dosyadaki)'}")
            else:
                print(f"✖ {row['email']:30} {r.status_code}: {r.text[:200]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
