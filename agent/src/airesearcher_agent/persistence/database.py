from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Database:
    def __init__(self, url: str | URL, *, echo: bool = False) -> None:
        options: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
        rendered = str(url)
        if rendered.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if rendered in {"sqlite://", "sqlite:///:memory:"}:
                options["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **options)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.session() as session, session.begin():
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
