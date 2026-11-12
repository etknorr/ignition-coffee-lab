SELECT t_offset_sec, sample_ts, bean_temp_f, rate_of_rise_f, fan_level, heat_level
FROM batch_series WHERE batch_number = :batch_number ORDER BY t_offset_sec
