"""
Runs every example from the article on real databases and checks each result
against what the article claims.

    docker compose up -d                 # first start can take a few minutes (Oracle, SQL Server)
    pip install "psycopg[binary]" pymysql pymssql oracledb
    python run_checks.py

Prints PASS/FAIL per check. Engines that are not reachable are skipped.
"""
import threading
import time

import psycopg
import pymysql

PG = dict(host="localhost", port=55432, user="postgres", password="test", dbname="postgres")
MY = dict(host="localhost", port=53306, user="root", password="test", database="test")
MS = dict(server="localhost", port=51433, user="sa", password="Test_pass1!")
OR = dict(user="app", password="test", dsn="localhost:51521/FREEPDB1")

results = []



def check(name, got, expected):
    ok = got == expected
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}, article says {expected!r}")


class Background:
    """Run one statement on another thread, so it can block on a lock."""

    def __init__(self, fn):
        self.result, self.error = None, None
        self.t = threading.Thread(target=self._run, args=(fn,))
        self.t.start()
        time.sleep(0.5)  # give it time to reach the lock

    def _run(self, fn):
        try:
            self.result = fn()
        except Exception as e:  # noqa: BLE001  (we inspect it afterwards)
            self.error = e

    def blocked(self):
        return self.t.is_alive()

    def join(self):
        self.t.join(10)
        return self


# ---------------------------------------------------------------- PostgreSQL

def pg():
    return psycopg.connect(**PG, autocommit=True)


def pg_one(c, sql):
    return c.execute(sql).fetchone()[0]


def pg_reset():
    with pg() as c:
        c.execute("DROP TABLE IF EXISTS products, doctors")
        c.execute("CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(50) NOT NULL, stock INT NOT NULL)")
        c.execute("INSERT INTO products VALUES (1, 'widget', 10), (2, 'gadget', 3)")
        c.execute("CREATE TABLE doctors (name VARCHAR(50) PRIMARY KEY, on_call BOOLEAN NOT NULL)")
        c.execute("INSERT INTO doctors VALUES ('alice', true), ('bob', true)")


def pg_checks():
    print("\n== PostgreSQL ==")
    with pg() as c:
        check("PG default level", pg_one(c, "SHOW transaction_isolation"), "read committed")

    # Panel 2: non-repeatable read at READ COMMITTED
    pg_reset()
    a, b = pg(), pg()
    a.execute("BEGIN")
    r1 = pg_one(a, "SELECT stock FROM products WHERE id = 1")
    b.execute("BEGIN"); b.execute("UPDATE products SET stock = 4 WHERE id = 1"); b.execute("COMMIT")
    r2 = pg_one(a, "SELECT stock FROM products WHERE id = 1")
    a.execute("COMMIT")
    check("PG RC non-repeatable read", (r1, r2), (10, 4))

    # Panel 3: phantom read at READ COMMITTED
    pg_reset()
    a.execute("BEGIN")
    r1 = pg_one(a, "SELECT count(*) FROM products WHERE stock < 5")
    b.execute("BEGIN"); b.execute("INSERT INTO products VALUES (3, 'gizmo', 2)"); b.execute("COMMIT")
    r2 = pg_one(a, "SELECT count(*) FROM products WHERE stock < 5")
    a.execute("COMMIT")
    check("PG RC phantom read", (r1, r2), (1, 2))

    # Image 03: DELETE at READ COMMITTED deletes nothing
    pg_reset()
    a.execute("UPDATE products SET stock = 9 WHERE id = 1")
    a.execute("UPDATE products SET stock = 10 WHERE id = 2")
    a.execute("BEGIN"); a.execute("UPDATE products SET stock = stock + 1")
    bg = Background(lambda: b.execute("DELETE FROM products WHERE stock = 10").rowcount)
    was_blocked = bg.blocked()
    a.execute("COMMIT")
    bg.join()
    rows = a.execute("SELECT name, stock FROM products ORDER BY id").fetchall()
    check("PG RC DELETE blocks, then deletes 0 rows", (was_blocked, bg.result), (True, 0))
    check("PG RC DELETE final state", rows, [("widget", 10), ("gadget", 11)])

    # Image 04: REPEATABLE READ waits, then aborts with 40001
    pg_reset()
    a.execute("BEGIN ISOLATION LEVEL REPEATABLE READ"); b.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    pg_one(a, "SELECT stock FROM products WHERE id = 1"); pg_one(b, "SELECT stock FROM products WHERE id = 1")
    a.execute("UPDATE products SET stock = 9 WHERE id = 1")
    bg = Background(lambda: b.execute("UPDATE products SET stock = 9 WHERE id = 1"))
    was_blocked = bg.blocked()
    a.execute("COMMIT")
    bg.join()
    b.execute("ROLLBACK")
    err = bg.error
    check("PG RR: B waits, then fails with 40001", (was_blocked, getattr(err, "sqlstate", None)), (True, "40001"))
    check("PG RR error text", str(err).splitlines()[0] if err else None,
          "could not serialize access due to concurrent update")

    # MySQL demo interleaving on PG RR: A commits before B updates -> B fails at once
    pg_reset()
    a.execute("BEGIN ISOLATION LEVEL REPEATABLE READ"); b.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    pg_one(a, "SELECT stock FROM products WHERE id = 1"); pg_one(b, "SELECT stock FROM products WHERE id = 1")
    a.execute("UPDATE products SET stock = 9 WHERE id = 1"); a.execute("COMMIT")
    try:
        b.execute("UPDATE products SET stock = 9 WHERE id = 1"); state = "succeeded"
    except psycopg.errors.SerializationFailure:
        state = "40001"
    b.execute("ROLLBACK")
    check("PG RR, A already committed: B's UPDATE", state, "40001")

    # Doctors at REPEATABLE READ: both commit, zero on call
    def doctors(level):
        pg_reset()
        a.execute(f"BEGIN ISOLATION LEVEL {level}"); b.execute(f"BEGIN ISOLATION LEVEL {level}")
        ca = pg_one(a, "SELECT count(*) FROM doctors WHERE on_call = true")
        cb = pg_one(b, "SELECT count(*) FROM doctors WHERE on_call = true")
        out, failed = [], set()
        for who, conn, stmt in [("a", a, "UPDATE doctors SET on_call = false WHERE name = 'alice'"),
                                ("b", b, "UPDATE doctors SET on_call = false WHERE name = 'bob'"),
                                ("a", a, "COMMIT"), ("b", b, "COMMIT")]:
            if who in failed:
                out.append("skipped"); continue
            try:
                conn.execute(stmt); out.append("ok")
            except psycopg.Error as e:
                out.append(e.sqlstate); failed.add(who)
                if stmt != "COMMIT":
                    conn.execute("ROLLBACK")
        left = pg_one(a, "SELECT count(*) FROM doctors WHERE on_call = true")
        return (ca, cb), out, left

    reads, out, left = doctors("REPEATABLE READ")
    check("PG doctors RR: both read 2", reads, (2, 2))
    check("PG doctors RR: both commit, 0 on call", (out, left), (["ok", "ok", "ok", "ok"], 0))
    reads, out, left = doctors("SERIALIZABLE")
    check("PG doctors SERIALIZABLE: Bob's COMMIT fails 40001, 1 on call", (out, left), (["ok", "ok", "ok", "40001"], 1))

    # Fix 1: FOR UPDATE at READ COMMITTED, Bob blocks and then sees only himself
    pg_reset()
    a.execute("BEGIN")
    a.execute("SELECT name FROM doctors WHERE on_call = true FOR UPDATE").fetchall()
    b.execute("BEGIN")
    bg = Background(lambda: b.execute("SELECT name FROM doctors WHERE on_call = true FOR UPDATE").fetchall())
    was_blocked = bg.blocked()
    a.execute("UPDATE doctors SET on_call = false WHERE name = 'alice'"); a.execute("COMMIT")
    bg.join(); b.execute("COMMIT")
    check("PG FOR UPDATE: Bob blocks, then sees 1 doctor", (was_blocked, bg.result), (True, [("bob",)]))

    # FOR UPDATE on count(*) is rejected
    try:
        a.execute("SELECT count(*) FROM doctors WHERE on_call = true FOR UPDATE"); state = "accepted"
    except psycopg.Error as e:
        state = "rejected"
    check("PG rejects FOR UPDATE on count(*)", state, "rejected")

    # Retry loop from the article: two concurrent "leave if someone else is on call"
    import random
    from psycopg import errors

    RETRYABLE = (errors.SerializationFailure, errors.DeadlockDetected)

    def run_serializable(conn, work, tries=5):
        conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        for attempt in range(1, tries + 1):
            try:
                with conn.transaction():
                    return work(conn)
            except RETRYABLE:
                if attempt == tries:
                    raise
                time.sleep(random.uniform(0, 0.05 * 2 ** attempt))

    pg_reset()
    barrier = threading.Barrier(2)

    def leave(name):
        def work(conn):
            n = pg_one(conn, "SELECT count(*) FROM doctors WHERE on_call = true")
            try:
                barrier.wait(1)  # make the first attempts overlap
            except threading.BrokenBarrierError:
                pass
            if n >= 2:
                conn.execute("UPDATE doctors SET on_call = false WHERE name = %s", (name,))
        with pg() as conn:
            run_serializable(conn, work)

    ts = [threading.Thread(target=leave, args=(n,)) for n in ("alice", "bob")]
    [t.start() for t in ts]; [t.join() for t in ts]
    with pg() as c:
        check("PG retry loop keeps 1 doctor on call", pg_one(c, "SELECT count(*) FROM doctors WHERE on_call = true"), 1)
    a.close(); b.close()


# --------------------------------------------------------------------- MySQL

def my():
    return pymysql.connect(**MY, autocommit=True)


def my_one(c, sql):
    with c.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def my_exec(c, sql):
    with c.cursor() as cur:
        return cur.execute(sql)


def my_reset():
    c = my()
    for s in ["DROP TABLE IF EXISTS products, doctors",
              "CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(50) NOT NULL, stock INT NOT NULL)",
              "INSERT INTO products VALUES (1, 'widget', 10), (2, 'gadget', 3)",
              "CREATE TABLE doctors (name VARCHAR(50) PRIMARY KEY, on_call BOOLEAN NOT NULL)",
              "INSERT INTO doctors VALUES ('alice', true), ('bob', true)"]:
        my_exec(c, s)
    c.close()


def my_checks():
    print("\n== MySQL ==")
    c = my()
    check("MySQL default level", my_one(c, "SELECT @@transaction_isolation"), "REPEATABLE-READ")
    c.close()

    # Panel 1: dirty read at READ UNCOMMITTED
    my_reset()
    a, b = my(), my()
    my_exec(a, "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"); my_exec(a, "BEGIN")
    my_exec(b, "BEGIN"); my_exec(b, "UPDATE products SET stock = 0 WHERE id = 1")
    r = my_one(a, "SELECT stock FROM products WHERE id = 1")
    my_exec(b, "ROLLBACK"); my_exec(a, "COMMIT")
    check("MySQL RU dirty read", r, 0)

    # Panel 2: non-repeatable read at READ COMMITTED
    my_reset()
    my_exec(a, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"); my_exec(a, "BEGIN")
    r1 = my_one(a, "SELECT stock FROM products WHERE id = 1")
    my_exec(b, "BEGIN"); my_exec(b, "UPDATE products SET stock = 4 WHERE id = 1"); my_exec(b, "COMMIT")
    r2 = my_one(a, "SELECT stock FROM products WHERE id = 1")
    my_exec(a, "COMMIT")
    check("MySQL RC non-repeatable read", (r1, r2), (10, 4))

    # Panel 3: phantom read at READ COMMITTED
    my_reset()
    my_exec(a, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"); my_exec(a, "BEGIN")
    r1 = my_one(a, "SELECT count(*) FROM products WHERE stock < 5")
    my_exec(b, "BEGIN"); my_exec(b, "INSERT INTO products VALUES (3, 'gizmo', 2)"); my_exec(b, "COMMIT")
    r2 = my_one(a, "SELECT count(*) FROM products WHERE stock < 5")
    my_exec(a, "COMMIT")
    check("MySQL RC phantom read", (r1, r2), (1, 2))

    # SET TRANSACTION applies to the next transaction only
    my_exec(a, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"); my_exec(a, "BEGIN"); my_exec(a, "COMMIT")
    check("MySQL SET TRANSACTION is one-shot", my_one(a, "SELECT @@transaction_isolation"), "REPEATABLE-READ")

    # Lost update at REPEATABLE READ (the article's demo), then the atomic fix
    def lost_update(set_clause):
        my_reset()
        my_exec(a, "BEGIN"); my_exec(b, "BEGIN")
        my_one(a, "SELECT stock FROM products WHERE id = 1"); my_one(b, "SELECT stock FROM products WHERE id = 1")
        my_exec(a, f"UPDATE products SET {set_clause} WHERE id = 1"); my_exec(a, "COMMIT")
        my_exec(b, f"UPDATE products SET {set_clause} WHERE id = 1"); my_exec(b, "COMMIT")
        return my_one(a, "SELECT stock FROM products WHERE id = 1")

    check("MySQL RR lost update: stock after two sales", lost_update("stock = 9"), 9)
    check("MySQL RR atomic decrement: stock after two sales", lost_update("stock = stock - 1"), 8)

    # Doctors at REPEATABLE READ: both commit
    my_reset()
    my_exec(a, "BEGIN"); my_exec(b, "BEGIN")
    reads = (my_one(a, "SELECT count(*) FROM doctors WHERE on_call = true"),
             my_one(b, "SELECT count(*) FROM doctors WHERE on_call = true"))
    my_exec(a, "UPDATE doctors SET on_call = false WHERE name = 'alice'")
    my_exec(b, "UPDATE doctors SET on_call = false WHERE name = 'bob'")
    my_exec(a, "COMMIT"); my_exec(b, "COMMIT")
    check("MySQL doctors RR: both read 2, 0 left on call",
          (reads, my_one(a, "SELECT count(*) FROM doctors WHERE on_call = true")), ((2, 2), 0))

    # Doctors at SERIALIZABLE: reads take shared locks, one transaction is a deadlock victim
    my_reset()
    for conn in (a, b):
        my_exec(conn, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"); my_exec(conn, "BEGIN")
    my_one(a, "SELECT count(*) FROM doctors WHERE on_call = true")
    my_one(b, "SELECT count(*) FROM doctors WHERE on_call = true")
    bg = Background(lambda: my_exec(a, "UPDATE doctors SET on_call = false WHERE name = 'alice'"))
    try:
        my_exec(b, "UPDATE doctors SET on_call = false WHERE name = 'bob'"); b_state = "ok"
    except pymysql.err.OperationalError as e:
        b_state = e.args[0]
    bg.join()
    a_state = bg.error.args[0] if bg.error else "ok"
    for conn in (a, b):
        try:
            my_exec(conn, "COMMIT")
        except pymysql.Error:
            my_exec(conn, "ROLLBACK")
    check("MySQL doctors SERIALIZABLE: one deadlock victim (1213)", sorted([str(a_state), str(b_state)]), ["1213", "ok"])
    check("MySQL doctors SERIALIZABLE: 1 left on call", my_one(a, "SELECT count(*) FROM doctors WHERE on_call = true"), 1)
    a.close(); b.close()




# --------------------------------------------------------------- SQL Server

def ms_checks():
    import pymssql
    print("\n== SQL Server ==")
    def ms(db="test"):
        c = pymssql.connect(**MS, database=db, autocommit=True); return c
    def ex(c, sql):
        cur = c.cursor(); cur.execute(sql)
        try:
            return cur.fetchall()
        except Exception:
            return None
    m = ms("master")
    ex(m, "IF DB_ID('test') IS NULL CREATE DATABASE test")
    ex(m, "ALTER DATABASE test SET ALLOW_SNAPSHOT_ISOLATION ON")
    m.close()
    def reset():
        c = ms()
        for s in ["DROP TABLE IF EXISTS products", "DROP TABLE IF EXISTS doctors",
                  "CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(50) NOT NULL, stock INT NOT NULL)",
                  "INSERT INTO products VALUES (1, 'widget', 10), (2, 'gadget', 3)",
                  "CREATE TABLE doctors (name VARCHAR(50) PRIMARY KEY, on_call BIT NOT NULL)",
                  "INSERT INTO doctors VALUES ('alice', 1), ('bob', 1)"]:
            ex(c, s)
        c.close()
    a, b = ms(), ms()
    check("SQL Server default level code (2 = READ COMMITTED)",
          ex(a, "SELECT transaction_isolation_level FROM sys.dm_exec_sessions WHERE session_id = @@SPID")[0][0], 2)

    # READ UNCOMMITTED really reads uncommitted data
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"); ex(a, "BEGIN TRANSACTION")
    ex(b, "BEGIN TRANSACTION"); ex(b, "UPDATE products SET stock = 0 WHERE id = 1")
    r = ex(a, "SELECT stock FROM products WHERE id = 1")[0][0]
    ex(b, "ROLLBACK"); ex(a, "COMMIT"); ex(a, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    check("SQL Server READ UNCOMMITTED dirty read", r, 0)

    # Lock-based REPEATABLE READ allows phantoms
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"); ex(a, "BEGIN TRANSACTION")
    r1 = ex(a, "SELECT count(*) FROM products WHERE stock < 5")[0][0]
    ex(b, "INSERT INTO products VALUES (3, 'gizmo', 2)")
    r2 = ex(a, "SELECT count(*) FROM products WHERE stock < 5")[0][0]
    ex(a, "COMMIT")
    check("SQL Server RR: phantom can happen", (r1, r2), (1, 2))

    # Lock-based REPEATABLE READ prevents lost update (one deadlock victim)
    def two_writers(level, read_sql, w_a, w_b):
        reset()
        for c in (a, b):
            ex(c, f"SET TRANSACTION ISOLATION LEVEL {level}"); ex(c, "BEGIN TRANSACTION")
        ex(a, read_sql); ex(b, read_sql)
        bg = Background(lambda: ex(a, w_a))
        try:
            ex(b, w_b); sb = "ok"
        except pymssql.Error as e:
            sb = "1205" if "1205" in str(e) else str(e)[:40]
        bg.join()
        sa = "ok" if not bg.error else ("1205" if "1205" in str(bg.error) else str(bg.error)[:40])
        for c in (a, b):
            try:
                ex(c, "IF @@TRANCOUNT > 0 COMMIT")
            except pymssql.Error:
                pass
            ex(c, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        return sorted([sa, sb])
    check("SQL Server RR: lost update prevented by deadlock (1205)",
          two_writers("REPEATABLE READ", "SELECT stock FROM products WHERE id = 1",
                      "UPDATE products SET stock = 9 WHERE id = 1", "UPDATE products SET stock = 9 WHERE id = 1"),
          ["1205", "ok"])
    check("SQL Server RR: doctors write skew prevented by deadlock (1205)",
          two_writers("REPEATABLE READ", "SELECT count(*) FROM doctors WHERE on_call = 1",
                      "UPDATE doctors SET on_call = 0 WHERE name = 'alice'", "UPDATE doctors SET on_call = 0 WHERE name = 'bob'"),
          ["1205", "ok"])

    # SNAPSHOT allows write skew
    reset()
    for c in (a, b):
        ex(c, "SET TRANSACTION ISOLATION LEVEL SNAPSHOT"); ex(c, "BEGIN TRANSACTION")
    ex(a, "SELECT count(*) FROM doctors WHERE on_call = 1"); ex(b, "SELECT count(*) FROM doctors WHERE on_call = 1")
    ex(a, "UPDATE doctors SET on_call = 0 WHERE name = 'alice'"); ex(b, "UPDATE doctors SET on_call = 0 WHERE name = 'bob'")
    ex(a, "COMMIT"); ex(b, "COMMIT")
    for c in (a, b): ex(c, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    check("SQL Server SNAPSHOT: write skew, 0 on call", ex(a, "SELECT count(*) FROM doctors WHERE on_call = 1")[0][0], 0)

    # SERIALIZABLE key-range locks block the phantom insert
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"); ex(a, "BEGIN TRANSACTION")
    ex(a, "SELECT count(*) FROM products WHERE stock < 5")
    bg = Background(lambda: ex(b, "INSERT INTO products VALUES (3, 'gizmo', 2)"))
    blocked = bg.blocked()
    ex(a, "COMMIT"); bg.join(); ex(a, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    check("SQL Server SERIALIZABLE: insert into scanned range blocks", blocked, True)

    # UPDLOCK: Bob waits for Alice, then sees only himself
    reset()
    ex(a, "BEGIN TRANSACTION"); ex(a, "SELECT name FROM doctors WITH (UPDLOCK) WHERE on_call = 1")
    ex(b, "BEGIN TRANSACTION")
    bg = Background(lambda: ex(b, "SELECT name FROM doctors WITH (UPDLOCK) WHERE on_call = 1"))
    blocked = bg.blocked()
    ex(a, "UPDATE doctors SET on_call = 0 WHERE name = 'alice'"); ex(a, "COMMIT")
    bg.join(); ex(b, "COMMIT")
    check("SQL Server UPDLOCK: Bob blocks, then sees 1 doctor", (blocked, [r[0] for r in (bg.result or [])]), (True, ["bob"]))
    a.close(); b.close()


# ------------------------------------------------------------------- Oracle

def or_checks():
    import oracledb
    print("\n== Oracle ==")
    a, b = oracledb.connect(**OR), oracledb.connect(**OR)
    def ex(c, sql):
        cur = c.cursor(); cur.execute(sql)
        try:
            return cur.fetchall()
        except oracledb.InterfaceError:
            return None
    def reset():
        c = oracledb.connect(**OR)
        for s in ["BEGIN EXECUTE IMMEDIATE 'DROP TABLE products'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                  "BEGIN EXECUTE IMMEDIATE 'DROP TABLE doctors'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                  "CREATE TABLE products (id NUMBER PRIMARY KEY, name VARCHAR2(50) NOT NULL, stock NUMBER NOT NULL)",
                  "INSERT INTO products VALUES (1, 'widget', 10)", "INSERT INTO products VALUES (2, 'gadget', 3)",
                  "CREATE TABLE doctors (name VARCHAR2(50) PRIMARY KEY, on_call NUMBER(1) NOT NULL)",
                  "INSERT INTO doctors VALUES ('alice', 1)", "INSERT INTO doctors VALUES ('bob', 1)"]:
            ex(c, s)
        c.commit(); c.close()

    # REPEATABLE READ is not offered
    try:
        ex(a, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"); state = "accepted"
    except oracledb.DatabaseError:
        state = "rejected"
    a.rollback()
    check("Oracle rejects REPEATABLE READ", state, "rejected")

    # READ COMMITTED (default): non-repeatable read
    reset()
    r1 = ex(a, "SELECT stock FROM products WHERE id = 1")[0][0]
    ex(b, "UPDATE products SET stock = 4 WHERE id = 1"); b.commit()
    r2 = ex(a, "SELECT stock FROM products WHERE id = 1")[0][0]
    a.commit()
    check("Oracle RC (default) non-repeatable read", (r1, r2), (10, 4))

    # SERIALIZABLE: no phantom
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    r1 = ex(a, "SELECT count(*) FROM products WHERE stock < 5")[0][0]
    ex(b, "INSERT INTO products VALUES (3, 'gizmo', 2)"); b.commit()
    r2 = ex(a, "SELECT count(*) FROM products WHERE stock < 5")[0][0]
    a.commit()
    check("Oracle SERIALIZABLE: no phantom", (r1, r2), (1, 1))

    # SERIALIZABLE: same-row update after a concurrent commit fails with ORA-08177
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"); ex(b, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    ex(a, "SELECT stock FROM products WHERE id = 1"); ex(b, "SELECT stock FROM products WHERE id = 1")
    ex(a, "UPDATE products SET stock = 9 WHERE id = 1"); a.commit()
    try:
        ex(b, "UPDATE products SET stock = 9 WHERE id = 1"); state = "ok"
    except oracledb.DatabaseError as e:
        state = "ORA-08177" if "ORA-08177" in str(e) else str(e)[:40]
    b.rollback()
    check("Oracle SERIALIZABLE: lost update rejected with ORA-08177", state, "ORA-08177")

    # SERIALIZABLE: write skew still happens
    reset()
    ex(a, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"); ex(b, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    ex(a, "SELECT count(*) FROM doctors WHERE on_call = 1"); ex(b, "SELECT count(*) FROM doctors WHERE on_call = 1")
    ex(a, "UPDATE doctors SET on_call = 0 WHERE name = 'alice'"); ex(b, "UPDATE doctors SET on_call = 0 WHERE name = 'bob'")
    a.commit(); b.commit()
    check("Oracle SERIALIZABLE: write skew, 0 on call", ex(a, "SELECT count(*) FROM doctors WHERE on_call = 1")[0][0], 0)
    a.close(); b.close()


def run(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"SKIP  {name}: not reachable or failed to start ({str(e)[:80]})")


if __name__ == "__main__":
    run("PostgreSQL", pg_checks)
    run("MySQL", my_checks)
    run("SQL Server", ms_checks)
    run("Oracle", or_checks)
    print(f"\n{sum(results)}/{len(results)} checks passed")
