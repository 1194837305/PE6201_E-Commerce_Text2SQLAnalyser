SELECT payment_method, COUNT(DISTINCT order_id) AS order_count
FROM sales
WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'
GROUP BY payment_method
ORDER BY payment_method;
