WITH daily AS (
  SELECT SUBSTR(event_time, 1, 10) AS day, COUNT(DISTINCT user_id) AS dau
  FROM user_events
  WHERE event_time >= '2024-01-01' AND event_time < '2025-01-01'
  GROUP BY day
), monthly AS (
  SELECT SUBSTR(event_time, 1, 7) AS month, COUNT(DISTINCT user_id) AS mau
  FROM user_events
  WHERE event_time >= '2024-01-01' AND event_time < '2025-01-01'
  GROUP BY month
)
SELECT m.month, m.mau, ROUND(AVG(d.dau), 2) AS average_dau
FROM monthly AS m
JOIN daily AS d ON SUBSTR(d.day, 1, 7) = m.month
GROUP BY m.month, m.mau
ORDER BY m.month;
