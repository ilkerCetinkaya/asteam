-- Mevcut masaüstü uygulamasının .mdb dosyalarından gelen kayıtlar için kaynak bilgisi
alter table public.measurements add column if not exists operator_name text;   -- uygulamadaki operatör adı
alter table public.measurements add column if not exists source_ref text;      -- dosya:tablo:anahtar

create index if not exists measurements_source_ref_idx on public.measurements (source_ref);

-- measurements_view yeni kolonları içersin diye yeniden oluşturulur
drop view if exists public.measurements_view;
create view public.measurements_view with (security_invoker = true) as
  select m.*, p.full_name as measured_by_name, s.name as standard_name
  from public.measurements m
  left join public.profiles p on p.id = m.measured_by
  left join public.standards s on s.id = m.standard_id;
grant select on public.measurements_view to authenticated;
revoke all on public.measurements_view from anon;
