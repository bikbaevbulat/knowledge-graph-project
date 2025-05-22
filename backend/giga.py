# backend/giga.py
import os
import requests
import uuid
from gigachat import GigaChat

GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
GIGACHAT_TOKEN = os.getenv("GIGACHAT_TOKEN")
AUTHORIZATION_KEY = os.getenv("GIGACHAT_TOKEN")  # твой Authorization Key, а не токен
TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

giga = GigaChat(
   credentials=os.getenv("GIGACHAT_TOKEN"),
   verify_ssl_certs=False,
   model='GigaChat-2-Max',
   timeout=100
)


HEADERS = {
    "Authorization": f"Bearer {GIGACHAT_TOKEN}",
    "Content-Type": "application/json"
}

def get_access_token():
    headers = {
        "Authorization": f"Basic {AUTHORIZATION_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4())  # уникальный идентификатор запроса
    }

    payload={
    'scope': 'GIGACHAT_API_PERS'
    }
    
    response = requests.post(TOKEN_URL, headers=headers, data=payload, verify=False)
    response.raise_for_status()
    return response.json()["access_token"]

def extract_knowledge_graph(text: str) -> str:
    """
    Запрос к GigaChat API: извлечение сущностей и связей в виде графа
    """

    prompt = """Ты помощник по созданию графов знаний. 
    Проанализируй следующий текст и выдели сущности и связи между ними. 
    Верни JSON-массив с элементами, содержащими 'name', 'desc' и опционально 'relations' 
    Пример: [ {\"name\": \"Сколтех\", \"desc\": \"Институт...\", \"relations\": [{\"type\": \"СОТРУДНИЧАЕТ\", \"target\": \"МФТИ\"}] } ] 
    и ничего больше!\n""" + f"""{text}"""

    response = giga.chat(prompt)
    print("gigachat response", response)
    print("gigachat response type", type(response))
    return response.choices[0].message.content

def answer_semantic_query(query: str, graph_data: str) -> str:
    """
    Получить логически связанный ответ на основе текста и графа знаний
    """
    prompt = f"""Ответь на вопрос: "{query}" используя информацию из следующего графа знаний (в JSON). Не присылай ничего кроме ответа на вопрос!:
{graph_data}"""

    response = giga.chat(prompt)
    return response.choices[0].message.content
