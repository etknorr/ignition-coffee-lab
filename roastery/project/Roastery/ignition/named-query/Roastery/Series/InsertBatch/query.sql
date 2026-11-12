INSERT INTO batch_series (batch_number, t_offset_sec, sample_ts, bean_temp_f, rate_of_rise_f, fan_level, heat_level)
SELECT :batch_number, (e->>'t')::integer, (e->>'ts')::timestamptz,
       (e->>'bt')::double precision, (e->>'ror')::double precision,
       (e->>'fan')::integer, (e->>'heat')::integer
FROM jsonb_array_elements(CAST(:points AS jsonb)) AS e
