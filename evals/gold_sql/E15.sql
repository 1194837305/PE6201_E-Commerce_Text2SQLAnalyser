SELECT country, COUNT(DISTINCT customer_id) AS customer_count
FROM customers
GROUP BY country
ORDER BY customer_count DESC, country
LIMIT 1;
