p = r'C:\Users\Administrator\Desktop\简历推荐系统\src\frontend\pages\3_简历管理.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()
old = 'query[\"personal_info.total_experience\"] = {\"\u0024regex\": str(min_exp), \"\u0024options\": \"i\"}'
new = 'query[\"personal_info.total_experience\"] = {\"\u0024gte\": min_exp}'
print('Old found:', old in c)
c = c.replace(old, new)
with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
print('Fix 2 reapplied')