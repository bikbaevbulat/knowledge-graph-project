import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="Семантический поиск на графах знаний",
    page_icon=":material/network_node:",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)

import requests
import time
from pyvis.network import Network
import streamlit.components.v1 as components
import os
import mgclient
from datetime import datetime
from streamlit_cookies_manager import EncryptedCookieManager
from jose import JWTError, jwt
import asyncio
import websockets
import json
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import docx
import re
import random

API_URL = os.getenv("API_URL", "http://localhost:8000")
cookies = EncryptedCookieManager(prefix="myapp_", password="esfgrrgerfewfwewef")

if not cookies.ready():
    st.stop()



st.title("🔍 Семантический поиск на графах знаний")

# Читаем токен из cookie или из session_state
if "token" not in st.session_state:
    st.session_state.token = cookies.get("token", None)
    if st.session_state.token:
        decoded_token = jwt.decode(st.session_state.token, key="secret", options={"verify_signature": False})
        is_admin = decoded_token.get("is_admin", False)
        st.session_state["is_admin"] = is_admin

if "show_graph" not in st.session_state:
    st.session_state.show_graph = False

def save_token(token: str, refresh_token: str):
    st.session_state.token = token
    st.session_state.refresh_token = refresh_token
    cookies["token"] = token
    cookies["refresh_token"] = refresh_token
    cookies.save()

def clear_token():
    st.session_state.token = None
    cookies["token"] = ""
    cookies.save()

def is_token_expired(token: str):
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
            return True
        return False
    except:
        return True
    
def auth_headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}

# Аутентификация
def login():
    st.subheader("Вход или регистрация")
    username = st.text_input("Имя пользователя")
    password = st.text_input("Пароль", type="password")

    if st.button("Войти"):
        r = requests.post(f"{API_URL}/login", json={"username": username, "password": password})
        if r.status_code == 200:
            st.session_state.token = r.json()["access_token"]
            st.session_state.refresh_token = r.json()["refresh_token"]
            refresh_token = r.json()["refresh_token"]
            decoded_token = jwt.decode(r.json()["access_token"], key="secret", options={"verify_signature": False})
            is_admin = decoded_token.get("is_admin", False)
            st.session_state["is_admin"] = is_admin
            save_token(st.session_state.token, refresh_token)
            st.rerun()
        else:
            st.error("Ошибка входа")

    if st.button("Регистрация"):
        r = requests.post(f"{API_URL}/register", json={"username": username, "password": password})
        if r.status_code == 200:
            st.success("Успешная регистрация. Теперь войдите.")
        else:
            st.error("Ошибка регистрации")

def logout():
    clear_token()
    st.rerun()

def get_color_for_types(types):
    """Генерируем словарь type -> цвет (hex)"""
    colors = {}
    for t in types:
        # Генерируем случайный цвет в hex формате
        colors[t] = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    return colors

def render_graph(graph_id: int, placeholder: st.delta_generator.DeltaGenerator):

    show_schema = st.checkbox("Посмотреть схему типов", value=False)

    with st.spinner("Рисуем граф..."):
        conn = mgclient.connect(host="memgraph", port=7687)
        cursor = conn.cursor()
        cursor.execute(
            """
            MATCH (a:Entity {graph_id: $graph_id})-[r]->(b:Entity {graph_id: $graph_id})
            RETURN a.name, type(r), b.name
            """,
            {"graph_id": graph_id}
        )
        rows = cursor.fetchall()
        print('получено из memgraph', rows)

        if not rows:
            with placeholder:
                st.info("В этом графе знаний пока нет данных")
            return
    
        # Получаем все узлы с типами
        cursor.execute(
            """
            MATCH (n:Entity {graph_id: $graph_id})
            RETURN n.name, n.type
            """,
            {"graph_id": graph_id}
        )
        nodes = cursor.fetchall()
        print('Получаем все узлы с типами', nodes)

        name_to_type = {}
        for row in nodes:
            if len(row) != 2:
                print("⚠️ Unexpected row format:", row)
                continue
            name, ntype = row
            name_to_type[name] = ntype or "Другое"
        all_types = sorted(set(name_to_type.values()))


        # Сопоставляем каждому типу свой цвет
        type_colors = get_color_for_types(all_types)

        edge_color = "#878D95"
        net = Network(height="500px", width="100%", notebook=False, directed=True)





        if show_schema:
            # Схема типов
            edge_types = set()
            for src, rel, tgt in rows:
                src_type = name_to_type.get(src, "Другое")
                tgt_type = name_to_type.get(tgt, "Другое")
                if src_type != tgt_type:
                    edge_types.add((src_type, rel, tgt_type))

            for t in all_types:
                net.add_node(t, label=t, shape="box", color=type_colors[t])

            for src_t, rel, tgt_t in edge_types:
                net.add_edge(src_t, tgt_t, label=rel, arrows="to", color=edge_color)

        else:
            # Обычный граф: сущности и связи
            for src, rel, tgt in rows:
                try:
                    if not isinstance(src, (str, int)):
                        continue
                    if not isinstance(tgt, (str, int)):
                        continue

                    net.add_node(src, label=src, color=type_colors.get(name_to_type.get(src, "Другое")))
                    net.add_node(tgt, label=tgt, color=type_colors.get(name_to_type.get(tgt, "Другое")))
                    net.add_edge(src, tgt, label=rel, arrows="to", color=edge_color)
                except Exception as e:
                    st.error(f"Ошибка при добавлении ребра {src} → {tgt}: {e}")
            
        net.save_graph("graph.html")
        # Используем placeholder для вставки графа в нужное место
        with placeholder:
            components.html(open("graph.html", "r", encoding="utf-8").read(), height=550)

        st.session_state.show_graph = True
        st.session_state.last_graph_id = graph_id


async def wait_for_graph_and_render(task_id, graph_id):
    placeholder = st.empty()
    uri = f"ws://backend:8000/ws/graph/{task_id}"  # адрес WebSocket FastAPI

    try:
        async with websockets.connect(uri) as websocket:
            placeholder.info("Получение статуса загрузки...")

            while True:
                message = await websocket.recv()
                data = json.loads(message)

                status = data.get("status")
                chunks_total = data.get("chunks_total")
                chunks_done = data.get("chunks_done")
                if status == "SUCCESS":
                    placeholder.success("✅ Граф построен!")
                    render_graph(graph_id, graph_placeholder)
                    break
                elif status == "FAILURE":
                    placeholder.error("❌ Ошибка при построении графа.")
                    break
                else:
                    placeholder.info(f"⏳ Статус: {status}, Всего частей текста: {chunks_total}, Обработанных частей текста: {chunks_done}")
    except Exception as e:
        placeholder.error(f"Ошибка WebSocket: {str(e)}")

async def wait_answer(task_id: str, graph_id: int):
    uri = f"ws://backend:8000/ws/answer/{task_id}"
    try:
        async with websockets.connect(uri) as websocket:
            with st.spinner("⏳ Ожидание ответа..."):
                while True:
                    msg = await websocket.recv()
                    data = json.loads(msg)
                    if data["status"] == "SUCCESS":
                        st.markdown("**🧠 Ответ на запрос:**")
                        st.text_area("Ответ", value=data["answer"], height=200)
                        break
                    elif data["status"] == "FAILURE":
                        st.error("❌ Ошибка при выполнении задачи.")
                        break
                    else:
                        st.info(f"Статус: {data['status']}")
    except Exception as e:
        st.error(f"Ошибка WebSocket: {e}")


def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = "\n".join([page.get_text() for page in doc])
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    text = "\n".join([para.text for para in doc.paragraphs])
    return text

def extract_text_from_url(url):
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        # Убираем скрипты и стили
        for s in soup(["script", "style"]):
            s.decompose()
        text = soup.get_text()
        return re.sub(r'\s+', ' ', text.strip())
    except Exception as e:
        return f"Ошибка при загрузке страницы: {e}"


if not st.session_state.token:
    login()
    st.stop()



# Выбор страницы
nav_options = ["Поиск", "История"]
if st.session_state.get("is_admin"):
    nav_options.append("Управление пользователями")
page = st.sidebar.radio("Навигация", nav_options)



if page == "Поиск":
    graph_placeholder = st.empty()
    # Получение и выбор графов
    st.sidebar.header("Граф знаний")
    r = requests.get(f"{API_URL}/graphs/", headers=auth_headers())
    graphs = r.json()
    graph_titles = [g["title"] for g in graphs]
    graph_ids = [g["id"] for g in graphs]
    graph_is_tatar = [g["is_tatar"] for g in graphs]

    if graph_ids:
        # Инициализация, если ключа еще нет
        if "selected_graph" not in st.session_state or st.session_state.selected_graph not in graph_ids:
            st.session_state.selected_graph = graph_ids[0]

        # Найдем индекс для selectbox, чтобы выбрать правильный элемент
        default_index = graph_ids.index(st.session_state.selected_graph)
        selected_graph = st.sidebar.selectbox("Выберите граф", graph_titles, index=default_index)

        # Обновляем st.session_state.selected_graph при изменении выбора
        new_selected_graph_id = graph_ids[graph_titles.index(selected_graph)]
        if new_selected_graph_id != st.session_state.selected_graph:
            st.session_state.selected_graph = new_selected_graph_id
            st.session_state.last_graph_id = new_selected_graph_id
            st.rerun()  # Немедленно обновляем страницу
        selected_index = graph_ids.index(new_selected_graph_id)

        # Показываем информацию про язык
        if graph_is_tatar[selected_index]:
            st.write("Язык графа: татарский")
        else:
            st.write("Язык графа: русский")

        # Удаление графа
        if st.sidebar.button("Удалить выбранный граф"):
            graph_id_to_delete = st.session_state.selected_graph
            if graph_id_to_delete is not None:
                r = requests.delete(f"{API_URL}/graphs/{graph_id_to_delete}", headers=auth_headers())
                if r.status_code == 204:
                    st.sidebar.success(f"Граф '{selected_graph}' удалён")
                    # Обновляем список
                    r = requests.get(f"{API_URL}/graphs/", headers=auth_headers())
                    graphs = r.json()
                    graph_titles = [g["title"] for g in graphs]
                    graph_ids = [g["id"] for g in graphs]
                    if st.session_state.selected_graph not in graph_ids:
                        st.session_state.selected_graph = graph_ids[0] if graph_ids else None
                    st.rerun()
                else:
                    st.sidebar.error("Ошибка при удалении графа")
    else:
        st.sidebar.warning("Нет доступных графов. Сначала создайте граф.")
        st.session_state.selected_graph = None


    # Очистка перед отрисовкой поля
    if st.session_state.get("clear_new_graph_title", False):
        st.session_state["new_graph_title"] = ""
        st.session_state["clear_new_graph_title"] = False

    # Создание нового графа
    st.sidebar.subheader("Создание графа")
    new_graph = st.sidebar.text_input("Название нового графа", key="new_graph_title")
    is_tatar = st.sidebar.checkbox("Татарский язык", value=False)

    if st.sidebar.button("Создать"):
        payload = {
        "title": new_graph,
        "is_tatar": is_tatar
        }
        r = requests.post(f"{API_URL}/graphs/", json=payload, headers=auth_headers())
        if r.status_code == 200:
            st.sidebar.success("Граф создан!")
            st.session_state["clear_new_graph_title"] = True
            st.rerun()
        else:
            st.sidebar.error("Ошибка при создании")

    # Построение графа
    if st.button("Показать текущий граф знаний"):
        graph_id = st.session_state.get("selected_graph")
        if graph_id is None:
            st.error("Выберите граф перед построением.")
            st.stop()
        graph_id = int(graph_id)
        render_graph(graph_id, graph_placeholder)
    st.subheader("📄 Загрузка документа или ввод текста для добавления информации в граф")
    upload_method = st.radio("Выберите способ загрузки", ["Ввод вручную", "Загрузка файла", "Ссылка на сайт"])

    text = ""

    if upload_method == "Ввод вручную":
        text = st.text_area("Введите текст")

    elif upload_method == "Загрузка файла":
        file = st.file_uploader("Выберите PDF или Word файл", type=["pdf", "docx"])
        if file:
            if file.type == "application/pdf":
                text = extract_text_from_pdf(file)
            elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"]:
                text = extract_text_from_docx(file)
            st.text_area("Извлечённый текст", text, height=300)

    elif upload_method == "Ссылка на сайт":
        url = st.text_input("Введите URL")

        if "text_from_url" not in st.session_state:
            st.session_state["text_from_url"] = ""

        if st.button("Загрузить со страницы"):
            if url:
                extracted = extract_text_from_url(url)
                st.session_state["text_from_url"] = extracted

        text = st.session_state["text_from_url"]
        # всегда отображаем поле
        text = st.text_area("Извлечённый текст", text, height=300)

    if st.button("Сохранить и построить граф"):
        graph_id = st.session_state.get("selected_graph")
        if graph_id is None:
            st.error("Выберите граф перед построением.")
            st.stop()
        clean_text = text.strip()
        if not clean_text:
            st.error("Текст пустой. Введите или загрузите данные.")
            st.stop()
        try:
            graph_id = int(graph_id)
        except ValueError:
            st.error("Некорректный ID графа.")
            st.stop()
        r = requests.post(f"{API_URL}/process_text/", json={
            "text": text,
            "graph_id": graph_id
        }, headers=auth_headers())

        if r.status_code == 200:
            task_id = r.json()["task_id"]
            st.success("Запрос отправлен. Подождите создание графа...")
            # Асинхронный запуск WebSocket
            asyncio.run(wait_for_graph_and_render(task_id, graph_id))
        else:
            st.error("Ошибка при отправке текста")

    # Поиск
    st.subheader("🔎 Поиск по графу")
    query = st.text_input("Введите запрос")
    if st.button("Поиск"):

        #if is_token_expired(st.session_state.token):
        #    refresh_token = st.session_state.get("refresh_token") or cookies.get("refresh_token")
        #    if refresh_token:
        #        r = requests.post(f"{API_URL}/refresh", json={"refresh_token": refresh_token})
        #        if r.status_code == 200:
        #            new_token = r.json()["access_token"]
        #            save_token(new_token, refresh_token)
        #        else:
        #            st.warning("Сессия истекла, войдите снова.")
        #            clear_token()
        #            st.rerun()

        r = requests.post(f"{API_URL}/search/", json={
            "query": query,
            "graph_id": st.session_state.selected_graph
        }, headers=auth_headers())

        if r.status_code == 200:
            st.session_state.show_graph = True
            st.session_state.last_graph_id = st.session_state.selected_graph
            task_id = r.json()["task_id"]
            asyncio.run(wait_answer(task_id, st.session_state.selected_graph))

        else:
            st.error("Ошибка при выполнении запроса")
    if st.session_state.get("show_graph") and st.session_state.get("last_graph_id"):
        render_graph(st.session_state.last_graph_id, graph_placeholder)

elif page == "История":
    st.subheader("📜 История запросов")
    r = requests.get(f"{API_URL}/history/", headers=auth_headers())
    if r.status_code == 200:
        history = r.json()
        if not history:
            st.info("История запросов пуста.")
        else:
            for item in history:
                dt = datetime.fromisoformat(item['created_at'])
                formatted_date = dt.strftime("%d.%m.%Y %H:%M")
                with st.expander(f"{formatted_date} — 📘 {item['graph_title']}"):
                    st.markdown(f"**📝 Запрос:**\n\n{item['query']}")
                    st.markdown(f"**🧠 Ответ:**\n\n{item['response']}")
    else:
        st.error("Ошибка загрузки истории.")

elif page == "Управление пользователями" and st.session_state.get("is_admin"):
    st.subheader("👥 Управление пользователями")

    r = requests.get(f"{API_URL}/users/", headers=auth_headers())
    if r.status_code == 200:
        users = r.json()
        if not users:
            st.info("Нет зарегистрированных пользователей.")
        else:
            for user in users:
                with st.expander(f"👤 {user['username']} (id: {user['id']})"):
                    col1, col2 = st.columns([1, 2])
                    
                    with col1:
                        new_pass = st.text_input(f"Новый пароль для {user['username']}", type="password", key=f"pwd_{user['id']}")
                        if st.button(f"🔐 Сменить пароль", key=f"chg_{user['id']}"):
                            if new_pass:
                                pwd_r = requests.post(
                                    f"{API_URL}/users/{user['id']}/password",
                                    json={"new_password": new_pass},
                                    headers=auth_headers()
                                )
                                if pwd_r.status_code == 200:
                                    st.success("Пароль обновлён")
                                else:
                                    st.error("Ошибка при смене пароля")
                            else:
                                st.warning("Введите новый пароль")

                    with col2:
                        if st.button(f"❌ Удалить пользователя", key=f"del_{user['id']}"):
                            del_r = requests.delete(f"{API_URL}/users/{user['id']}", headers=auth_headers())
                            if del_r.status_code == 204:
                                st.success(f"Пользователь {user['username']} удалён")
                                st.rerun()
                            else:
                                st.error("Ошибка при удалении пользователя")
    else:
        st.error("Ошибка загрузки пользователей")

# Кнопка "Выйти" внизу sidebar
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Выйти"):
    logout()