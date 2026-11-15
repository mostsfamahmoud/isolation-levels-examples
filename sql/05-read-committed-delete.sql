-- One statement, two moments (article: "READ COMMITTED"). PostgreSQL.
-- Start from widget = 9, gadget = 10:
UPDATE products SET stock = 9  WHERE id = 1;
UPDATE products SET stock = 10 WHERE id = 2;

-- [Session A]
BEGIN;
UPDATE products SET stock = stock + 1;         -- widget 10, gadget 11, not committed
-- [Session B]  (autocommit, no BEGIN)
DELETE FROM products WHERE stock = 10;         -- blocks on gadget's lock
-- [Session A]
COMMIT;
-- [Session B]  the DELETE now finishes: DELETE 0
SELECT name, stock FROM products ORDER BY id;  -- widget 10, gadget 11
