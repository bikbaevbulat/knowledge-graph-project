# backend/main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi import status
from sqlalchemy.orm import Session
from backend import models, database, crud
from backend.auth import get_current_user, UserIn, UserOut, authenticate_user, create_access_token, create_refresh_token, is_admin_user, get_password_hash, PasswordChange
from pydantic import BaseModel
from backend.tasks import process_text_task, search_graph_task
from backend.crud import create_graph, get_user_graphs, get_user_history
from typing import List
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from backend.tasks import celery_app
from models import User
import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect, Body
import json
from typing import Optional
from jose import JWTError, jwt

# Инициализация приложения FastAPI
app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация базы данных
models.Base.metadata.create_all(bind=database.engine)

# Подключение к Redis (для WebSocket-уведомлений)
redis_client = redis.Redis(host="redis", port=6379, db=0)

# Модель графа для параметров
class GraphCreate(BaseModel):
    title: str
    is_tatar: Optional[bool] = False

class GraphOut(BaseModel):
    id: int
    title: str
    is_tatar: Optional[bool] = False
    
    class Config:
        orm_mode = True

# Модель текста для параметров
class TextInput(BaseModel):
    text: str
    graph_id: int

# Модель запроса для параметров
class SearchInput(BaseModel):
    query: str
    graph_id: int

# Создание графа знаний
@app.post("/graphs/", response_model=GraphOut)
def create_knowledge_graph(graph: GraphCreate, current_user=Depends(get_current_user), db: Session = Depends(database.get_db)):
    return create_graph(db, graph.title, current_user.id, graph.is_tatar)

# Получение списка графов пользователя
@app.get("/graphs/", response_model=List[GraphOut])
def list_knowledge_graphs(current_user=Depends(get_current_user), db: Session = Depends(database.get_db)):
    return get_user_graphs(db, current_user.id)

# Регистрация пользователя
@app.post("/register", response_model=UserOut)
def register(user: UserIn, db: Session = Depends(database.get_db)):
    return crud.create_user(db, user)

# Авторизация пользователя (выдача JWT токена)
@app.post("/login")
def login(user: UserIn, db: Session = Depends(database.get_db)):
    db_user = authenticate_user(db, user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": db_user.username, "is_admin": db_user.is_admin})
    refresh_token = create_refresh_token(data={"sub": db_user.username, "is_admin": db_user.is_admin})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}

# Обновление access токена по refresh токену
@app.post("/refresh")
def refresh_token(refresh_token: str = Body(...), db: Session = Depends(database.get_db)):
    try:
        payload = jwt.decode(refresh_token, key="secret", options={"verify_signature": False})
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = create_access_token(data={"sub": user.username, "is_admin": user.is_admin})
    return {"access_token": new_access_token}

"""
POST запрос на загрузку текста в граф знаний
Создает Celery задачу
Возвращает task_id, с помощью которого пользователь будет получать статус загрузки текста
"""
@app.post("/process_text/")
def process_text(input: TextInput, current_user=Depends(get_current_user)):
    task = process_text_task.delay(input.text, input.graph_id, current_user.id)
    return {"task_id": task.id}

# WebSocket для получения статуса загрузки текста в граф знаний
@app.websocket("/ws/graph/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()

    existing_status = await redis_client.get(f"graph_built:{task_id}")
    if existing_status:
        await websocket.send_json(json.loads(existing_status))
        return

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"graph_built:{task_id}")

    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await websocket.send_json(data)
                if data.get("status") in ("SUCCESS", "FAILURE"):
                    break
    except WebSocketDisconnect:
        await pubsub.unsubscribe(f"graph_built:{task_id}")
        await pubsub.close()

    finally:
        await pubsub.unsubscribe(f"graph_built:{task_id}")
        await pubsub.close()

"""
POST запрос на поиск по графу знаний
Создает Celery задачу
Возвращает task_id, с помощью которого пользователь будет получать статус поиска
"""
@app.post("/search/")
def search_graph(input: SearchInput, current_user=Depends(get_current_user)):
    task = search_graph_task.delay(input.query, input.graph_id, current_user.id)
    return {"task_id": task.id}

# WebSocket для получения ответа на запрос поиска
@app.websocket("/ws/answer/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()

    existing_status = await redis_client.get(f"answer:{task_id}")
    if existing_status:
        await websocket.send_json(json.loads(existing_status))
        return

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"answer:{task_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json(data)
                if data["status"] in {"SUCCESS", "FAILURE"}:
                    break
    except WebSocketDisconnect:
        print("WebSocket отключен")
    finally:
        await pubsub.unsubscribe(f"answer:{task_id}")
        await pubsub.close()

# Получение истории запросов пользователя
@app.get("/history/")
def get_history(current_user=Depends(get_current_user), db: Session = Depends(database.get_db)):
    history = get_user_history(db, current_user.id)
    return [
        {
            "query": item.query,
            "response": item.response,
            "created_at": item.created_at.isoformat(),
            "graph_title": item.graph.title if item.graph else "Без названия"
        }
        for item in history
    ]

# Удаление графа по id
@app.delete("/graphs/{graph_id}", status_code=204)
def delete_graph(graph_id: int, db: Session = Depends(database.get_db), current_user=Depends(get_current_user)):
    graph = crud.get_graph_by_id(db, graph_id)
    if not graph or graph.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Graph not found or not owned by user")
    crud.delete_graph(db, graph)
    return

# Получение списка всех пользователей
@app.get("/users/", response_model=List[UserOut])
def list_users(db: Session = Depends(database.get_db), current_user=Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return db.query(User).all()

# Удаление пользователя
@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(database.get_db), current_user=Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.delete(user)
    db.commit()
    return

# Смена пароля пользователя
@app.post("/users/{user_id}/password", status_code=200)
def change_user_password(user_id: int, payload: PasswordChange, db: Session = Depends(database.get_db), current_user=Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    # Здесь должен быть код для хэширования нового пароля, например:
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"detail": "Пароль успешно изменен"}