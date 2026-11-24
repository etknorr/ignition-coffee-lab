UPDATE batches SET bean_name = :bean_name, drop_temp_f = :drop_temp_f,
       roast_end = :roast_end,
       data = CAST(:data AS jsonb), updated_at = now()
WHERE batch_number = :batch_number
