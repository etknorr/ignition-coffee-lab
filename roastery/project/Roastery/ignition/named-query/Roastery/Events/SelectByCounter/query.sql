SELECT id, batch_number, action, press_counter, pressed_at
FROM batch_events
WHERE batch_number = :batch_number AND press_counter = :press_counter
