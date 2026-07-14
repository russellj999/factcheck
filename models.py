from sqlalchemy import Column, Integer, Text, TIMESTAMP, text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Example(Base):
    __tablename__ = "example"

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(Text, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
