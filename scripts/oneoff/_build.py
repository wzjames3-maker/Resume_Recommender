import os
api_path = r'C:\Users\Administrator\Desktop\简历推荐系统\src\frontend\api_client.py'
with open(api_path, 'r', encoding='utf-8') as f: existing = f.read()
if 'def get_resume(' in existing: print('SKIP: already exists'); exit(0)
print('Appending methods...')
