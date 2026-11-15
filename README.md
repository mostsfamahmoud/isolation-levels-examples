# Isolation Levels: runnable examples

Companion code for the article **"Isolation Levels: What Your Transaction Can Actually See"**.
Every two-session example in the article, as plain SQL you can copy, plus a script that runs
all of them on PostgreSQL, MySQL, SQL Server and Oracle and checks each result against the article.

## Run everything

```
docker compose up -d            # Oracle and SQL Server can take a few minutes on first start
pip install "psycopg[binary]" pymysql pymssql oracledb
python run_checks.py            # or double-click run_checks.bat on Windows
```

Each check prints `PASS` or `FAIL`. Engines that aren't running are skipped. Last full run: **37/37 passed** on PostgreSQL 17, MySQL 8.4, SQL Server 2022 and Oracle 23ai Free.

## Run an example by hand

1. Load `sql/01-setup.sql`.
2. Open two connections (two terminals, or two query tabs).
3. Follow the file step by step: each `-- [Session A]` / `-- [Session B]` marker says which
   connection runs the next statements.

| File | Article section | Engine |
|---|---|---|
| `sql/02-dirty-read.sql` | 1. Dirty read | MySQL |
| `sql/03-non-repeatable-read.sql` | 2. Non-repeatable read | PostgreSQL, MySQL |
| `sql/04-phantom-read.sql` | 3. Phantom read | PostgreSQL, MySQL |
| `sql/05-read-committed-delete.sql` | READ COMMITTED: one statement, two moments | PostgreSQL |
| `sql/06-repeatable-read-abort.sql` | REPEATABLE READ: abort, not overwrite | PostgreSQL |
| `sql/07-lost-update-mysql.sql` | Where "lost update" actually fits | MySQL |
| `sql/08-write-skew.sql` | Write skew (doctors) | PostgreSQL, MySQL |
| `sql/09-for-update-fix.sql` | Fix 1: lock the rows your rule reads | PostgreSQL |

The SQL uses PostgreSQL/MySQL syntax. For SQL Server and Oracle, swap in the forms from the
article's "Running the examples on your engine" table (for example `BEGIN TRANSACTION`, `BIT`
or `NUMBER(1)` for booleans, `WITH (UPDLOCK)`). `run_checks.py` already does this for all four.

## What the script checks

- **PostgreSQL 17 (14 checks):** default level, non-repeatable and phantom reads, the DELETE that deletes nothing, REPEATABLE READ aborting with 40001, write skew at REPEATABLE READ and SERIALIZABLE, `FOR UPDATE`, the retry loop.
- **MySQL 8.4 (10 checks):** default level, dirty read, non-repeatable and phantom reads, one-shot `SET TRANSACTION`, lost update and its fix, write skew at REPEATABLE READ, deadlock at SERIALIZABLE.
- **SQL Server 2022 (8 checks):** default level, dirty read, phantoms at lock-based REPEATABLE READ, lost update and write skew stopped by deadlock (1205), write skew at SNAPSHOT, range locks at SERIALIZABLE, `UPDLOCK`.
- **Oracle 23ai Free (5 checks):** no REPEATABLE READ, non-repeatable read at READ COMMITTED, no phantoms at SERIALIZABLE, `ORA-08177` on a lost update, write skew at SERIALIZABLE.
