# backend/main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi import status
from sqlalchemy.orm import Session
from backend import models, database, crud
from backend.auth import get_current_user, UserIn, UserOut, authenticate_user, create_access_token
from pydantic import BaseModel
from backend.tasks import process_text_task, search_graph_task
from backend.crud import create_graph, get_user_graphs
from typing import List
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from backend.tasks import celery_app

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models.Base.metadata.create_all(bind=database.engine)

class GraphCreate(BaseModel):
    title: str

class GraphOut(BaseModel):
    id: int
    title: str

    class Config:
        orm_mode = True

@app.post("/graphs/", response_model=GraphOut)
def create_knowledge_graph(graph: GraphCreate, current_user=Depends(get_current_user), db: Session = Depends(database.get_db)):
    return create_graph(db, graph.title, current_user.id)

@app.get("/graphs/", response_model=List[GraphOut])
def list_knowledge_graphs(current_user=Depends(get_current_user), db: Session = Depends(database.get_db)):
    return get_user_graphs(db, current_user.id)

@app.post("/register", response_model=UserOut)
def register(user: UserIn, db: Session = Depends(database.get_db)):
    return crud.create_user(db, user)

@app.post("/login")
def login(user: UserIn, db: Session = Depends(database.get_db)):
    db_user = authenticate_user(db, user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": db_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

class TextInput(BaseModel):
    text: str
    graph_id: int

@app.post("/process_text/")
def process_text(input: TextInput, current_user=Depends(get_current_user)):
    task = process_text_task.delay(input.text, input.graph_id, current_user.id)
    return {"task_id": task.id}

class SearchInput(BaseModel):
    query: str
    graph_id: int

@app.post("/search/")
def search_graph(input: SearchInput, current_user=Depends(get_current_user)):
    task = search_graph_task.delay(input.query, input.graph_id, current_user.id)
    return {"task_id": task.id}

@app.get("/search_result/{task_id}")
def get_search_result(task_id: str):
    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {"status": "PENDING"}

    elif result.state == "SUCCESS":
        print('result из main', result)
        return {"status": "SUCCESS", "answer": result.result["answer"]}

    elif result.state == "FAILURE":
        raise HTTPException(status_code=500, detail="Ошибка выполнения задачи")

    return {"status": result.state}