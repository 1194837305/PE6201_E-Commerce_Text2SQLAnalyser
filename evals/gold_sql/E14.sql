SELECT SUBSTR(o.order_date, 1, 7) AS month, ROUND(SUM(oi.total_sales), 2) AS total_sales
FROM customers AS c
JOIN orders AS o ON o.customer_id = c.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
JOIN products AS p ON p.product_id = oi.product_id
WHERE c.country = 'Germany'
  AND p.product_category = 'Technology'
  AND o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'
GROUP BY month
ORDER BY month;
