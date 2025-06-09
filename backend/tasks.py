# backend/tasks.py
from celery import Celery
from backend import giga, crud, database
from sqlalchemy.orm import Session
import mgclient
import os
from gqlalchemy import Memgraph
import json 
import redis
from sentence_transformers import SentenceTransformer
import numpy as np
import base64
import networkx as nx
from crud import get_graph_by_id


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
mg = Memgraph(host='memgraph', port=7687)
redis_client = redis.Redis(host='redis', port=6379, db=0)

embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')


celery_app = Celery(
    'tasks',
    broker='redis://redis:6379/0',            # очередь задач
    backend='redis://redis:6379/1',           # <- это нужно для хранения результатов
)
def get_memgraph_connection():
    return mgclient.connect(host="memgraph", port=7687)

def encode_vector(vector):
    return base64.b64encode(np.array(vector, dtype=np.float32).tobytes()).decode()


def get_embedding(text: str):
    return embedding_model.encode(text, normalize_embeddings=True).tolist()

def split_text_by_overlap(text: str, chunk_size: int = 1000, overlap: int = 150):
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

@celery_app.task(bind=True)
def process_text_task(self, text: str, graph_id: int, user_id: int):

    db: Session = next(database.get_db())
    graph = get_graph_by_id(db, graph_id)
    is_tatar = graph.is_tatar if graph else False
    db.close()
    
    chunks = split_text_by_overlap(text, chunk_size=1000, overlap=150)
    total_chunks = len(chunks)
    processed_chunks = 0

    all_entities = []

    for idx, chunk in enumerate(chunks):
        try:
            response = giga.extract_knowledge_graph(chunk, is_tatar)

            raw = response.strip('`').replace('json\n', '', 1)
            graph_list = json.loads(raw)
            all_entities.extend(graph_list)
        except Exception as e:
            print(f"Ошибка при обработке чанка {idx+1}: {e}")
        finally:
            processed_chunks += 1
            redis_status = json.dumps({
                "status": "В процессе",
                "graph_id": graph_id,
                "chunks_total": total_chunks,
                "chunks_done": processed_chunks
            })
            redis_client.set(f"graph_built:{self.request.id}", redis_status)
            redis_client.publish(f"graph_built:{self.request.id}", redis_status)

    for ent in all_entities:
        try:
            # Проверка и нормализация типа
            raw_type = ent.get("type", "Other")
            if isinstance(raw_type, list):
                clean_type = raw_type[0] if raw_type else "Other"
            elif isinstance(raw_type, str):
                clean_type = raw_type
            else:
                clean_type = str(raw_type)
            emb = get_embedding(ent["desc"] or ent["name"])
            emb_b64 = encode_vector(emb)
            mg.execute(
                """
                MERGE (e:Entity {name: $name, graph_id: $graph_id})
                SET e.description = $desc,
                e.embedding = $embedding,
                e.type = $type
                """,
                {"name": ent["name"], "desc": ent["desc"], "type": clean_type, "graph_id": graph_id, "embedding": emb_b64}
            )
        except Exception as e:
            print(f"Ошибка при создании узла: {e}")

    # Этот фрагмент перебирает все связи (relations) для каждой сущности (ent) и создаёт их в графе, при необходимости автоматически создавая недостающие узлы
    # потому что GigaChat часто упоминает связи с сущностями, которые не описывает отдельно, и тогда узел b не создаётся на предыдущем этапе (узлы с описанием и эмбеддингами).
    for ent in all_entities:
        if "relations" in ent:
            for rel in ent["relations"]:
                try:
                    mg.execute(
                        f"""
                        MERGE (a:Entity {{name: $from, graph_id: $graph_id}})
                        ON CREATE SET a.description = '', a.embedding = ''
                        MERGE (b:Entity {{name: $to, graph_id: $graph_id}})
                        ON CREATE SET b.description = '', b.embedding = ''
                        MERGE (a)-[r:`{rel['type']}` {{graph_id: $graph_id}}]->(b)
                        """,
                        {"from": ent["name"], "to": rel["target"], "graph_id": graph_id}
                    )
                except Exception as e:
                    print(f"Ошибка при создании отношения {rel['type']}: {e}")

    status_data = json.dumps({
        "status": "SUCCESS",
        "graph_id": graph_id,
        "chunks_total": total_chunks,
        "chunks_done": processed_chunks
    })
    redis_client.set(f"graph_built:{self.request.id}", status_data)
    redis_client.publish(f"graph_built:{self.request.id}", status_data)

    return {"status": "success", "graph_id": graph_id}


@celery_app.task(bind=True)
def search_graph_task(self, query: str, graph_id: int, user_id: int):
    db: Session = next(database.get_db())
    graph = get_graph_by_id(db, graph_id)
    is_tatar = graph.is_tatar if graph else False
    db.close()
    task_id = self.request.id

    try:
        # Вектор запроса
        query_vec = embedding_model.encode(query, normalize_embeddings=True)

        # Получаем весь граф из Memgraph
        conn = get_memgraph_connection()
        cursor = conn.cursor()

        # Извлечение всех узлов графа с эмбендингами
        cursor.execute(
            "MATCH (e:Entity {graph_id: $graph_id}) RETURN e.name, e.description, e.embedding",
            {"graph_id": graph_id}
        )

        all_nodes = []
        # Кандидаты на отправку в LLM
        candidates = []
        for name, desc, emb_b64 in cursor.fetchall():
            if emb_b64:
                node_vec = np.frombuffer(base64.b64decode(emb_b64), dtype=np.float32)
                sim = np.dot(query_vec, node_vec)
                all_nodes.append((name, desc, sim))
                candidates.append((sim, name))
        # Топ-K узлов по семантической близости
        top_names = [name for _, name in sorted(candidates, reverse=True)[:10]]

    # Semantic Expansion: соседние узлы (до 2-х хопов)
        cursor.execute(
            """
                UNWIND $names AS name
                MATCH (a:Entity {graph_id: $graph_id}) 
                WHERE a.name = name
                MATCH (a)-[*1..2]-(b:Entity {graph_id: $graph_id})
                RETURN DISTINCT a.name, a.description, b.name, b.description
            """,
            {"graph_id": graph_id, "names": top_names}
        )

        node_set = set()
        edge_set = set()

        for a_name, a_desc, b_name, b_desc in cursor.fetchall():
            if isinstance(a_name, str) and isinstance(a_desc, str):
                node_set.add((a_name, a_desc))
            else:
                print("Пропущено: неверный тип данных", a_name, a_desc)
            if isinstance(b_name, str) and isinstance(b_desc, str):
                node_set.add((b_name, b_desc))
            else:
                print("Пропущено: неверный тип данных", b_name, b_desc)
            if isinstance(a_name, str) and isinstance(b_name, str):
                edge_set.add((a_name, b_name))
            else:
                print("Пропущено: неверный тип данных", a_name, b_name)    

        # PageRank (на клиенте, в NetworkX)
        G = nx.Graph()
        for name, desc in node_set:
            G.add_node(name, description=desc)
        for source, target in edge_set:
            G.add_edge(source, target)

        pagerank_scores = nx.pagerank(G)

        # Сортировка узлов по: alpha*similarity + beta*pagerank
        alpha, beta = 0.7, 0.3
        scored_nodes = []
        for name, desc, sim in all_nodes:
            pr = pagerank_scores.get(name, 0.0)
            score = alpha * sim + beta * pr
            scored_nodes.append((score, name))

        top_nodes = sorted(scored_nodes, reverse=True)[:20]
        final_names = [name for _, name in top_nodes]

        print('Узлы отправленные в gigachat', final_names)
        cursor.execute(
            """
            UNWIND $names AS name
            MATCH (a:Entity {name: name, graph_id: $graph_id})-[r]-(b:Entity {graph_id: $graph_id})
            RETURN a.name, a.description, type(r), b.name, b.description
            """,
            {"graph_id": graph_id, "names": final_names}
        )

        triples = []
        for a_name, a_desc, rel_type, b_name, b_desc in cursor.fetchall():
            triples.append({
                "source": a_name,
                "source_desc": a_desc,
                "relation": rel_type,
                "target": b_name,
                "target_desc": b_desc
            })
        print('Данные из графа, отправленные в gigachat', triples)
        cursor.close()
        conn.close()

        import json
        graph_data = json.dumps(triples)
        answer = giga.answer_semantic_query(query, graph_data, is_tatar)

        # Сохраняем ответ в историю
        db: Session = next(database.get_db())
        crud.save_query_result(db, query, answer, graph_id, user_id)
        print('ответ от гигачата в celery', answer)
        result = {"status": "SUCCESS", "answer": answer}
        redis_client.publish(f"answer:{task_id}", json.dumps(result))
        redis_client.set(f"answer:{task_id}", json.dumps(result))

        return result
    
    except Exception as e:
        redis_client.publish(f"answer:{task_id}", json.dumps({"status": "FAILURE", "error": str(e)}))
        redis_client.set(f"answer:{task_id}", json.dumps({"status": "FAILURE", "error": str(e)}))
        raise