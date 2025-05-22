import streamlit as st
import requests
import time
from pyvis.network import Network
import streamlit.components.v1 as components
import os
import mgclient

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(layout="wide")
st.title("🔍 Семантический поиск на графах знаний")

if "token" not in st.session_state:
    st.session_state.token = None

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
            st.rerun()
        else:
            st.error("Ошибка входа")

    if st.button("Регистрация"):
        r = requests.post(f"{API_URL}/register", json={"username": username, "password": password})
        if r.status_code == 200:
            st.success("Успешная регистрация. Теперь войдите.")
        else:
            st.error("Ошибка регистрации")


def render_graph():
    with st.spinner("Рисуем граф..."):
        conn = mgclient.connect(host="memgraph", port=7687)
        cursor = conn.cursor()
        cursor.execute("MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name")
        rows = cursor.fetchall()
        print('получено из memgraph', rows)
        net = Network(height="500px", width="100%", notebook=False)
        for src, rel, tgt in rows:
            net.add_node(src, label=src)
            net.add_node(tgt, label=tgt)
            net.add_edge(src, tgt, label=rel)

        net.save_graph("graph.html")
        components.html(open("graph.html", "r", encoding="utf-8").read(), height=550)



if not st.session_state.token:
    login()
    st.stop()

# Получение и выбор графов
st.sidebar.header("Граф знаний")
r = requests.get(f"{API_URL}/graphs/", headers=auth_headers())
graphs = r.json()
graph_titles = [g["title"] for g in graphs]
graph_ids = [g["id"] for g in graphs]

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
else:
    st.sidebar.warning("Нет доступных графов. Сначала создайте граф.")
    st.session_state.selected_graph = None


# Создание нового графа
st.sidebar.subheader("Создание графа")
new_graph = st.sidebar.text_input("Название нового графа")
if st.sidebar.button("Создать"):
    r = requests.post(f"{API_URL}/graphs/", json={"title": new_graph}, headers=auth_headers())
    if r.status_code == 200:
        st.sidebar.success("Граф создан!")
        st.rerun()
    else:
        st.sidebar.error("Ошибка при создании")

# Построение графа
st.subheader("📄 Ввод текста для построения графа")
text = st.text_area("Введите текст")
if st.button("Сохранить и построить граф"):
    graph_id = st.session_state.get("selected_graph")
    if graph_id is None:
        st.error("Выберите граф перед построением.")
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
        st.success("Запрос отправлен. Подождите несколько секунд...")
        time.sleep(70)
        render_graph()  # 👈 отрисовываем граф сразу после построения
    else:
        st.error("Ошибка при отправке текста")

# Поиск
st.subheader("🔎 Поиск по графу")
query = st.text_input("Введите запрос")
if st.button("Поиск"):
    r = requests.post(f"{API_URL}/search/", json={
        "query": query,
        "graph_id": st.session_state.selected_graph
    }, headers=auth_headers())

    if r.status_code == 200:
        task_id = r.json()["task_id"]
        st.success("Запрос отправлен. Ждём ответа...")

        # Ожидаем результата
        with st.spinner("Обработка запроса..."):
            answer = None
            for _ in range(30):  # максимум 30 попыток (60 сек при sleep 2)
                res = requests.get(f"{API_URL}/search_result/{task_id}")
                data = res.json()

                if data["status"] == "SUCCESS":
                    answer = data.get("answer", "Ответ не найден.")
                    break
                elif data["status"] == "FAILURE":
                    st.error("Ошибка обработки запроса.")
                    break
                else:
                    time.sleep(1)

            if answer:
                st.markdown("**🧠 Ответ на запрос:**")
                st.text_area("Ответ", value=answer, height=200)

    else:
        st.error("Ошибка при выполнении запроса")