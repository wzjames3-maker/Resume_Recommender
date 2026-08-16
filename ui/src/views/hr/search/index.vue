<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>简历语义检索</h2>
        <span class="color-secondary">基于简历知识库的语义召回 + RRF 融合 + Rerank 精排</span>
      </div>
    </div>

    <el-card style="--el-card-padding: 0">
      <div class="p-16 border-b flex gap-12">
        <el-input
          v-model="form.query"
          placeholder="输入自然语言，例如：有幕墙系统设计经验、3 年以上 Python 后端、会 Java 和 FastAPI 的候选人"
          clearable
          style="flex: 1"
          @keyup.enter="search"
        />
        <span class="color-secondary">模式</span>
        <el-select v-model="form.mode" style="width: 130px">
          <el-option label="自动" value="auto" />
          <el-option label="混合" value="hybrid" />
          <el-option label="向量" value="dense" />
          <el-option label="整句" value="phrase" />
          <el-option label="技能" value="skills" />
        </el-select>
        <span class="color-secondary">TopK</span>
        <el-input-number v-model="form.top_k" :min="1" :max="20" :step="1" />
        <el-button type="primary" :loading="searching" @click="search">检索</el-button>
      </div>

      <el-table :data="items" v-loading="searching" :empty-text="emptyText">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="paragraph-list">
              <el-empty v-if="!row.paragraphs || row.paragraphs.length === 0" description="无命中段落（结构化/姓名命中）" :image-size="60" />
              <div v-for="p in row.paragraphs" :key="p.id" class="paragraph-item">
                <div class="flex-between mb-8">
                  <span class="paragraph-title">{{ p.title || '段落' }}</span>
                  <el-tag size="small">score {{ Number(p.score || 0).toFixed(3) }}</el-tag>
                </div>
                <p class="paragraph-content">{{ p.content }}</p>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="rank" label="#" width="60" />
        <el-table-column label="候选人" min-width="150">
          <template #default="{ row }">
            <div v-if="row.candidate">
              <el-link type="primary" :underline="false" @click="goCandidate(row.candidate)">{{ row.candidate.name }}</el-link>
              <div class="color-secondary text-12">
                {{ row.candidate.highest_degree || '学历未知' }}
                <template v-if="row.candidate.years_unknown">
                  <el-tag size="small" type="info" class="ml-4">年限未知</el-tag>
                </template>
                <template v-else>
                  · {{ row.candidate.years_experience == null ? '-' : `${row.candidate.years_experience} 年` }}
                </template>
              </div>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="联系方式" min-width="160">
          <template #default="{ row }">
            <template v-if="row.candidate">
              <div>{{ row.candidate.phone || '-' }}</div>
              <div class="color-secondary text-12">{{ row.candidate.email || '-' }}</div>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="技能" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <template v-if="row.candidate?.skills?.length">
              <el-tag v-for="skill in row.candidate.skills" :key="skill" size="small" class="mr-4">{{ skill }}</el-tag>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="简历" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.resume">{{ row.resume.file_name }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="分数" width="150">
          <template #default="{ row }">
            <div class="text-12">
              <div v-if="row.score?.resume != null">综合 {{ Number(row.score.resume).toFixed(3) }}</div>
              <div v-if="row.score?.rerank != null">Rerank {{ Number(row.score.rerank).toFixed(3) }}</div>
              <div v-if="row.score?.rrf != null">RRF {{ Number(row.score.rrf).toFixed(3) }}</div>
              <div v-if="row.score?.hit_count != null">命中 {{ row.score.hit_count }} 技能</div>
              <div v-if="row.score?.name_match">姓名命中</div>
              <div v-if="row.score?.structured">结构化命中</div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="meta" class="mt-16" style="--el-card-padding: 0">
      <template #header>
        <span>检索元信息</span>
      </template>
      <div class="meta-grid p-16">
        <div class="meta-item"><span class="label">模式</span><span>{{ modeLabel(meta.mode) }}（{{ meta.search_type }}）</span></div>
        <div class="meta-item"><span class="label">技能</span><span>{{ meta.skills?.length ? meta.skills.join('、') : '-' }}</span></div>
        <div class="meta-item"><span class="label">召回</span><span>{{ formatMeta(meta.recall) }}</span></div>
        <div class="meta-item"><span class="label">Rerank</span><span>{{ formatMeta(meta.rerank) }}</span></div>
        <div class="meta-item"><span class="label">聚合</span><span>{{ formatMeta(meta.aggregation) }}</span></div>
        <div class="meta-item"><span class="label">耗时</span><span>{{ formatElapsed(meta.elapsed_ms) }}</span></div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import HrApi from '@/api/hr/recruitment'
import type { ResumeSearchCandidate, ResumeSearchItem, ResumeSearchMeta, ResumeSearchMode } from '@/api/type/hr'
import { MsgError } from '@/utils/message'

const router = useRouter()

const searching = ref(false)
const items = ref<ResumeSearchItem[]>([])
const meta = ref<ResumeSearchMeta | null>(null)
const form = reactive({
  query: '',
  mode: 'auto' as ResumeSearchMode,
  top_k: 5,
})

const emptyText = computed(() => {
  if (!meta.value) return '输入查询开始语义检索'
  if (meta.value.search_type === 'prefilter_empty') return '无满足条件的候选人'
  if (meta.value.search_type === 'empty') return '未检索到结果'
  return '未检索到结果'
})

function search() {
  const query = form.query.trim()
  if (!query) return
  searching.value = true
  items.value = []
  meta.value = null
  HrApi.searchResumes({
    query,
    mode: form.mode,
    top_k: form.top_k,
  })
    .then((response) => {
      items.value = response.data.items || []
      meta.value = response.data.meta || null
    })
    .catch(() => MsgError('语义检索失败，请检查 AI/Rerank 配置与简历知识库'))
    .finally(() => {
      searching.value = false
    })
}

function goCandidate(candidate: ResumeSearchCandidate | null) {
  if (!candidate) return
  router.push({ path: '/hr/candidates', query: { candidate_id: candidate.id } })
}

function modeLabel(mode: ResumeSearchMode | undefined) {
  const labels: Record<string, string> = {
    auto: '自动',
    hybrid: '混合',
    dense: '向量',
    phrase: '整句',
    skills: '技能',
  }
  return mode ? labels[mode] || mode : '-'
}

function formatMeta(value: unknown) {
  if (!value) return '-'
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function formatElapsed(value: Record<string, number> | undefined) {
  if (!value) return '-'
  return Object.entries(value)
    .map(([key, ms]) => `${key}: ${ms}ms`)
    .join(' / ')
}
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.text-12 { font-size: 12px; line-height: 18px; }
.candidate-name { font-weight: 500; }
.paragraph-list { padding: 4px 24px 16px; }
.paragraph-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--el-fill-color-light);
}
.paragraph-title { font-weight: 500; }
.paragraph-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px 24px;
}
.meta-item {
  display: flex;
  gap: 8px;
  font-size: 13px;
}
.meta-item .label {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  min-width: 56px;
}
</style>
