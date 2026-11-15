-- REPEATABLE READ: abort, not overwrite (article: "REPEATABLE READ"). PostgreSQL.

-- [Session A]
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- [Session B]
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- [Session A]
SELECT stock FROM products WHERE id = 1;       -- 10
-- [Session B]
SELECT stock FROM products WHERE id = 1;       -- 10
-- [Session A]
UPDATE products SET stock = 9 WHERE id = 1;
-- [Session B]
UPDATE products SET stock = 9 WHERE id = 1;    -- blocks, waiting for A's row lock
-- [Session A]
COMMIT;
-- [Session B]
-- ERROR:  could not serialize access due to concurrent update   (SQLSTATE 40001)
ROLLBACK;
