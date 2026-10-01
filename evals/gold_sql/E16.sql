SELECT o.payment_method, ROUND(SUM(oi.total_sales), 2) AS total_sales
FROM orders AS o
JOIN order_items AS oi ON oi.order_id = o.order_id
JOIN products AS p ON p.product_id = oi.product_id
WHERE p.product_category = 'Furniture'
GROUP BY o.payment_method
ORDER BY o.payment_method;
