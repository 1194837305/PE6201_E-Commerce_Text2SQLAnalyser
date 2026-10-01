SELECT
  'Q' || (CAST((CAST(STRFTIME('%m', order_date) AS INTEGER) - 1) / 3 AS INTEGER) + 1) AS quarter,
  ROUND(SUM(total_sales), 2) AS total_sales,
  ROUND(SUM(profit), 2) AS total_profit
FROM sales
WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'
GROUP BY quarter
ORDER BY quarter;
