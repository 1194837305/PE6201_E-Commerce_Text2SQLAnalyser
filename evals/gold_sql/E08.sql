SELECT SUBSTR(order_date, 1, 7) AS month, ROUND(SUM(total_sales), 2) AS total_sales
FROM sales
WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01'
GROUP BY month
ORDER BY month;
