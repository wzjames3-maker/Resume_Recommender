from pymilvus import connections, Collection

for host in ["milvus", "resume-rag-milvus", "172.18.0.6"]:
    try:
        connections.connect(alias="default", host=host, port="19530")
        collection = Collection("resume_chunks")
        collection.load()
        import time
        time.sleep(1)
        total = collection.num_entities
        print(f"SUCCESS via {host}: {total} chunks")
        break
    except Exception as e:
        print(f"FAIL via {host}: {str(e)[:80]}")
        connections.disconnect("default")
