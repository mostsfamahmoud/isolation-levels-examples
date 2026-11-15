-- Phantom read (article: "3. Phantom read"). READ COMMITTED.
-- MySQL: run SET TRANSACTION ISOLATION LEVEL READ COMMITTED; in Session A first.

-- [Session A]
BEGIN;
SELECT count(*) FROM products WHERE stock < 5; -- 1
-- [Session B]
BEGIN;
INSERT INTO products VALUES (3, 'gizmo', 2);
COMMIT;
-- [Session A]
SELECT count(*) FROM products WHERE stock < 5; -- 2: a row appeared
COMMIT;
