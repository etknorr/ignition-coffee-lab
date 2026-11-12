UPDATE batches SET bean_name = :bean_name, drop_temp_f = :drop_temp_f,
       data = CAST(:data AS jsonb), updated_at = now()
WHERE batch_number = :batch_number
