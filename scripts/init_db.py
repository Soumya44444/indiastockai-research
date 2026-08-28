"""One-time script: create all tables in the Supabase Postgres database."""
from app.data.db import engine
from app.data.models import Base

def main():
    print(f"Connecting to: {engine.url.host}")
    Base.metadata.create_all(engine)
    print("Tables created successfully:")
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")

if __name__ == "__main__":
    main()