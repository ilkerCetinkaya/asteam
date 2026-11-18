-- RLS ve kullanıcı limiti testleri. Hata olursa psql ON_ERROR_STOP ile durur.
\set ON_ERROR_STOP on
\o /dev/null
begin;

-- 10 kullanıcı oluştur (ilki admin olur)
insert into auth.users (id, email, raw_user_meta_data)
select ('00000000-0000-0000-0000-0000000000' || lpad(g::text, 2, '0'))::uuid,
       'kullanici' || g || '@demo.local',
       case when g = 10 then '{"role":"viewer"}'::jsonb else '{}'::jsonb end
from generate_series(1, 10) g;

do $$ begin
  assert (select count(*) from public.profiles) = 10, '10 profil bekleniyordu';
  assert (select role from public.profiles where email = 'kullanici1@demo.local') = 'admin', 'ilk kullanıcı admin olmalı';
  assert (select role from public.profiles where email = 'kullanici10@demo.local') = 'viewer', 'viewer rolü';
end $$;

-- 11. kullanıcı reddedilmeli
do $$ begin
  begin
    insert into auth.users (email) values ('fazla@demo.local');
    raise exception 'LIMIT CALISMADI';
  exception when check_violation then
    raise notice 'OK: 11. kullanıcı reddedildi';
  end;
end $$;

-- Operator (kullanıcı 2) ölçüm ekler
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', true);
insert into public.measurements (client_uuid, sample_name, reflectance, l_star, a_star, b_star)
values (gen_random_uuid(), 'Op2 numune', array_fill(50.0::float8, array[39]), 76, 0, 0);

-- Geçersiz spektrum (38 nokta) reddedilmeli
do $$ begin
  begin
    insert into public.measurements (client_uuid, sample_name, reflectance, l_star, a_star, b_star)
    values (gen_random_uuid(), 'Bozuk', array_fill(50.0::float8, array[38]), 1, 1, 1);
    raise exception 'SPEKTRUM KONTROLU CALISMADI';
  exception when check_violation then raise notice 'OK: 38 noktalı spektrum reddedildi';
  end;
end $$;

-- Başkası adına kayıt atamaz
do $$ begin
  begin
    insert into public.measurements (client_uuid, sample_name, reflectance, l_star, a_star, b_star, measured_by)
    values (gen_random_uuid(), 'Sahte', array_fill(50.0::float8, array[39]), 1, 1, 1,
            '00000000-0000-0000-0000-000000000003');
    raise exception 'RLS CALISMADI';
  exception when insufficient_privilege then raise notice 'OK: başkası adına kayıt reddedildi';
  end;
end $$;

-- Operator 3 ölçümü görür ama değiştiremez/silemez
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', true);
do $$
declare n int;
begin
  assert (select count(*) from public.measurements) = 1, 'operator 3 ortak ölçümü görmeli';
  update public.measurements set sample_name = 'hack';
  get diagnostics n = row_count;
  assert n = 0, 'operator başkasının ölçümünü güncelleyememeli';
  delete from public.measurements;
  get diagnostics n = row_count;
  assert n = 0, 'operator başkasının ölçümünü silememeli';
  -- rolünü yükseltemez
  begin
    update public.profiles set role = 'admin' where id = auth.uid();
    raise exception 'ROL KORUMASI CALISMADI';
  exception when raise_exception then
    if sqlerrm = 'ROL KORUMASI CALISMADI' then raise; end if;
  end;
end $$;

-- Viewer okur ama yazamaz
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000010', true);
do $$ begin
  assert (select count(*) from public.measurements_view) = 1, 'viewer okumalı';
  begin
    insert into public.recipes (name, components) values ('x', '[]');
    raise exception 'VIEWER YAZDI';
  exception when insufficient_privilege then raise notice 'OK: viewer yazamadı';
  end;
end $$;

-- Admin her şeyi düzenler
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', true);
do $$
declare n int;
begin
  update public.measurements set sample_name = 'Admin düzeltti';
  get diagnostics n = row_count;
  assert n = 1, 'admin güncelleyebilmeli';
  insert into public.recipes (name, components) values ('R1', '[{"colorant_code":"R03","amount_pct":1.8}]');
  update public.recipes set status = 'onaylı';
  assert (select version from public.recipes) = 2, 'versiyon artmalı';
end $$;

-- Anonim erişim yok
reset role;
set local role anon;
do $$ begin
  begin
    perform 1 from public.measurements;
    raise exception 'ANON OKUDU';
  exception when insufficient_privilege then raise notice 'OK: anon erişimi yok';
  end;
end $$;

reset role;
rollback;
\o
\echo 'TUM RLS TESTLERI GECTI'
