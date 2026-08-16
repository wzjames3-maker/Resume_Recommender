// HR 模块共享常量与标签映射
// 候选人与职位页共用,避免多处重复定义

// ---------- 候选人 ----------
export const channelLabels: Record<string, string> = {
  REFERRAL: '内推',
  JOB_SITE: '招聘网站',
  HEADHUNTER: '猎头',
  CAMPUS: '校园',
  OTHER: '其他',
}

export const consentStatusLabels: Record<string, string> = {
  UNKNOWN: '未知',
  NOTIFIED: '已告知',
  CONSENTED: '已同意',
  NOT_REQUIRED: '无需同意',
}

export const contactPreferenceLabels: Record<string, string> = {
  EMAIL: '邮箱',
  PHONE: '电话',
  NO_CONTACT: '不联系',
  UNSPECIFIED: '未指定',
}

export const highestDegreeOptions = ['博士', '硕士', '本科', '大专', '中专', '高中']

/** 返回候选人合规信息缺失项；空数组表示已完善 */
export function getComplianceMissing(candidate: {
  phone?: string | null
  email?: string | null
  collected_at?: string | null
  consent_status?: string
  consent_version?: string
  contact_preference?: string
}): string[] {
  const missing: string[] = []
  if (!candidate.phone && !candidate.email) missing.push('联系方式')
  if (!candidate.collected_at) missing.push('收集日期')
  if (!candidate.consent_status || candidate.consent_status === 'UNKNOWN') missing.push('告知状态')
  if (!candidate.consent_version) missing.push('告知版本')
  if (!candidate.contact_preference || candidate.contact_preference === 'UNSPECIFIED') missing.push('联系偏好')
  return missing
}

// ---------- 职位 ----------
export const jobStatusLabels: Record<string, string> = {
  DRAFT: '草稿',
  OPEN: '开放',
  ON_HOLD: '暂停',
  CLOSED: '已关闭',
}

export function jobStatusTagType(status: string) {
  if (status === 'OPEN') return 'success'
  if (status === 'ON_HOLD') return 'warning'
  if (status === 'CLOSED') return 'info'
  return 'info'
}

export const jobCloseReasonLabels: Record<string, string> = {
  FILLED: '招满',
  CANCELLED: '取消',
  DUPLICATE: '重复需求',
  OTHER: '其他',
}

// ---------- 指派 ----------
export const assignmentStatusLabels: Record<string, string> = {
  PENDING_SCREEN: '待筛选',
  SCREEN_PASSED: '筛选通过',
  INTERVIEWING: '面试中',
  OFFER: 'Offer 中',
  HIRED: '已入职',
  REJECTED: '已淘汰',
  WITHDRAWN: '已退出',
  CLOSED: '已关闭',
}

/** 看板进行中列的链式顺序:只允许按此顺序前进 */
export const PIPELINE_ORDER = ['PENDING_SCREEN', 'SCREEN_PASSED', 'INTERVIEWING', 'OFFER', 'HIRED'] as const

export const TERMINAL_STATUSES = ['REJECTED', 'WITHDRAWN', 'CLOSED'] as const

export function assignmentTagType(status: string) {
  if (status === 'HIRED') return 'success'
  if (status === 'REJECTED' || status === 'WITHDRAWN' || status === 'CLOSED') return 'info'
  return 'primary'
}

// ---------- Application（ATS v2） ----------
export const applicationStatusLabels: Record<string, string> = {
  ACTIVE: '在途',
  HIRED: '已入职',
  REJECTED: '已淘汰',
  WITHDRAWN: '已退出',
  CLOSED: '已关闭',
}

export const TERMINAL_APPLICATION_STATUSES = ['REJECTED', 'WITHDRAWN', 'CLOSED'] as const

export function applicationStatusTagType(status: string) {
  if (status === 'ACTIVE') return 'primary'
  if (status === 'HIRED') return 'success'
  return 'info'
}

export const applicationTerminalReasonOptions: Record<string, string[]> = {
  reject: ['NOT_FIT', 'SALARY', 'OTHER'],
  withdraw: ['CANDIDATE_WITHDRAW', 'UNREACHABLE', 'OTHER'],
  close: ['MERGED', 'OTHER'],
}

export const applicationActionLabels: Record<string, string> = {
  reject: '淘汰',
  withdraw: '候选人退出',
  close: '关闭申请',
  restore: '恢复申请',
}

export const relationTypeLabels: Record<string, string> = {
  APPLY: '投递',
  SEEK: '主动寻访',
  REFERRAL: '内推',
  HEADHUNTER: '猎头推荐',
}

export const terminationReasonLabels: Record<string, string> = {
  NOT_FIT: '不合适',
  SALARY: '薪资不符',
  UNREACHABLE: '无法联系',
  CANDIDATE_WITHDRAW: '候选人退出',
  JOB_CLOSED: '职位关闭',
  MERGED: '合并',
  OTHER: '其他',
}

// ---------- 面试 ----------
export const interviewStatusLabels: Record<string, string> = {
  PENDING: '待面试',
  PASSED: '通过',
  FAILED: '未通过',
  NO_SHOW: '未到场',
  CANCELLED: '取消',
}

// ---------- Offer ----------
export const offerStatusLabels: Record<string, string> = {
  DRAFT: '草稿',
  SENT: '已发送',
  ACCEPTED: '已接受',
  REJECTED: '已拒绝',
  WITHDRAWN: '已撤回',
}

export function offerStatusTag(status: string) {
  if (status === 'ACCEPTED') return 'success'
  if (status === 'REJECTED' || status === 'WITHDRAWN') return 'danger'
  if (status === 'SENT') return 'warning'
  return 'info'
}

// ---------- 简历流转 ----------
export const flowLogNodeLabels: Record<string, string> = {
  UPLOAD: '上传',
  EXTRACT: '提取',
  SANITIZE: '清洗',
  SPLIT: '切片',
  DOCUMENT: '建索引',
  LIFECYCLE: '生命周期',
}

// ---------- 通用格式化 ----------
export function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export function formatFileSize(bytes: number) {
  if (bytes == null) return '-'
  return bytes >= 1024 * 1024 ? (bytes / 1024 / 1024).toFixed(1) + ' MB' : (bytes / 1024).toFixed(1) + ' KB'
}
