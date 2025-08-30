"""Sample database fixtures for testing."""

from typing import List, Dict, Any, AsyncGenerator
from pathlib import Path
import tempfile

import pytest

from dbranching.database.adapter import DatabaseAdapter


class SampleDatabaseBuilder:
    """Builder for creating sample databases with test data."""

    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter

    async def create_blog_database(self) -> Dict[str, Any]:
        """Create a sample blog database with users, posts, and comments."""
        # Create tables
        await self.adapter.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                author_id INTEGER,
                published BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY,
                post_id INTEGER,
                author_id INTEGER,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id),
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE post_tags (
                post_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (post_id, tag_id),
                FOREIGN KEY (post_id) REFERENCES posts(id),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )
        """)

        # Insert sample users
        users_data = [
            ("john_doe", "john@example.com", "John Doe"),
            ("jane_smith", "jane@example.com", "Jane Smith"),
            ("bob_wilson", "bob@example.com", "Bob Wilson"),
            ("alice_brown", "alice@example.com", "Alice Brown"),
        ]

        for username, email, full_name in users_data:
            await self.adapter.execute(
                "INSERT INTO users (username, email, full_name) VALUES (?, ?, ?)",
                (username, email, full_name)
            )

        # Insert sample posts
        posts_data = [
            ("Getting Started with Database Branching", "This is a comprehensive guide...", 1, True),
            ("Advanced SQL Techniques", "Learn about window functions and CTEs...", 1, True),
            ("Python Best Practices", "Writing clean and maintainable Python code...", 2, True),
            ("Draft: Upcoming Features", "This post is still in draft...", 2, False),
            ("Database Design Patterns", "Common patterns for database design...", 3, True),
        ]

        for title, content, author_id, published in posts_data:
            await self.adapter.execute(
                "INSERT INTO posts (title, content, author_id, published) VALUES (?, ?, ?, ?)",
                (title, content, author_id, published)
            )

        # Insert sample tags
        tags_data = ["database", "sql", "python", "programming", "tutorial", "advanced"]
        for tag in tags_data:
            await self.adapter.execute("INSERT INTO tags (name) VALUES (?)", (tag,))

        # Insert sample post-tag associations
        post_tags_data = [
            (1, 1), (1, 2), (1, 5),  # Post 1: database, sql, tutorial
            (2, 2), (2, 6),          # Post 2: sql, advanced
            (3, 3), (3, 4), (3, 5),  # Post 3: python, programming, tutorial
            (5, 1), (5, 2), (5, 6),  # Post 5: database, sql, advanced
        ]

        for post_id, tag_id in post_tags_data:
            await self.adapter.execute(
                "INSERT INTO post_tags (post_id, tag_id) VALUES (?, ?)",
                (post_id, tag_id)
            )

        # Insert sample comments
        comments_data = [
            (1, 2, "Great article! Very helpful."),
            (1, 3, "Thanks for the detailed explanation."),
            (1, 4, "Looking forward to more content like this."),
            (2, 3, "The window functions section was particularly useful."),
            (3, 1, "Nice tips on code organization."),
            (3, 4, "Could you add more examples?"),
        ]

        for post_id, author_id, content in comments_data:
            await self.adapter.execute(
                "INSERT INTO comments (post_id, author_id, content) VALUES (?, ?, ?)",
                (post_id, author_id, content)
            )

        return {
            "users": len(users_data),
            "posts": len(posts_data),
            "tags": len(tags_data),
            "post_tags": len(post_tags_data),
            "comments": len(comments_data),
        }

    async def create_ecommerce_database(self) -> Dict[str, Any]:
        """Create a sample e-commerce database with products, orders, and customers."""
        # Create tables
        await self.adapter.execute("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                parent_id INTEGER,
                FOREIGN KEY (parent_id) REFERENCES categories(id)
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price DECIMAL(10, 2) NOT NULL,
                stock_quantity INTEGER DEFAULT 0,
                category_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                total_amount DECIMAL(10, 2),
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                product_id INTEGER,
                quantity INTEGER,
                price DECIMAL(10, 2),
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

        # Insert sample data
        customers_data = [
            ("customer1@example.com", "John", "Customer", "+1-555-0101"),
            ("customer2@example.com", "Jane", "Buyer", "+1-555-0102"),
            ("customer3@example.com", "Bob", "Shopper", "+1-555-0103"),
        ]

        for email, first_name, last_name, phone in customers_data:
            await self.adapter.execute(
                "INSERT INTO customers (email, first_name, last_name, phone) VALUES (?, ?, ?, ?)",
                (email, first_name, last_name, phone)
            )

        categories_data = [
            ("Electronics", "Electronic devices and accessories", None),
            ("Books", "Books and educational materials", None),
            ("Clothing", "Apparel and accessories", None),
            ("Smartphones", "Mobile phones and accessories", 1),  # Child of Electronics
            ("Laptops", "Portable computers", 1),  # Child of Electronics
        ]

        for name, description, parent_id in categories_data:
            await self.adapter.execute(
                "INSERT INTO categories (name, description, parent_id) VALUES (?, ?, ?)",
                (name, description, parent_id)
            )

        products_data = [
            ("iPhone 13", "Latest iPhone model", 999.99, 50, 4),
            ("Samsung Galaxy S21", "Android smartphone", 799.99, 30, 4),
            ("MacBook Pro", "Professional laptop", 1999.99, 20, 5),
            ("Dell XPS 13", "Ultrabook laptop", 1299.99, 25, 5),
            ("Python Programming Book", "Learn Python programming", 39.99, 100, 2),
            ("T-Shirt", "Cotton t-shirt", 19.99, 200, 3),
        ]

        for name, description, price, stock, category_id in products_data:
            await self.adapter.execute(
                "INSERT INTO products (name, description, price, stock_quantity, category_id) VALUES (?, ?, ?, ?, ?)",
                (name, description, price, stock, category_id)
            )

        orders_data = [
            (1, 1039.98, "completed"),  # Customer 1
            (2, 1319.98, "pending"),    # Customer 2
            (1, 59.98, "completed"),    # Customer 1 again
        ]

        for customer_id, total, status in orders_data:
            await self.adapter.execute(
                "INSERT INTO orders (customer_id, total_amount, status) VALUES (?, ?, ?)",
                (customer_id, total, status)
            )

        order_items_data = [
            (1, 1, 1, 999.99),  # Order 1: iPhone
            (1, 6, 2, 19.99),   # Order 1: 2 T-shirts
            (2, 4, 1, 1299.99), # Order 2: Dell laptop
            (2, 6, 1, 19.99),   # Order 2: T-shirt
            (3, 5, 1, 39.99),   # Order 3: Book
            (3, 6, 1, 19.99),   # Order 3: T-shirt
        ]

        for order_id, product_id, quantity, price in order_items_data:
            await self.adapter.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                (order_id, product_id, quantity, price)
            )

        return {
            "customers": len(customers_data),
            "categories": len(categories_data),
            "products": len(products_data),
            "orders": len(orders_data),
            "order_items": len(order_items_data),
        }

    async def create_analytics_database(self) -> Dict[str, Any]:
        """Create a sample analytics database with time-series data."""
        # Create tables
        await self.adapter.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                user_id TEXT,
                session_id TEXT,
                page_url TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                properties TEXT  -- JSON-like string for additional data
            )
        """)

        await self.adapter.execute("""
            CREATE TABLE daily_metrics (
                date DATE PRIMARY KEY,
                page_views INTEGER DEFAULT 0,
                unique_visitors INTEGER DEFAULT 0,
                bounce_rate DECIMAL(5, 2) DEFAULT 0.0,
                avg_session_duration INTEGER DEFAULT 0  -- in seconds
            )
        """)

        # Insert sample events data
        import datetime
        import json

        base_date = datetime.datetime.now() - datetime.timedelta(days=30)
        events_data = []

        # Generate sample events over the last 30 days
        for day in range(30):
            current_date = base_date + datetime.timedelta(days=day)
            
            # Generate events for this day
            for hour in range(24):
                for event_num in range(10):  # 10 events per hour
                    timestamp = current_date.replace(
                        hour=hour,
                        minute=event_num * 6,  # Spread throughout the hour
                        second=0,
                        microsecond=0
                    )
                    
                    user_id = f"user_{(day * 24 + hour + event_num) % 100}"
                    session_id = f"session_{day}_{hour}_{event_num // 5}"
                    
                    # Different event types
                    if event_num % 10 == 0:
                        event_type = "page_view"
                        page_url = "/home"
                    elif event_num % 5 == 0:
                        event_type = "click"
                        page_url = "/products"
                    elif event_num % 3 == 0:
                        event_type = "scroll"
                        page_url = "/blog"
                    else:
                        event_type = "page_view"
                        page_url = f"/page_{event_num % 5}"
                    
                    properties = json.dumps({
                        "browser": "chrome" if event_num % 2 == 0 else "firefox",
                        "device": "desktop" if event_num % 3 == 0 else "mobile",
                        "referrer": "google.com" if event_num % 4 == 0 else "direct"
                    })
                    
                    events_data.append((
                        event_type, user_id, session_id, page_url, timestamp, properties
                    ))

        # Insert events in batches
        batch_size = 100
        for i in range(0, len(events_data), batch_size):
            batch = events_data[i:i + batch_size]
            placeholders = ",".join(["(?, ?, ?, ?, ?, ?)"] * len(batch))
            flat_data = [item for event in batch for item in event]
            
            await self.adapter.execute(
                f"INSERT INTO events (event_type, user_id, session_id, page_url, timestamp, properties) VALUES {placeholders}",
                flat_data
            )

        # Insert sample daily metrics
        for day in range(30):
            date = (base_date + datetime.timedelta(days=day)).date()
            page_views = 200 + (day * 10)  # Trending up
            unique_visitors = 50 + (day * 2)
            bounce_rate = 45.5 + (day * 0.3)  # Slightly increasing
            avg_duration = 180 + (day * 5)  # Increasing engagement
            
            await self.adapter.execute(
                "INSERT INTO daily_metrics (date, page_views, unique_visitors, bounce_rate, avg_session_duration) VALUES (?, ?, ?, ?, ?)",
                (date, page_views, unique_visitors, bounce_rate, avg_duration)
            )

        return {
            "events": len(events_data),
            "daily_metrics": 30,
        }


@pytest.fixture
async def sample_blog_database(sqlite_adapter: DatabaseAdapter) -> Dict[str, Any]:
    """Create a sample blog database for testing."""
    builder = SampleDatabaseBuilder(sqlite_adapter)
    return await builder.create_blog_database()


@pytest.fixture
async def sample_ecommerce_database(sqlite_adapter: DatabaseAdapter) -> Dict[str, Any]:
    """Create a sample e-commerce database for testing."""
    builder = SampleDatabaseBuilder(sqlite_adapter)
    return await builder.create_ecommerce_database()


@pytest.fixture
async def sample_analytics_database(sqlite_adapter: DatabaseAdapter) -> Dict[str, Any]:
    """Create a sample analytics database for testing."""
    builder = SampleDatabaseBuilder(sqlite_adapter)
    return await builder.create_analytics_database()


def create_sample_config_file(temp_dir: Path, config_type: str = "sqlite") -> Path:
    """Create a sample configuration file for testing."""
    config_file = temp_dir / "dbranching.yaml"
    
    if config_type == "sqlite":
        config_content = f"""
database:
  type: sqlite
  database: {temp_dir / "test.db"}

storage:
  directory: {temp_dir / "snapshots"}
  compression: gzip

logging:
  level: INFO
"""
    elif config_type == "mysql":
        config_content = """
database:
  type: mysql
  host: localhost
  port: 3306
  database: testdb
  username: testuser
  password: testpass

storage:
  directory: /tmp/dbranching_snapshots
  compression: bzip2

logging:
  level: DEBUG
"""
    elif config_type == "postgresql":
        config_content = """
database:
  type: postgresql
  host: localhost
  port: 5432
  database: testdb
  username: testuser
  password: testpass

storage:
  directory: /tmp/dbranching_snapshots
  compression: lz4

logging:
  level: WARNING
"""
    else:
        raise ValueError(f"Unknown config type: {config_type}")
    
    config_file.write_text(config_content.strip())
    return config_file


def create_invalid_config_file(temp_dir: Path, error_type: str = "yaml") -> Path:
    """Create an invalid configuration file for error testing."""
    config_file = temp_dir / "invalid_dbranching.yaml"
    
    if error_type == "yaml":
        # Invalid YAML syntax
        config_content = """
database:
  type: sqlite
  database: /tmp/test.db
    invalid: yaml: [
"""
    elif error_type == "validation":
        # Valid YAML but invalid configuration
        config_content = """
database:
  type: invalid_database_type
  host: localhost

storage:
  compression: invalid_compression_type

logging:
  level: INVALID_LEVEL
"""
    elif error_type == "missing_required":
        # Missing required fields
        config_content = """
storage:
  directory: /tmp/snapshots

logging:
  level: INFO
# Missing required database section
"""
    else:
        raise ValueError(f"Unknown error type: {error_type}")
    
    config_file.write_text(config_content.strip())
    return config_file