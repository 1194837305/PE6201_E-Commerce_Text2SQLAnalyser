SELECT c.customer_segment, ROUND(SUM(oi.quantity), 2) AS units_purchased
FROM customers AS c
JOIN orders AS o ON o.customer_id = c.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
JOIN products AS p ON p.product_id = oi.product_id
WHERE p.product_category = 'Technology'
GROUP BY c.customer_segment
ORDER BY units_purchased DESC, c.customer_segment
LIMIT 1;
