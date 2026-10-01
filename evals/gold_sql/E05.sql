SELECT country, ROUND(SUM(total_sales), 2) AS total_sales
FROM sales
WHERE order_date >= '2023-01-01' AND order_date < '2024-01-01'
GROUP BY country
ORDER BY total_sales DESC, country
LIMIT 3;
