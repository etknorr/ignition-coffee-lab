INSERT INTO batch_events (batch_number, action, t_offset_sec, bean_temp_f, rate_of_rise_f, fan_level, heat_level)
VALUES (:batch_number, :action, :t_offset_sec, :bean_temp_f, :rate_of_rise_f, :fan_level, :heat_level)
