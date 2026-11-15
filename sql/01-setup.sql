-- Tables used by every example in the article.
-- PostgreSQL and MySQL syntax. For SQL Server and Oracle, see the
-- per-engine syntax table in the article ("Running the examples on your engine").

CREATE TABLE products (
    id    INT PRIMARY KEY,
    name  VARCHAR(50) NOT NULL,
    stock INT NOT NULL
);
INSERT INTO products VALUES (1, 'widget', 10), (2, 'gadget', 3);

CREATE TABLE doctors (name VARCHAR(50) PRIMARY KEY, on_call BOOLEAN NOT NULL);
INSERT INTO doctors VALUES ('alice', true), ('bob', true);
