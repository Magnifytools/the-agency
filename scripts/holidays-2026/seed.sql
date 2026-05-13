-- Festivos 2026 (Nacho está en Alicante: region=VAL, locality=Alicante)
-- + Vacaciones de Nacho 2026

BEGIN;

-- Asegurar región/localidad de Nacho (idempotente, no pisa si ya tiene otra)
UPDATE users
SET region = COALESCE(region, 'VAL'),
    locality = COALESCE(locality, 'Alicante')
WHERE email = 'nacho@magnify.ing';

-- Festivos (nacionales + Valencia + Alicante)
-- Usa NOT EXISTS contra el índice único expression-based en prod
INSERT INTO company_holidays (date, name, country, region, locality)
SELECT * FROM (VALUES
  -- Nacionales (region NULL)
  ('2026-01-01'::date, 'Año Nuevo',                    'ES', NULL::varchar, NULL::varchar),
  ('2026-01-06'::date, 'Epifanía del Señor',           'ES', NULL,           NULL),
  ('2026-04-03'::date, 'Viernes Santo',                'ES', NULL,           NULL),
  ('2026-05-01'::date, 'Fiesta del Trabajo',           'ES', NULL,           NULL),
  ('2026-08-15'::date, 'Asunción de la Virgen',        'ES', NULL,           NULL),
  ('2026-10-12'::date, 'Fiesta Nacional de España',    'ES', NULL,           NULL),
  ('2026-12-08'::date, 'Inmaculada Concepción',        'ES', NULL,           NULL),
  ('2026-12-25'::date, 'Natividad del Señor',          'ES', NULL,           NULL),
  -- Comunitat Valenciana
  ('2026-03-19'::date, 'San José',                          'ES', 'VAL', NULL),
  ('2026-04-06'::date, 'Lunes de Pascua',                   'ES', 'VAL', NULL),
  ('2026-10-09'::date, 'Día de la Comunitat Valenciana',    'ES', 'VAL', NULL),
  -- Locales Alicante
  ('2026-04-16'::date, 'Santa Faz',              'ES', 'VAL', 'Alicante/Alacant'),
  ('2026-06-23'::date, 'Hogueras de San Juan',   'ES', 'VAL', 'Alicante/Alacant'),
  ('2026-06-24'::date, 'San Juan',               'ES', 'VAL', 'Alicante/Alacant')
) AS v(date, name, country, region, locality)
WHERE NOT EXISTS (
  SELECT 1 FROM company_holidays ch
  WHERE ch.date = v.date
    AND COALESCE(ch.region, '') = COALESCE(v.region, '')
    AND COALESCE(ch.locality, '') = COALESCE(v.locality, '')
);

-- Vacaciones de Nacho (solo laborables, status=vacation)
-- Bloque 1: 27 jul – 9 ago (10 laborables)
-- Bloque 2: 13 oct – 19 oct (5 laborables, salta sáb 17 + dom 18)
-- Bloque 3: 28 dic 2026 – 3 ene 2027 (5 laborables)
INSERT INTO user_day_statuses (user_id, date, status, label)
SELECT u.id, d::date, 'vacation', 'Vacaciones'
FROM users u, (VALUES
  -- Bloque 1
  ('2026-07-27'::date),('2026-07-28'::date),('2026-07-29'::date),('2026-07-30'::date),('2026-07-31'::date),
  ('2026-08-03'::date),('2026-08-04'::date),('2026-08-05'::date),('2026-08-06'::date),('2026-08-07'::date),
  -- Bloque 2
  ('2026-10-13'::date),('2026-10-14'::date),('2026-10-15'::date),('2026-10-16'::date),('2026-10-19'::date),
  -- Bloque 3
  ('2026-12-28'::date),('2026-12-29'::date),('2026-12-30'::date),('2026-12-31'::date),('2027-01-01'::date)
) AS dates(d)
WHERE u.email = 'nacho@magnify.ing'
ON CONFLICT (user_id, date) DO UPDATE
  SET status = EXCLUDED.status,
      label = EXCLUDED.label;

COMMIT;

-- Verificación
SELECT 'Festivos 2026' AS bloque, COUNT(*) FROM company_holidays
  WHERE date BETWEEN '2026-01-01' AND '2026-12-31'
UNION ALL
SELECT 'Vacaciones Nacho', COUNT(*) FROM user_day_statuses uds
  JOIN users u ON u.id = uds.user_id
  WHERE u.email = 'nacho@magnify.ing'
    AND uds.date BETWEEN '2026-07-01' AND '2027-01-31'
    AND uds.status = 'vacation';
