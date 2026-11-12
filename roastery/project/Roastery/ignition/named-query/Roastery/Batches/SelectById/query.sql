SELECT id, batch_number, roast_start, roast_end, bean_name, drop_temp_f, data
FROM batches WHERE batch_number = :batch_number
