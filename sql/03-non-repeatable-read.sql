-- Non-repeatable read (article: "2. Non-repeatable read"). READ COMMITTED.
-- PostgreSQL: plain BEGIN is READ COMMITTED.
-- MySQL: run SET TRANSACTION ISOLATION LEVEL READ COMMITTED; in Session A first.

-- [Session A]
BEGIN;
SELECT stock FROM products WHERE id = 1;       -- 10
-- [Session B]
BEGIN;
UPDATE products SET stock = 4 WHERE id = 1;
COMMIT;
-- [Session A]
SELECT stock FROM products WHERE id = 1;       -- 4: same query, same transaction
COMMIT;
