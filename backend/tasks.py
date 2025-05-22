# backend/tasks.py
from celery import Celery
from backend import giga, crud, database
from sqlalchemy.orm import Session
import mgclient
import os
from gqlalchemy import Memgraph
import json 

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
mg = Memgraph(host='memgraph', port=7687)
celery_app = Celery(
    'tasks',
    broker='redis://redis:6379/0',            # очередь задач
    backend='redis://redis:6379/1',           # <- это нужно для хранения результатов
)
def get_memgraph_connection():
    return mgclient.connect(host="memgraph", port=7687)

@celery_app.task
def process_text_task(text: str, graph_id: int, user_id: int):
    graph_str = giga.extract_knowledge_graph(text)
    print('graph_list до изменений', graph_str)
    print('строка для сравнения', "строкаФФФФФФФ")

    print('graph_list type  до изменений', type(graph_str))

    # Уберем обертку ```json и ```
    raw = graph_str.strip('`').replace('json\n', '', 1)
    graph_list = json.loads(raw)

    print('graph_list после изменений', graph_list)
    print('graph_list type после изменений', type(graph_list))
    

    for ent in graph_list:
        mg.execute(
            """
            MERGE (e:Entity {name: $name})
            SET e.description = $desc
            """,
            {"name": ent["name"], "desc": ent["desc"]}
        )
    for ent in graph_list:
        if "relations" in ent:
            for rel in ent["relations"]:
                mg.execute(
                    f"""
                    MATCH (a:Entity {{name: $from}}), (b:Entity {{name: $to}})
                    MERGE (a)-[:`{rel['type']}`]->(b)
                    """,
                    {"from": ent["name"], "to": rel["target"]}
            )
    """
    # Преобразуем JSON в Cypher (предполагается формат: [{source, relation, target}])
    data = graph_list

    conn = get_memgraph_connection()
    cursor = conn.cursor()

    for triple in data:
        source = triple.get("source")
        relation = triple.get("relation")
        target = triple.get("target")

        query = f
        MERGE (a:Entity {{name: "{source}"}})
        MERGE (b:Entity {{name: "{target}"}})
        MERGE (a)-[:{relation.upper()}]->(b)
        
        cursor.execute(query)

    cursor.close()
    conn.close()
    """
    return {"status": "success", "graph_id": graph_id}

@celery_app.task
def search_graph_task(query: str, graph_id: int, user_id: int):
    # Получаем весь граф из Memgraph
    conn = get_memgraph_connection()
    cursor = conn.cursor()

    cursor.execute("MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name")
    triples = [{"source": row[0], "relation": row[1], "target": row[2]} for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    import json
    graph_data = json.dumps(triples)
    answer = giga.answer_semantic_query(query, graph_data)

    # Сохраняем ответ в историю
    db: Session = next(database.get_db())
    crud.save_query_result(db, query, answer, graph_id, user_id)
    print('ответ от гигачата в celery', answer)
    return {"answer": answer}
