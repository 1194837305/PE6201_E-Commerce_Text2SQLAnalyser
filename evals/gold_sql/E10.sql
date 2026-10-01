SELECT SUBSTR(order_date, 1, 4) AS year, ROUND(SUM(total_sales), 2) AS total_sales
FROM sales
WHERE order_date >= '2023-01-01' AND order_date < '2026-01-01'
GROUP BY year
ORDER BY year;
