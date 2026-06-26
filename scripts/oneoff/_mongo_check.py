from pymongo import MongoClient
c=MongoClient('mongodb://localhost:27017',username='admin',password='password')
db=c['resume_rag']
print('collections', db.list_collection_names())
print('count', db.resumes.count_documents({}))
