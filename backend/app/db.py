from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

url = make_url(settings.database_url)
is_sqlite = url.drivername.startswith("sqlite")
if is_sqlite and url.database and url.database != ":memory:":
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
