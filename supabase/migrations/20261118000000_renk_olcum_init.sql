-- =====================================================================
-- Renk Ölçüm / Reçete Sistemi — Supabase (PostgreSQL) şeması
-- 10 kullanıcılı paylaşımlı veritabanı, Row Level Security ile korunur.
-- Spektral veri: 360-740 nm, 10 nm aralık => 39 nokta, % yansıma.
-- =====================================================================

-- ---------- Ayarlar ----------------------------------------------------
create table if not exists public.app_settings (
  id          boolean primary key default true check (id),   -- tek satır
  company     text    not null default 'Demo Tekstil A.Ş.',
  max_users   integer not null default 10 check (max_users between 1 and 1000),
  updated_at  timestamptz not null default now()
);
insert into public.app_settings (id) values (true) on conflict do nothing;

-- ---------- Kullanıcı profilleri --------------------------------------
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  role        text not null default 'operator' check (role in ('admin','operator','viewer')),
  created_at  timestamptz not null default now()
);

-- Spektral dizi doğrulaması (39 nokta, 0-200 %)
create or replace function public.valid_spectrum(r double precision[])
returns boolean language sql immutable as $$
  select r is not null
     and array_ndims(r) = 1
     and array_length(r, 1) = 39
     and not exists (select 1 from unnest(r) v where v is null or v < 0 or v > 200 or v = 'NaN'::float8);
$$;

-- ---------- Cihazlar --------------------------------------------------
create table if not exists public.instruments (
  id          uuid primary key default gen_random_uuid(),
  serial_no   text not null unique,
  model       text not null,
  location    text,
  created_by  uuid references public.profiles(id) default auth.uid(),
  created_at  timestamptz not null default now()
);

-- ---------- Boyarmaddeler (reçete veritabanı) --------------------------
create table if not exists public.colorants (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique,
  name        text not null,
  ks          double precision[] not null check (array_length(ks, 1) = 39),  -- %1 başına K/S
  unit        text not null default '%',
  active      boolean not null default true,
  created_by  uuid references public.profiles(id) default auth.uid(),
  created_at  timestamptz not null default now()
);

-- ---------- Renk standartları (müşteri referansları) -------------------
create table if not exists public.standards (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  customer     text,
  reflectance  double precision[] not null check (public.valid_spectrum(reflectance)),
  l_star       double precision not null,
  a_star       double precision not null,
  b_star       double precision not null,
  tolerance_de double precision not null default 1.0,
  illuminant   text not null default 'D65',
  observer     text not null default '10',
  created_by   uuid references public.profiles(id) default auth.uid(),
  created_at   timestamptz not null default now()
);

-- ---------- Ölçümler ---------------------------------------------------
create table if not exists public.measurements (
  id            uuid primary key default gen_random_uuid(),
  client_uuid   uuid not null unique,              -- çevrimdışı kuyruktan tekrar gönderimde çift kaydı önler
  sample_name   text not null,
  reflectance   double precision[] not null check (public.valid_spectrum(reflectance)),
  wl_start      integer not null default 360,
  wl_step       integer not null default 10,
  l_star        double precision not null,
  a_star        double precision not null,
  b_star        double precision not null,
  standard_id   uuid references public.standards(id) on delete set null,
  delta_e2000   double precision,
  pass_fail     text check (pass_fail in ('GEÇTİ','KALDI')),
  instrument_serial text,
  instrument_model  text,
  meta          jsonb not null default '{}'::jsonb,
  measured_at   timestamptz not null default now(),
  measured_by   uuid not null references public.profiles(id) default auth.uid(),
  created_at    timestamptz not null default now()
);
create index if not exists measurements_measured_at_idx on public.measurements (measured_at desc);
create index if not exists measurements_standard_idx on public.measurements (standard_id);

-- ---------- Reçeteler --------------------------------------------------
create table if not exists public.recipes (
  id             uuid primary key default gen_random_uuid(),
  client_uuid    uuid unique,
  name           text not null,
  measurement_id uuid references public.measurements(id) on delete set null,
  standard_id    uuid references public.standards(id) on delete set null,
  components     jsonb not null,                  -- [{colorant_code, colorant_name, amount_pct}]
  predicted_l    double precision,
  predicted_a    double precision,
  predicted_b    double precision,
  predicted_de   double precision,
  status         text not null default 'taslak' check (status in ('taslak','onaylı','iptal')),
  notes          text,
  version        integer not null default 1,
  created_by     uuid not null references public.profiles(id) default auth.uid(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists recipes_created_at_idx on public.recipes (created_at desc);

-- ---------- Yardımcı fonksiyonlar ---------------------------------------
create or replace function public.my_role()
returns text language sql stable security definer set search_path = public as $$
  select role from public.profiles where id = auth.uid();
$$;

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  new.version := old.version + 1;
  return new;
end $$;

drop trigger if exists recipes_touch on public.recipes;
create trigger recipes_touch before update on public.recipes
  for each row execute function public.touch_updated_at();

-- Kullanıcı sayısı sınırı (varsayılan 10)
create or replace function public.enforce_user_limit()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  lim integer;
begin
  select max_users into lim from public.app_settings where id;
  perform pg_advisory_xact_lock(hashtext('profiles_seat_limit'));
  if (select count(*) from public.profiles) >= coalesce(lim, 10) then
    raise exception 'Kullanıcı limiti doldu (en fazla % kullanıcı)', lim
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

drop trigger if exists profiles_user_limit on public.profiles;
create trigger profiles_user_limit before insert on public.profiles
  for each row execute function public.enforce_user_limit();

-- Supabase Auth'ta kullanıcı oluşunca profil aç. İlk kullanıcı admin olur.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    case when not exists (select 1 from public.profiles) then 'admin'
         when new.raw_user_meta_data->>'role' in ('operator','viewer') then new.raw_user_meta_data->>'role'
         else 'operator' end
  );
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Kullanıcı kendi rolünü yükseltemesin
create or replace function public.protect_profile_role()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.role is distinct from old.role and coalesce(public.my_role(), '') <> 'admin'
     and auth.uid() is not null then
    raise exception 'Rol değiştirme yetkisi sadece admin''dedir';
  end if;
  return new;
end $$;

drop trigger if exists profiles_protect_role on public.profiles;
create trigger profiles_protect_role before update on public.profiles
  for each row execute function public.protect_profile_role();

-- ---------- Row Level Security ----------------------------------------
alter table public.app_settings enable row level security;
alter table public.profiles     enable row level security;
alter table public.instruments  enable row level security;
alter table public.colorants    enable row level security;
alter table public.standards    enable row level security;
alter table public.measurements enable row level security;
alter table public.recipes      enable row level security;

-- Okuma: sistemdeki (profili olan) tüm kullanıcılar ortak veriyi görür
do $$
declare t text;
begin
  foreach t in array array['app_settings','profiles','instruments','colorants','standards','measurements','recipes'] loop
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.my_role() is not null)',
      t || '_select', t);
  end loop;
end $$;

-- Yazma: admin + operator; viewer sadece okur. Operator yalnızca kendi kaydını
-- düzenler/siler, admin hepsini.
do $$
declare
  t text;
  owner_col text;
begin
  foreach t in array array['instruments','standards','measurements','recipes'] loop
    owner_col := case when t = 'measurements' then 'measured_by' else 'created_by' end;

    execute format('drop policy if exists %I on public.%I', t || '_insert', t);
    execute format(
      'create policy %I on public.%I for insert to authenticated
         with check (public.my_role() in (''admin'',''operator'') and %I = auth.uid())',
      t || '_insert', t, owner_col);

    execute format('drop policy if exists %I on public.%I', t || '_update', t);
    execute format(
      'create policy %I on public.%I for update to authenticated
         using (public.my_role() = ''admin'' or (public.my_role() = ''operator'' and %I = auth.uid()))
         with check (public.my_role() = ''admin'' or (public.my_role() = ''operator'' and %I = auth.uid()))',
      t || '_update', t, owner_col, owner_col);

    execute format('drop policy if exists %I on public.%I', t || '_delete', t);
    execute format(
      'create policy %I on public.%I for delete to authenticated
         using (public.my_role() = ''admin'' or (public.my_role() = ''operator'' and %I = auth.uid()))',
      t || '_delete', t, owner_col);
  end loop;
end $$;

-- Boyarmadde veritabanını sadece admin yönetir
drop policy if exists colorants_write on public.colorants;
create policy colorants_write on public.colorants for all to authenticated
  using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

-- Ayarlar: sadece admin değiştirir
drop policy if exists app_settings_update on public.app_settings;
create policy app_settings_update on public.app_settings for update to authenticated
  using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

-- Profil: herkes kendi adını, admin herkesi düzenler; silme sadece admin
drop policy if exists profiles_update on public.profiles;
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid() or public.my_role() = 'admin')
  with check (id = auth.uid() or public.my_role() = 'admin');
drop policy if exists profiles_delete on public.profiles;
create policy profiles_delete on public.profiles for delete to authenticated
  using (public.my_role() = 'admin' and id <> auth.uid());

-- Ölçüm/Reçete kaydını kimin yaptığını gösteren görünüm
create or replace view public.measurements_view with (security_invoker = true) as
  select m.*, p.full_name as measured_by_name, s.name as standard_name
  from public.measurements m
  left join public.profiles p on p.id = m.measured_by
  left join public.standards s on s.id = m.standard_id;

create or replace view public.recipes_view with (security_invoker = true) as
  select r.*, p.full_name as created_by_name, s.name as standard_name, m.sample_name
  from public.recipes r
  left join public.profiles p on p.id = r.created_by
  left join public.standards s on s.id = r.standard_id
  left join public.measurements m on m.id = r.measurement_id;

-- Anon kullanıcıya hiçbir erişim yok
revoke all on all tables in schema public from anon;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant usage on schema public to authenticated;

-- Gerçek zamanlı güncellemeler (10 kullanıcı aynı anda yeni ölçümleri görür)
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.measurements, public.recipes, public.standards;
    exception when duplicate_object then null;
    end;
  end if;
end $$;
