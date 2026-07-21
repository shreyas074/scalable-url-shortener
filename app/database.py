"""
Database configuration.

Uses SQLite for zero-setup local development. In a real production deployment
on AWS, you would swap SQLALCHEMY_DATABASE_URL for a DynamoDB or RDS/Postgres
connection string — the rest of the app (models, queries) would barely change
if you keep using an ORM-style access layer like this.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./shortener.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
