import { RoleConst, HrRoleConst } from '@/utils/permission/data'

const hrRouter = {
  path: '/hr',
  name: 'hr',
  meta: {
    title: '人事部',
    menu: true,
    permission: [RoleConst.USER.getWorkspaceRole, RoleConst.WORKSPACE_MANAGE.getWorkspaceRole],
    icon: 'app-user',
    group: 'workspace',
    order: 5,
  },
  redirect: '/hr/pipeline',
  component: () => import('@/layout/layout-template/SimpleLayout.vue'),
  children: [
    {
      path: '/hr/pipeline',
      name: 'hr-pipeline',
      meta: { title: 'Pipeline', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/pipeline/index.vue'),
    },
    {
      path: '/hr/dashboard',
      name: 'hr-dashboard',
      meta: { title: '工作台', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/dashboard/index.vue'),
    },
    {
      path: '/hr/agents',
      name: 'hr-agents',
      meta: { title: 'Agent 工作台', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/agents/index.vue'),
    },
    {
      path: '/hr/candidates',
      name: 'hr-candidates',
      meta: { title: '简历数据库', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/resumes/index.vue'),
    },
    {
      path: '/hr/resumes/databases',
      name: 'hr-resume-databases',
      meta: { title: '简历库管理', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/resumes/databases.vue'),
    },
    {
      path: '/hr/resumes/databases/:databaseId',
      name: 'hr-resume-database-detail',
      meta: { title: '库内候选人', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/candidates/index.vue'),
    },
    {
      path: '/hr/resumes/upload',
      name: 'hr-resume-upload',
      meta: { title: '批量上传简历', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.OPERATOR] },
      component: () => import('@/views/hr/resumes/upload.vue'),
    },
    {
      path: '/hr/candidates/list',
      name: 'hr-candidate-list',
      meta: { title: '全部候选人', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/candidates/index.vue'),
    },
    {
      path: '/hr/candidates/:id',
      name: 'hr-candidate-detail',
      meta: { title: '候选人详情', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/candidates/detail.vue'),
    },
    {
      path: '/hr/jobs/new',
      name: 'hr-job-create',
      meta: { title: '新建职位', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.OPERATOR] },
      component: () => import('@/views/hr/jobs/create.vue'),
    },
    {
      path: '/hr/jobs',
      name: 'hr-jobs',
      meta: { title: '职位', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/jobs/index.vue'),
    },
    {
      path: '/hr/offers',
      name: 'hr-offers',
      meta: { title: 'Offer 管理', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/offers/index.vue'),
    },
    {
      path: '/hr/search',
      name: 'hr-search',
      meta: { title: '简历检索', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.OPERATOR] },
      component: () => import('@/views/hr/search/index.vue'),
    },
    {
      path: '/hr/interviews',
      name: 'hr-interviews',
      meta: { title: '面试管理', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.OPERATOR] },
      component: () => import('@/views/hr/interviews/index.vue'),
    },
    {
      path: '/hr/my-interviews',
      name: 'hr-my-interviews',
      meta: { title: '我的面试', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.VIEWER] },
      component: () => import('@/views/hr/my-interviews/index.vue'),
    },
    {
      path: '/hr/access',
      name: 'hr-access',
      meta: { title: '人事成员', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/access/index.vue'),
    },
    {
      path: '/hr/offboarding',
      name: 'hr-offboarding',
      meta: { title: '租户注销', activeMenu: '/hr', sameRoute: 'hr', permission: [RoleConst.WORKSPACE_MANAGE] },
      component: () => import('@/views/hr/offboarding/index.vue'),
    },
    {
      path: '/hr/audit-logs',
      name: 'hr-audit-logs',
      meta: { title: '审计日志', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/audit/index.vue'),
    },
    {
      path: '/hr/handoffs',
      name: 'hr-handoffs',
      meta: { title: '入职交接', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/handoffs/index.vue'),
    },
  ],
}

export default hrRouter
