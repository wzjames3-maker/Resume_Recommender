<template>
  <nav class="hr-workspace-nav" aria-label="人事部导航">
    <div class="hr-workspace-nav__inner">
      <div class="hr-workspace-nav__identity">
        <span class="hr-workspace-nav__mark"><el-icon><User /></el-icon></span>
        <div>
          <strong>招聘运营</strong>
          <span>{{ roleLabel }}</span>
        </div>
      </div>
      <div class="hr-workspace-nav__links" role="list">
        <button
          v-for="item in primaryLinks"
          :key="item.path"
          type="button"
          class="hr-workspace-nav__link"
          :class="{ 'is-active': isActive(item.path) }"
          :aria-current="isActive(item.path) ? 'page' : undefined"
          @click="go(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
        <el-dropdown v-if="moreLinks.length" trigger="click" popper-class="hr-workspace-dropdown" @command="go">
          <button type="button" class="hr-workspace-nav__link hr-workspace-nav__more" :class="{ 'is-active': moreLinks.some((item) => isActive(item.path)) }">
            <el-icon><MoreFilled /></el-icon>
            <span>更多</span>
            <el-icon class="hr-workspace-nav__chevron"><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="item in moreLinks" :key="item.path" :command="item.path" :class="{ 'is-active': isActive(item.path) }">
                <el-icon><component :is="item.icon" /></el-icon>
                {{ item.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Calendar, Collection, Document, Files, MagicStick, MoreFilled, Setting, User } from '@element-plus/icons-vue'
import useStore from '@/stores'

interface NavItem {
  label: string
  path: string
  icon: Component
}

const route = useRoute()
const router = useRouter()
const { user } = useStore()
const isAdmin = computed(() => user.getHrRole() === 'ADMIN')
const roleLabel = computed(() => ({ ADMIN: '管理员', OPERATOR: '招聘运营', INTERVIEWER: '面试官' } as Record<string, string>)[user.getHrRole() || ''] || '工作区成员')

const primaryLinks: NavItem[] = [
  { label: '工作台', path: '/hr/dashboard', icon: Document },
  { label: 'Pipeline', path: '/hr/pipeline', icon: Files },
  { label: '简历库', path: '/hr/candidates', icon: Collection },
  { label: '职位', path: '/hr/jobs', icon: User },
  { label: '面试', path: '/hr/interviews', icon: Calendar },
  { label: 'Agent', path: '/hr/agents', icon: MagicStick },
]

const moreLinks = computed<NavItem[]>(() => {
  const links: NavItem[] = []
  if (isAdmin.value) {
    links.push({ label: 'Offer 管理', path: '/hr/offers', icon: Document })
    links.push(
      { label: '简历库管理', path: '/hr/resumes/databases', icon: Collection },
      { label: '入职交接', path: '/hr/handoffs', icon: Files },
      { label: '人事成员', path: '/hr/access', icon: User },
      { label: '审计日志', path: '/hr/audit-logs', icon: Document },
      { label: '租户注销', path: '/hr/offboarding', icon: Setting },
    )
  }
  return links
})

function isActive(path: string) {
  const basePath = path.split('?')[0]
  return route.path === basePath || route.path.startsWith(basePath + '/')
}

function go(path: string) {
  router.push(path)
}
</script>
