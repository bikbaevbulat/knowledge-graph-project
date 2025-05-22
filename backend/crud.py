# backend/crud.py
from sqlalchemy.orm import Session
from backend import models, auth

def create_user(db: Session, user: auth.UserIn):
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(username=user.username, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, username: str, password: str):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return None
    return user

def create_graph(db: Session, title: str, user_id: int):
    graph = models.KnowledgeGraph(title=title, owner_id=user_id)
    db.add(graph)
    db.commit()
    db.refresh(graph)
    return graph

def save_query_result(db: Session, query: str, response: str, graph_id: int, user_id: int):
    record = models.SearchHistory(
        query=query,
        response=response,
        graph_id=graph_id,
        user_id=user_id
    )
    db.add(record)
    db.commit()

def get_user_graphs(db: Session, user_id: int):
    return db.query(models.KnowledgeGraph).filter(models.KnowledgeGraph.owner_id == user_id).all()
