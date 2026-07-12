-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pgvector;

-- Create demo schema for testing
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255),
    country VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    total DECIMAL(10,2),
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    category VARCHAR(100),
    price DECIMAL(10,2),
    stock INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    stock INTEGER DEFAULT 0,
    warehouse VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    type VARCHAR(100),
    payload JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed demo data
INSERT INTO customers (name, email, country) 
SELECT 
    'Customer ' || i,
    'customer' || i || '@example.com',
    CASE (i % 5) WHEN 0 THEN 'US' WHEN 1 THEN 'UK' WHEN 2 THEN 'DE' WHEN 3 THEN 'FR' ELSE 'JP' END
FROM generate_series(1, 150000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO products (name, category, price, stock)
SELECT 
    'Product ' || i,
    CASE (i % 10) WHEN 0 THEN 'Electronics' WHEN 1 THEN 'Clothing' WHEN 2 THEN 'Food' ELSE 'Books' END,
    (random() * 1000)::numeric(10,2),
    (random() * 1000)::int
FROM generate_series(1, 10000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO orders (customer_id, total, status, created_at)
SELECT 
    (random() * 150000)::int + 1,
    (random() * 500)::numeric(10,2),
    CASE (random() * 3)::int WHEN 0 THEN 'pending' WHEN 1 THEN 'shipped' ELSE 'delivered' END,
    NOW() - (random() * interval '365 days')
FROM generate_series(1, 2400000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO inventory (product_id, stock, warehouse)
SELECT 
    (random() * 10000)::int + 1,
    (random() * 500)::int,
    CASE (random() * 3)::int WHEN 0 THEN 'NYC' WHEN 1 THEN 'LAX' ELSE 'ORD' END
FROM generate_series(1, 50000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO events (type, payload, created_at)
SELECT 
    CASE (random() * 5)::int WHEN 0 THEN 'login' WHEN 1 THEN 'purchase' WHEN 2 THEN 'logout' WHEN 3 THEN 'view' ELSE 'click' END,
    jsonb_build_object('user_id', (random() * 150000)::int, 'session', md5(random()::text)),
    NOW() - (random() * interval '90 days')
FROM generate_series(1, 5000000) AS i
ON CONFLICT DO NOTHING;

-- Reset pg_stat_statements
SELECT pg_stat_statements_reset();
