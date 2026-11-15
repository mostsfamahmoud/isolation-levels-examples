-- Fix 1: lock the rows your rule reads (article: "Fix 1"). PostgreSQL, READ COMMITTED.
-- Run the same block in two sessions, Alice and Bob (Bob updates 'bob').

BEGIN;
SELECT name FROM doctors WHERE on_call = true FOR UPDATE;  -- Bob waits here until Alice commits
-- the application counts the returned rows and decides
UPDATE doctors SET on_call = false WHERE name = 'alice';
COMMIT;
-- Bob's SELECT then returns only 'bob', so Bob stays on call.
-- SQL Server: SELECT name FROM doctors WITH (UPDLOCK) WHERE on_call = 1;
