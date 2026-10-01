SELECT ROUND(SUM(profit), 2) AS total_profit
FROM sales
WHERE country = 'Japan'
  AND order_date >= '2024-01-01' AND order_date < '2025-01-01';
