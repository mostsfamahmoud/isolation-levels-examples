-- Lost update on MySQL's REPEATABLE READ (article: "Where lost update actually fits").

-- [Session A]
BEGIN;
-- [Session B]
BEGIN;
-- [Session A]
SELECT stock FROM products WHERE id = 1;       -- 10
-- [Session B]
SELECT stock FROM products WHERE id = 1;       -- 10
-- [Session A]
UPDATE products SET stock = 9 WHERE id = 1;
COMMIT;
-- [Session B]
UPDATE products SET stock = 9 WHERE id = 1;    -- succeeds
COMMIT;
SELECT stock FROM products WHERE id = 1;       -- 9 after two sales: one update was lost
-- Fix: write SET stock = stock - 1 instead; stock then ends at 8.
