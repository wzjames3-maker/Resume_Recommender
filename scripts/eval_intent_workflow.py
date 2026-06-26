#!/usr/bin/env python3
'''Intent Recognition & Workflow Evaluation Suite'''
import sys, os, json, time, traceback
sys.path.insert(0, '.')
from collections import defaultdict

results = []
def test(name, fn):
    try:
        start = time.time()
        r = fn()
        elapsed = time.time() - start
        results.append((name, 'PASS', str(r)[:500], f'{elapsed:.1f}s'))
        print(f'\n[PASS] {name} ({elapsed:.1f}s)')
        if isinstance(r, dict):
            for k, v in r.items():
                print(f'  {k}: {v}')
        elif isinstance(r, str) and len(r) < 200:
            print(f'  {r}')
    except Exception as e:
        results.append((name, 'FAIL', str(e)[:300], ''))
        print(f'\n[FAIL] {name}: {str(e)[:200]}')
        traceback.print_exc()

# ============================================================
print('=' * 70)
print('PHASE 1: INTENT RECOGNITION TESTS')
print('=' * 70)

def t1_classifier_health():
    from src.intent_router.classifier import get_intent_classifier
    c = get_intent_classifier()
    c.clear_cache()
    assert c.model, 'No model configured'
    assert c.api_key, 'No API key'
    return f'Model={c.model}, threshold={c.confidence_threshold}'

test('1. Classifier Health', t1_classifier_health)

# ---- Keyword fallback tests (no LLM cost) ----
def t2_keyword_fallback():
    from src.intent_router.classifier import get_intent_classifier
    from src.intent_router.schemas import IntentEnum
    c = get_intent_classifier()
    tests = [
        ('帮我找3年Java开发', IntentEnum.RECRUITMENT_SEARCH),
        ('推荐一个前端工程师', IntentEnum.RECRUITMENT_SEARCH),
        ('按薪资从高到低排序', IntentEnum.RECRUITMENT_REFINE),
        ('筛选工作经验5年以上的', IntentEnum.RECRUITMENT_REFINE),
        ('查看张三的简历详情', IntentEnum.CANDIDATE_LOOKUP),
        ('简历详情李四', IntentEnum.CANDIDATE_LOOKUP),
        ('你好', IntentEnum.CHAT),
        ('今天天气怎么样', IntentEnum.CHAT),
        ('上传简历', IntentEnum.RESUME_UPLOAD),
        ('随机乱码xyz123', IntentEnum.CHAT),
    ]
    correct = 0
    details = []
    for query, expected in tests:
        r = c._keyword_fallback(query)
        ok = r.intent == expected
        if ok: correct += 1
        details.append(f'  {chr(0x2713) if ok else chr(0x2717)} \"{query}\" -> {r.intent.value} (expected={expected.value})')
    for d in details:
        print(d)
    return {'accuracy': f'{correct}/{len(tests)} ({100*correct//len(tests)}%)'}

test('2. Keyword Fallback Accuracy', t2_keyword_fallback)

# ---- LLM-based intent classification ----
def t3_llm_intent_classification():
    from src.intent_router.classifier import get_intent_classifier
    from src.intent_router.schemas import IntentEnum
    c = get_intent_classifier()
    c.clear_cache()
    
    test_cases = [
        ('帮我找一个3年以上Java开发经验的候选人', IntentEnum.RECRUITMENT_SEARCH),
        ('推荐有Python和机器学习背景的候选人', IntentEnum.RECRUITMENT_SEARCH),
        ('按薪资从高到低排序', IntentEnum.RECRUITMENT_REFINE),
        ('只看工作经验5年以上的', IntentEnum.RECRUITMENT_REFINE),
        ('查看张三的简历详情', IntentEnum.CANDIDATE_LOOKUP),
        ('你好，你能做什么', IntentEnum.CHAT),
        ('谢谢你的帮助', IntentEnum.CHAT),
        ('对比一下张三和李四', IntentEnum.RECRUITMENT_COMPARE),
    ]
    
    correct = 0
    total = 0
    confidences = []
    details = []
    fallback_count = 0
    
    for query, expected in test_cases:
        total += 1
        r = c.classify(query)
        confidences.append(r.confidence)
        ok = r.intent == expected
        if ok: correct += 1
        note = ''
        if 'keyword' in (r.reasoning or ''):
            fallback_count += 1
            note = ' [keyword]'
        elif 'fallback' in str(r.intent.value):
            note = ' [llm-fallback]'
        marker = chr(0x2713) if ok else chr(0x2717)
        details.append(f'  {marker} \"{query}\" -> {r.intent.value} conf={r.confidence:.2f}{note}')
    
    for d in details:
        print(d)
    
    avg_conf = sum(confidences)/len(confidences) if confidences else 0
    return {
        'accuracy': f'{correct}/{total} ({100*correct//total}%)',
        'avg_confidence': f'{avg_conf:.2f}',
        'keyword_fallback_rate': f'{fallback_count}/{total}',
        'model': c.model,
    }

test('3. LLM Intent Classification', t3_llm_intent_classification)

# ---- Intent with Context ----
def t4_intent_with_context():
    from src.intent_router.classifier import get_intent_classifier
    from src.intent_router.schemas import IntentEnum
    from src.intent_router.schemas import ConversationContext
    
    c = get_intent_classifier()
    c.clear_cache()
    
    ctx = ConversationContext(
        conversation_id='test-ctx-1',
        turn_count=3,
        last_intent=IntentEnum.RECRUITMENT_SEARCH,
        last_query={'intent': 'recruitment.search', 'skills': ['Java']},
    )
    
    queries = [
        ('按薪资排序', IntentEnum.RECRUITMENT_REFINE),
        ('只要北京地区的', IntentEnum.RECRUITMENT_REFINE),
        ('再推荐几个', IntentEnum.RECRUITMENT_REFINE),
    ]
    
    correct = 0
    details = []
    for query, expected in queries:
        r = c.classify(query, context=ctx)
        ok = r.intent == expected
        if ok: correct += 1
        marker = chr(0x2713) if ok else chr(0x2717)
        details.append(f'  {marker} \"{query}\" -> {r.intent.value} conf={r.confidence:.2f}')
    
    for d in details:
        print(d)
    
    return {'accuracy': f'{correct}/{len(queries)} ({100*correct//len(queries)}%)'}

test('4. Intent with Context', t4_intent_with_context)

# ---- Cache behavior ----
def t5_cache_behavior():
    from src.intent_router.classifier import get_intent_classifier
    c = get_intent_classifier()
    c.clear_cache()
    
    # First call - should hit LLM
    start1 = time.time()
    r1 = c.classify('帮我找5年Java开发')
    time1 = time.time() - start1
    
    # Second call - should hit cache
    start2 = time.time()
    r2 = c.classify('帮我找5年Java开发')
    time2 = time.time() - start2
    
    same = r1.intent == r2.intent and r1.confidence == r2.confidence
    speedup = time1 / time2 if time2 > 0 else 0
    
    print(f'  1st call: {time1:.2f}s -> {r1.intent.value} (conf={r1.confidence:.2f})')
    print(f'  2nd call: {time2:.2f}s -> {r2.intent.value} (conf={r2.confidence:.2f})')
    
    return {
        'cache_consistent': str(same),
        'speedup': f'{speedup:.1f}x' if speedup > 1 else f'{time2:.4f}s (no speedup)',
        'first_latency': f'{time1:.2f}s',
    }

test('5. Cache Behavior', t5_cache_behavior)

# ---- Slot extraction ----
def t6_slot_extraction():
    from src.intent_router.classifier import get_intent_classifier
    from src.intent_router.schemas import IntentEnum
    c = get_intent_classifier()
    c.clear_cache()
    
    r = c.classify('帮我找一个在北京的有3年React开发经验的候选人')
    
    slots = {}
    if r.query_slots:
        slots['skills'] = r.candidate_slots.skills
        slots['min_experience'] = r.candidate_slots.experience
        slots['city'] = r.candidate_slots.city
        slots['sort_by'] = r.query_slots.sort_by
    if r.candidate_slots:
        slots['candidate_name'] = r.candidate_slots.name
    
    print(f'  Intent: {r.intent.value} (conf={r.confidence:.2f})')
    print(f'  Reasoning: {r.reasoning}')
    for k, v in slots.items():
        if v: print(f'  Slot.{k}: {v}')
    
    return {
        'intent': r.intent.value,
        'confidence': f'{r.confidence:.2f}',
        'slots_found': sum(1 for v in slots.values() if v),
        'total_slots': len(slots),
    }

test('6. Slot Extraction', t6_slot_extraction)

# ============================================================
print('\n' + '=' * 70)
print('PHASE 2: WORKFLOW EVALUATION')
print('=' * 70)

def t7_workflow_resume_enrichment():
    '''Test that resume metadata is properly looked up for intent enrichment'''
    from src.intent_router.classifier import get_intent_classifier
    c = get_intent_classifier()
    c.clear_cache()
    
    r = c.classify('帮我找一个有字节跳动工作经验的候选人，要求3年以上Java开发，薪资期望30k以内')
    
    print(f'  Intent: {r.intent.value}')
    print(f'  Skills: {r.candidate_slots.skills}')
    print(f'  Company: {r.candidate_slots.company}')
    print(f'  Min experience: {r.candidate_slots.experience}')
    print(f'  Max salary: {r.candidate_slots.salary}')
    
    return {
        'intent': r.intent.value,
        'skills': str(r.candidate_slots.skills)[:80],
        'company': r.candidate_slots.company or 'N/A',
        'experience': str(r.candidate_slots.experience),
        'salary': str(r.candidate_slots.salary),
    }

test('7. Complex Query Slot Extraction', t7_workflow_resume_enrichment)

def t8_workflow_conversation_flow():
    '''Test a multi-turn conversation simulating a real recruiting session'''
    from src.conversation_memory.session_manager import get_session_manager
    from src.intent_router.classifier import get_intent_classifier
    
    sm = get_session_manager()
    c = get_intent_classifier()
    c.clear_cache()
    
    session = sm.create_session(user_id='eval-user')
    print(f'  Session: {session.session_id[:8]}...')
    
    turns = [
        ('你好，我需要找一个Java开发工程师', 'user'),
        ('好的，请问有什么具体要求吗？', 'assistant'),
        ('3年以上经验，最好在北京', 'user'),
        ('已为您检索到以下候选人，需要进一步筛选吗？', 'assistant'),
        ('按薪资从低到高排序', 'user'),
    ]
    
    turn_results = []
    for msg, role in turns:
        sm.append_message(session.session_id, role, msg)
        if role == 'user':
            r = c.classify(msg)
            sm.update_session_state(session.session_id, {'last_intent': r.intent.value})
        else:
            r = None
    
    ctx = sm.get_context(session.session_id)
    msgs = sm.get_messages(session.session_id, limit=10)
    
    print(f'  Messages stored: {len(msgs)}')
    print(f'  Turn count: {ctx.turn_count}')
    print(f'  Last intent: {ctx.last_intent}')
    
    return {
        'session_id': session.session_id[:12],
        'messages': str(len(msgs)),
        'turns': str(ctx.turn_count),
        'last_intent': str(ctx.last_intent),
    }

test('8. Multi-turn Conversation Flow', t8_workflow_conversation_flow)

def t9_workflow_narrow_optimization():
    '''Test NARROW optimization - refine should modify existing search, not re-search from scratch'''
    from src.conversation_memory.workflow import ConversationWorkflow
    from src.intent_router.classifier import get_intent_classifier
    from src.conversation_memory.session_manager import get_session_manager
    from src.intent_router.schemas import IntentEnum
    
    c = get_intent_classifier()
    c.clear_cache()
    sm = get_session_manager()
    
    session = sm.create_session(user_id='narrow-test')
    
    # Step 1: Initial search
    r1 = c.classify('帮我找3年Java开发')
    sm.append_message(session.session_id, 'user', '帮我找3年Java开发')
    sm.update_session_state(session.session_id, {'last_intent': r1.intent.value})
    print(f'  Step 1 (search): {r1.intent.value} skills={r1.query_slots.skills}')
    
    # Step 2: Refine based on context
    ctx = sm.get_context(session.session_id)
    r2 = c.classify('按薪资排序，只看北京地区的', context=ctx)
    sm.append_message(session.session_id, 'user', '按薪资排序，只看北京地区的')
    sm.update_session_state(session.session_id, {'last_intent': r2.intent.value})
    print(f'  Step 2 (refine): {r2.intent.value} sort={r2.query_slots.sort_by} city={r2.query_slots.city}')
    
    return {
        'step1_intent': r1.intent.value,
        'step2_intent': r2.intent.value,
        'step2_sort': r2.query_slots.sort_by or 'N/A',
        'step2_city': r2.query_slots.city or 'N/A',
    }

test('9. NARROW Optimization (Search -> Refine)', t9_workflow_narrow_optimization)

# ============================================================
print('\n' + '=' * 70)
print('PHASE 3: EVALUATION METRICS SUMMARY')
print('=' * 70)

def t10_eval_metrics():
    '''Run a mini evaluation suite with labeled queries'''
    from src.intent_router.classifier import get_intent_classifier
    from src.intent_router.schemas import IntentEnum
    c = get_intent_classifier()
    c.clear_cache()
    
    labeled_queries = [
        # (query, expected_intent)
        ('找3年Python开发', IntentEnum.RECRUITMENT_SEARCH),
        ('推荐一个有React经验的候选人', IntentEnum.RECRUITMENT_SEARCH),
        ('招一个数据分析师', IntentEnum.RECRUITMENT_SEARCH),
        ('需要5年以上C++开发', IntentEnum.RECRUITMENT_SEARCH),
        ('按工作经验排序', IntentEnum.RECRUITMENT_REFINE),
        ('只看硕士学历的', IntentEnum.RECRUITMENT_REFINE),
        ('薪资从高到低', IntentEnum.RECRUITMENT_REFINE),
        ('查看王五的详情', IntentEnum.CANDIDATE_LOOKUP),
        ('张三的简历', IntentEnum.CANDIDATE_LOOKUP),
        ('对比赵六和孙七', IntentEnum.RECRUITMENT_COMPARE),
        ('你好', IntentEnum.CHAT),
        ('谢谢', IntentEnum.CHAT),
        ('今天天气如何', IntentEnum.CHAT),
        ('你能做什么', IntentEnum.CHAT),
        ('上传我的简历', IntentEnum.RESUME_UPLOAD),
    ]
    
    intent_confusion = defaultdict(lambda: defaultdict(int))
    per_intent = defaultdict(lambda: {'correct': 0, 'total': 0})
    confidences = []
    total_correct = 0
    total = 0
    
    for query, expected in labeled_queries:
        total += 1
        r = c.classify(query)
        confidences.append(r.confidence)
        intent_confusion[expected][r.intent] += 1
        per_intent[expected]['total'] += 1
        if r.intent == expected:
            total_correct += 1
            per_intent[expected]['correct'] += 1
    
    accuracy = total_correct / total if total else 0
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    
    print(f'  Overall Accuracy: {total_correct}/{total} = {accuracy:.1%}')
    print(f'  Avg Confidence: {avg_confidence:.2f}')
    print()
    print('  Per-Intent Accuracy:')
    for intent in sorted(per_intent.keys(), key=lambda x: x.value):
        d = per_intent[intent]
        acc = d['correct'] / d['total'] if d['total'] else 0
        bar = chr(0x2588) * int(acc * 10)
        print(f'    {intent.value:25s}: {d["correct"]}/{d["total"]} = {acc:.0%} {bar}')
    
    # Confusion matrix summary
    print()
    print('  Confusion Matrix (expected -> predicted):')
    for expected in sorted(intent_confusion.keys(), key=lambda x: x.value):
        preds = intent_confusion[expected]
        for pred, count in sorted(preds.items(), key=lambda x: -x[1]):
            if count > 0:
                marker = '  ' if pred == expected else '  ! '
                print(f'    {marker}{expected.value:25s} -> {pred.value:25s}: {count}')
    
    return {
        'accuracy': f'{accuracy:.1%}',
        'avg_confidence': f'{avg_confidence:.2f}',
        'total_queries': str(total),
    }

test('10. Mini Evaluation Suite', t10_eval_metrics)

# ============================================================
print('\n' + '=' * 70)
print('FINAL SUMMARY')
print('=' * 70)
passed = sum(1 for _, status, _, _ in results if status == 'PASS')
failed = sum(1 for _, status, _, _ in results if status == 'FAIL')
for name, status, detail, elapsed in results:
    marker = chr(0x2713) if status == 'PASS' else chr(0x2717)
    print(f'  {marker} {name}: {status} ({elapsed})')
    if status == 'FAIL':
        print(f'       {detail[:120]}')
print(f'\n  {passed}/{len(results)} PASS, {failed}/{len(results)} FAIL')
