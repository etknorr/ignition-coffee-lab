INSERT INTO batches (batch_number, roast_start, roast_end, bean_name, drop_temp_f, data)
VALUES (:batch_number, :roast_start, :roast_end, :bean_name, :drop_temp_f, CAST(:data AS jsonb))
RETURNING id
