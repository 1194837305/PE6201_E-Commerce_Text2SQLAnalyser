SELECT p.product_name, ROUND(SUM(oi.quantity), 2) AS units_sold
FROM order_items AS oi
JOIN products AS p ON p.product_id = oi.product_id
GROUP BY p.product_name
ORDER BY units_sold DESC, p.product_name
LIMIT 5;
