SELECT id, batch_number, action, t_offset_sec, bean_temp_f, rate_of_rise_f, fan_level, heat_level, pressed_at
FROM batch_events WHERE batch_number = :batch_number ORDER BY pressed_at, id
