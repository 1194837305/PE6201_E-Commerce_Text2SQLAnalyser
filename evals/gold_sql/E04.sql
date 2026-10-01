SELECT ROUND(AVG(discount_percent), 2) AS average_discount_percent
FROM sales
WHERE customer_segment = 'Consumer';
