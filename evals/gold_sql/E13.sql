SELECT ROUND(SUM(oi.total_sales), 2) AS total_sales, ROUND(SUM(oi.profit), 2) AS total_profit
FROM customers AS c
JOIN orders AS o ON o.customer_id = c.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE c.country = 'Japan'
  AND o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01';
