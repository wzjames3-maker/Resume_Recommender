#!/usr/bin/env python3
"""Generate 100 diverse resumes using LLM"""
import json, os, httpx, time, random

API_KEY = "sk-8TOvYUiK72C4yZHF9zfcUwZiWBKrK9aS"
BASE_URL = "https://token.sensenova.cn/v1"

# Define diverse profiles
profiles = [
    # Java Backend
    {"role": "Java高级工程师", "companies": ["阿里巴巴", "腾讯", "字节跳动", "美团", "京东", "百度", "网易", "滴滴", "快手", "拼多多"], "skills": ["Java", "Spring Boot", "微服务", "MySQL", "Redis", "Kafka", "Docker", "Kubernetes", "ElasticSearch", "分布式系统"], "schools": ["清华大学", "北京大学", "浙江大学", "上海交通大学", "复旦大学", "中国科学技术大学", "南京大学", "华中科技大学", "武汉大学", "哈尔滨工业大学"], "degrees": ["本科", "硕士", "博士"]},
    {"role": "Java中级工程师", "companies": ["小米", "华为", "OPPO", "vivo", "联想", "中兴", "海康威视", "大华", "用友", "金蝶"], "skills": ["Java", "Spring", "MyBatis", "MySQL", "Redis", "RabbitMQ", "Linux", "Git", "Maven", "Jenkins"], "schools": ["西安电子科技大学", "北京邮电大学", "电子科技大学", "东南大学", "同济大学", "大连理工大学", "重庆大学", "湖南大学", "中南大学", "西北工业大学"], "degrees": ["本科", "硕士"]},
    # Frontend
    {"role": "前端高级工程师", "companies": ["腾讯", "字节跳动", "美团", "快手", "B站", "小红书", "知乎", "携程", "蚂蚁集团", "钉钉"], "skills": ["React", "TypeScript", "Vue.js", "Node.js", "Webpack", "小程序", "Next.js", "GraphQL", "TailwindCSS", "前端性能优化"], "schools": ["清华大学", "北京大学", "浙江大学", "上海交通大学", "南京大学", "华中科技大学", "武汉大学", "中山大学", "厦门大学", "四川大学"], "degrees": ["本科", "硕士"]},
    {"role": "前端中级工程师", "companies": ["京东", "网易", "58同城", "贝壳找房", "得物", "唯品会", "苏宁", "国美", "当当", "蘑菇街"], "skills": ["JavaScript", "Vue.js", "React", "CSS", "HTML5", "Webpack", "微信小程序", "uni-app", "ElementUI", "Ant Design"], "schools": ["北京理工大学", "北京航空航天大学", "天津大学", "山东大学", "吉林大学", "兰州大学", "东北大学", "中国海洋大学", "暨南大学", "华南理工大学"], "degrees": ["本科", "硕士"]},
    # AI/Algorithm
    {"role": "AI算法工程师", "companies": ["百度", "阿里巴巴", "腾讯", "字节跳动", "商汤科技", "旷视科技", "科大讯飞", "寒武纪", "地平线", "第四范式"], "skills": ["Python", "PyTorch", "TensorFlow", "NLP", "CV", "大模型", "RAG", "Transformer", "CUDA", "分布式训练"], "schools": ["清华大学", "北京大学", "中国科学技术大学", "上海交通大学", "浙江大学", "南京大学", "复旦大学", "哈尔滨工业大学", "中科院", "北京航空航天大学"], "degrees": ["硕士", "博士"]},
    {"role": "数据科学家", "companies": ["阿里巴巴", "腾讯", "美团", "滴滴", "快手", "拼多多", "京东", "网易", "小米", "华为"], "skills": ["Python", "SQL", "Spark", "Hadoop", "机器学习", "深度学习", "数据挖掘", "A/B测试", "Tableau", "统计分析"], "schools": ["北京大学", "清华大学", "复旦大学", "上海交通大学", "浙江大学", "南京大学", "中国人民大学", "中央财经大学", "上海财经大学", "对外经济贸易大学"], "degrees": ["硕士", "博士"]},
    # DevOps/SRE
    {"role": "DevOps工程师", "companies": ["华为云", "阿里云", "腾讯云", "字节跳动", "美团", "PingCAP", "JFrog", "灵雀云", "DaoCloud", "青云"], "skills": ["Docker", "Kubernetes", "Jenkins", "GitLab CI", "Ansible", "Terraform", "Prometheus", "Grafana", "Linux", "Shell脚本"], "schools": ["北京邮电大学", "西安电子科技大学", "电子科技大学", "成都理工大学", "重庆邮电大学", "杭州电子科技大学", "桂林电子科技大学", "南京邮电大学", "西安邮电大学", "长春理工大学"], "degrees": ["本科", "硕士"]},
    {"role": "SRE工程师", "companies": ["字节跳动", "阿里巴巴", "腾讯", "美团", "快手", "百度", "网易", "京东", "滴滴", "小米"], "skills": ["Linux", "Python", "Go", "Docker", "Kubernetes", "Prometheus", "Grafana", "ELK", "Nginx", "负载均衡"], "schools": ["清华大学", "北京航空航天大学", "哈尔滨工业大学", "北京理工大学", "大连理工大学", "东北大学", "西安交通大学", "西北工业大学", "武汉大学", "华中科技大学"], "degrees": ["本科", "硕士"]},
    # Product/Design
    {"role": "产品经理", "companies": ["腾讯", "字节跳动", "阿里巴巴", "美团", "快手", "小红书", "B站", "知乎", "得物", "携程"], "skills": ["需求分析", "用户研究", "数据分析", "Axure", "Figma", "SQL", "A/B测试", "Scrum", "项目管理", "商业化"], "schools": ["北京大学", "清华大学", "复旦大学", "上海交通大学", "中国人民大学", "浙江大学", "南京大学", "武汉大学", "中山大学", "厦门大学"], "degrees": ["本科", "硕士"]},
    {"role": "UI/UX设计师", "companies": ["腾讯", "阿里巴巴", "字节跳动", "美团", "快手", "网易", "B站", "小红书", "蚂蚁集团", "钉钉"], "skills": ["Figma", "Sketch", "Adobe XD", "Photoshop", "Illustrator", "用户研究", "交互设计", "视觉设计", "设计系统", "Motion Design"], "schools": ["中央美术学院", "清华大学美术学院", "中国美术学院", "北京服装学院", "广州美术学院", "四川美术学院", "鲁迅美术学院", "湖北美术学院", "天津美术学院", "西安美术学院"], "degrees": ["本科", "硕士"]},
    # Mobile
    {"role": "Android高级工程师", "companies": ["华为", "小米", "OPPO", "vivo", "腾讯", "阿里巴巴", "字节跳动", "美团", "快手", "百度"], "skills": ["Kotlin", "Java", "Android SDK", "Jetpack", "Compose", "性能优化", "架构设计", "Gradle", "NDK", "跨平台"], "schools": ["北京邮电大学", "西安电子科技大学", "电子科技大学", "华中科技大学", "武汉大学", "浙江大学", "上海交通大学", "哈尔滨工业大学", "北京航空航天大学", "东南大学"], "degrees": ["本科", "硕士"]},
    {"role": "iOS高级工程师", "companies": ["苹果", "腾讯", "阿里巴巴", "字节跳动", "美团", "快手", "滴滴", "网易", "携程", "小红书"], "skills": ["Swift", "Objective-C", "UIKit", "SwiftUI", "Combine", "Core Data", "性能优化", "架构设计", "CocoaPods", "CI/CD"], "schools": ["清华大学", "北京大学", "浙江大学", "上海交通大学", "南京大学", "复旦大学", "中山大学", "厦门大学", "武汉大学", "华中科技大学"], "degrees": ["本科", "硕士"]},
    # QA
    {"role": "测试工程师", "companies": ["腾讯", "阿里巴巴", "字节跳动", "美团", "华为", "百度", "京东", "网易", "小米", "快手"], "skills": ["自动化测试", "Selenium", "Appium", "Python", "Java", "JMeter", "接口测试", "性能测试", "CI/CD", "测试框架"], "schools": ["北京理工大学", "北京科技大学", "天津大学", "山东大学", "吉林大学", "东北大学", "湖南大学", "中南大学", "重庆大学", "西安交通大学"], "degrees": ["本科", "硕士"]},
    # Security
    {"role": "安全工程师", "companies": ["腾讯", "阿里巴巴", "百度", "360", "奇安信", "深信服", "绿盟科技", "启明星辰", "安恒信息", "字节跳动"], "skills": ["渗透测试", "漏洞挖掘", "Web安全", "逆向工程", "Python", "C/C++", "密码学", "安全审计", "应急响应", "威胁情报"], "schools": ["北京邮电大学", "西安电子科技大学", "电子科技大学", "武汉大学", "华中科技大学", "北京航空航天大学", "上海交通大学", "浙江大学", "中国科学技术大学", "哈尔滨工业大学"], "degrees": ["本科", "硕士"]},
    # DBA
    {"role": "数据库工程师", "companies": ["阿里巴巴", "腾讯", "百度", "美团", "京东", "PingCAP", "达梦数据库", "人大金仓", "华为", "蚂蚁集团"], "skills": ["MySQL", "PostgreSQL", "Redis", "MongoDB", "分布式数据库", "SQL优化", "数据迁移", "高可用", "分库分表", "TiDB"], "schools": ["北京大学", "清华大学", "浙江大学", "上海交通大学", "南京大学", "武汉大学", "华中科技大学", "电子科技大学", "西安电子科技大学", "北京邮电大学"], "degrees": ["本科", "硕士"]},
    # Go Backend
    {"role": "Go后端工程师", "companies": ["字节跳动", "腾讯", "B站", "七牛云", "PingCAP", "今日头条", "滴滴", "美团", "快手", "知乎"], "skills": ["Go", "gRPC", "微服务", "Docker", "Kubernetes", "MySQL", "Redis", "Kafka", "etcd", "分布式系统"], "schools": ["清华大学", "北京大学", "浙江大学", "上海交通大学", "复旦大学", "南京大学", "华中科技大学", "武汉大学", "哈尔滨工业大学", "中国科学技术大学"], "degrees": ["本科", "硕士"]},
    # Rust
    {"role": "Rust工程师", "companies": ["字节跳动", "蚂蚁集团", "PingCAP", "华为", "百度", "达坦科技", "溪塔科技", "奇安信", "冲量在线", "Zilliz"], "skills": ["Rust", "C++", "系统编程", "WebAssembly", "Tokio", "并发编程", "内存安全", "网络编程", "Linux", "性能优化"], "schools": ["清华大学", "北京大学", "中国科学技术大学", "上海交通大学", "浙江大学", "南京大学", "哈尔滨工业大学", "北京航空航天大学", "国防科技大学", "西北工业大学"], "degrees": ["本科", "硕士", "博士"]},
]

# Chinese surnames and given names
surnames = ["张", "李", "王", "赵", "刘", "陈", "杨", "黄", "周", "吴", "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗", "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧", "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕", "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎"]
given_names = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "涛", "明", "超", "秀兰", "霞", "平", "刚", "桂英", "华", "飞", "玉兰", "萍", "红", "玉梅", "辉", "建华", "建国", "建军", "建平", "志强", "志明", "志远", "文博", "文轩", "浩然", "浩宇", "子涵", "子轩", "宇航", "思远", "天翔", "嘉懿", "俊杰", "晨曦", "雨泽", "皓轩"]

years_opts = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15]

def gen_resume(idx, profile):
    surname = random.choice(surnames)
    given = random.choice(given_names)
    name = surname + given
    gender = random.choice(["男", "女"])
    birth_year = random.randint(1985, 2002)
    phone = "1" + str(random.choice([38,39,58,59,86,87,36,37,88,89])) + "".join([str(random.randint(0,9)) for _ in range(8)])
    email = f"{surname.lower()}{given.lower()}{idx}@example.com"
    
    school = random.choice(profile["schools"])
    degree = random.choice(profile["degrees"])
    edu_start = str(birth_year + 18)
    edu_end = str(int(edu_start) + (4 if degree == "本科" else (2 if degree == "硕士" else 4)))
    
    companies = random.sample(profile["companies"], min(random.randint(1, 3), len(profile["companies"])))
    skills = random.sample(profile["skills"], min(random.randint(5, len(profile["skills"])), len(profile["skills"])))
    
    experience = []
    current_year = 2026
    exp_start = int(edu_end)
    for i, company in enumerate(companies):
        duration = random.randint(1, 4)
        start = str(exp_start)
        end = str(min(exp_start + duration, 2026))
        if i == len(companies) - 1:
            end = "至今"
        title = profile["role"]
        if i < len(companies) - 1:
            title = title.replace("高级", "").replace("资深", "").strip()
        desc_templates = [
            f"负责{company}核心业务系统开发，使用{', '.join(skills[:3])}等技术栈",
            f"主导{company}技术架构升级，系统性能提升{random.randint(30,80)}%",
            f"参与{company}平台建设，日活用户{random.choice(['百万', '千万', '亿'])}级",
            f"负责{company}微服务架构设计与实现，服务可用性达99.{random.randint(9,99)}%",
            f"主导{company}数据平台开发，处理日均{random.choice(['TB', 'PB'])}级数据",
        ]
        experience.append({
            "company": company,
            "title": title,
            "duration": f"{start}.{random.randint(1,12):02d}-{end}" if end != "至今" else f"{start}.{random.randint(1,12):02d}-至今",
            "description": random.choice(desc_templates)
        })
        exp_start += duration
    
    return {
        "name": name,
        "gender": gender,
        "birth_year": birth_year,
        "phone": phone,
        "email": email,
        "education": [{"school": school, "degree": degree, "major": "计算机科学与技术" if "工程师" in profile["role"] or "算法" in profile["role"] else random.choice(["计算机科学", "软件工程", "信息工程", "数据科学", "人工智能"]), "start": edu_start, "end": edu_end}],
        "experience": experience,
        "skills": skills,
    }

# Generate 100 resumes
os.makedirs("generated_resumes", exist_ok=True)
count = 0
for pidx, profile in enumerate(profiles):
    per_profile = 100 // len(profiles)
    if pidx < 100 % len(profiles):
        per_profile += 1
    for i in range(per_profile):
        resume = gen_resume(count, profile)
        fname = f"generated_resumes/resume_{count:03d}_{resume['name']}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(resume, f, ensure_ascii=False, indent=2)
        count += 1

print(f"Generated {count} resumes in generated_resumes/")

# Show distribution
from collections import Counter
files = os.listdir("generated_resumes")
print(f"Total files: {len(files)}")
