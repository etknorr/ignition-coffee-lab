SELECT id, batch_number, roast_start, roast_end, bean_name, drop_temp_f,
       data->>'roastDegree' AS roast_degree,
       (data->'phases'->>'dtrPct')::double precision AS dtr_pct,
       (data->'metadata'->>'ChargeWeightG')::double precision AS charge_g,
       (data->'metadata'->>'WeightOutG')::double precision AS weight_out_g,
       data->'metadata'->>'Origin' AS origin,
       (data->>'totalSec')::double precision AS total_sec
FROM batches
ORDER BY roast_start DESC NULLS LAST, batch_number DESC
