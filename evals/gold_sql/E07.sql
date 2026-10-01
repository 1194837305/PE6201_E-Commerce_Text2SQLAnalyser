SELECT product_category, ROUND(SUM(profit), 2) AS total_profit
FROM sales
WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01'
GROUP BY product_category
ORDER BY total_profit DESC, product_category
LIMIT 1;
