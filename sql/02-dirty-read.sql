-- Dirty read (article: "1. Dirty read"). MySQL, READ UNCOMMITTED.
-- Run the steps in order, switching between two connections.

-- [Session A]
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
BEGIN;
-- [Session B]
BEGIN;
UPDATE products SET stock = 0 WHERE id = 1;    -- not committed
-- [Session A]
SELECT stock FROM products WHERE id = 1;       -- 0: a value that was never committed
-- [Session B]
ROLLBACK;
-- [Session A]
COMMIT;
