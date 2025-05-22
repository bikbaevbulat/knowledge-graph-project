# backend/models.py
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)

    graphs = relationship("KnowledgeGraph", back_populates="owner")

class KnowledgeGraph(Base):
    __tablename__ = "knowledge_graphs"

    id = Column(Integer, primary_key=True)
    title = Column(String(100))
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="graphs")
    queries = relationship("SearchHistory", back_populates="graph")

class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True)
    query = Column(Text)
    response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    graph_id = Column(Integer, ForeignKey("knowledge_graphs.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    graph = relationship("KnowledgeGraph", back_populates="queries")
