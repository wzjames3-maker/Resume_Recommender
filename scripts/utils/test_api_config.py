"""
智能招聘 RAG 推荐系统 - API 配置测试脚本

测试所有外部 API 连接
"""

import os
import sys
import httpx
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_llm_api():
    """测试 LLM API 连接"""
    print("\n" + "="*50)
    print("测试 LLM API (DeepSeek)")
    print("="*50)

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")

    print(f"URL: {base_url}")
    print(f"Model: {model}")
    print(f"API Key: {api_key[:10]}...")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "你好，请回复'OK'"}
                    ],
                    "max_tokens": 10,
                },
            )

            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                print(f"✅ LLM API 连接成功!")
                print(f"   响应: {content}")
                return True
            else:
                print(f"❌ LLM API 返回错误: {response.status_code}")
                print(f"   响应: {response.text}")
                return False

    except Exception as e:
        print(f"❌ LLM API 连接失败: {str(e)}")
        return False


def test_embedding_api():
    """测试 Embedding API 连接"""
    print("\n" + "="*50)
    print("测试 Embedding API (BGE-M3)")
    print("="*50)

    api_key = os.getenv("EMBEDDING_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL")
    model = os.getenv("EMBEDDING_MODEL")

    print(f"URL: {base_url}/embeddings")
    print(f"Model: {model}")
    print(f"API Key: {api_key[:10]}...")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": ["测试文本"],
                    "encoding_format": "float",
                },
            )

            if response.status_code == 200:
                result = response.json()
                embedding = result["data"][0]["embedding"]
                print(f"✅ Embedding API 连接成功!")
                print(f"   向量维度: {len(embedding)}")
                print(f"   前5个值: {embedding[:5]}")
                return True
            else:
                print(f"❌ Embedding API 返回错误: {response.status_code}")
                print(f"   响应: {response.text}")
                return False

    except Exception as e:
        print(f"❌ Embedding API 连接失败: {str(e)}")
        return False


def test_reranker_api():
    """测试 Reranker API 连接"""
    print("\n" + "="*50)
    print("测试 Reranker API (BGE-Reranker)")
    print("="*50)

    api_key = os.getenv("RERANKER_API_KEY")
    base_url = os.getenv("RERANKER_BASE_URL")
    model = os.getenv("RERANKER_MODEL")

    print(f"URL: {base_url}/rerank")
    print(f"Model: {model}")
    print(f"API Key: {api_key[:10]}...")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "query": "Java工程师",
                    "documents": [
                        "3年Java开发经验",
                        "5年Python开发经验",
                        "Java Spring Boot 后端工程师",
                    ],
                    "top_n": 3,
                },
            )

            if response.status_code == 200:
                result = response.json()
                print(f"✅ Reranker API 连接成功!")
                for item in result.get("results", []):
                    print(f"   文档 {item['index']}: 相关度 {item['relevance_score']:.4f}")
                return True
            else:
                print(f"❌ Reranker API 返回错误: {response.status_code}")
                print(f"   响应: {response.text}")
                return False

    except Exception as e:
        print(f"❌ Reranker API 连接失败: {str(e)}")
        return False


def test_mongodb():
    """测试 MongoDB 连接"""
    print("\n" + "="*50)
    print("测试 MongoDB 连接")
    print("="*50)

    try:
        from pymongo import MongoClient

        mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
        mongodb_user = os.getenv("MONGODB_USER", "admin")
        mongodb_password = os.getenv("MONGODB_PASSWORD", "password")
        db_name = os.getenv("MONGODB_DATABASE", "resume_rag")

        # 构建带认证的连接字符串
        if mongodb_user and mongodb_password:
            # 从 URL 中提取 host:port
            host_port = mongodb_url.replace("mongodb://", "")
            auth_url = f"mongodb://{mongodb_user}:{mongodb_password}@{host_port}/{db_name}?authSource=admin"
        else:
            auth_url = mongodb_url

        print(f"URL: {auth_url[:50]}...")

        client = MongoClient(auth_url, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")

        db = client[db_name]

        print(f"✅ MongoDB 连接成功!")
        print(f"   数据库: {db_name}")

        # 列出集合（需要认证）
        try:
            collections = db.list_collection_names()
            print(f"   集合: {collections}")
        except Exception as e:
            print(f"   集合: (需要额外权限)")

        client.close()
        return True

    except Exception as e:
        print(f"❌ MongoDB 连接失败: {str(e)}")
        return False


def test_milvus():
    """测试 Milvus 连接"""
    print("\n" + "="*50)
    print("测试 Milvus 连接")
    print("="*50)

    try:
        from pymilvus import connections, utility

        milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
        print(f"URI: {milvus_uri}")

        connections.connect(alias="default", uri=milvus_uri)

        # 测试连接
        collections = utility.list_collections()
        print(f"✅ Milvus 连接成功!")
        print(f"   集合: {collections}")

        connections.disconnect(alias="default")
        return True

    except Exception as e:
        print(f"❌ Milvus 连接失败: {str(e)}")
        return False


def test_redis():
    """测试 Redis 连接"""
    print("\n" + "="*50)
    print("测试 Redis 连接")
    print("="*50)

    try:
        import redis

        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_password = os.getenv("REDIS_PASSWORD", "password")

        print(f"Host: {redis_host}:{redis_port}")

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
        )

        # 测试连接
        r.ping()

        # 测试读写
        r.set("test_key", "test_value")
        value = r.get("test_key")
        r.delete("test_key")

        print(f"✅ Redis 连接成功!")
        print(f"   读写测试: {value}")

        return True

    except Exception as e:
        print(f"❌ Redis 连接失败: {str(e)}")
        return False


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("智能招聘 RAG 推荐系统 - API 配置测试")
    print("="*60)

    results = {}

    # 测试所有服务
    results["LLM API"] = test_llm_api()
    results["Embedding API"] = test_embedding_api()
    results["Reranker API"] = test_reranker_api()
    results["MongoDB"] = test_mongodb()
    results["Milvus"] = test_milvus()
    results["Redis"] = test_redis()

    # 汇总结果
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)

    all_passed = True
    for service, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{service}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "="*60)
    if all_passed:
        print("🎉 所有服务测试通过！可以启动应用了。")
    else:
        print("⚠️  部分服务测试失败，请检查配置。")
    print("="*60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
