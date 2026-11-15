-- Write skew: the doctors example (article: "Write Skew").
-- PostgreSQL shown. On MySQL use plain BEGIN: REPEATABLE READ is its default.

-- [Alice]
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- [Bob]
BEGIN ISOLATION LEVEL REPEATABLE READ;
-- [Alice]
SELECT count(*) FROM doctors WHERE on_call = true;   -- 2
-- [Bob]
SELECT count(*) FROM doctors WHERE on_call = true;   -- 2
-- [Alice]
UPDATE doctors SET on_call = false WHERE name = 'alice';
-- [Bob]
UPDATE doctors SET on_call = false WHERE name = 'bob';
-- [Alice]
COMMIT;
-- [Bob]
COMMIT;                                              -- succeeds
SELECT count(*) FROM doctors WHERE on_call = true;   -- 0

-- Reset (UPDATE doctors SET on_call = true;) and repeat with
-- BEGIN ISOLATION LEVEL SERIALIZABLE in both sessions:
-- on PostgreSQL, Bob's COMMIT fails with SQLSTATE 40001.
