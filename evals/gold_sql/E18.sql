SELECT event_type, COUNT(*) AS event_count
FROM user_events
WHERE event_time >= '2024-01-01' AND event_time < '2025-01-01'
GROUP BY event_type
ORDER BY event_count DESC, event_type
LIMIT 1;
