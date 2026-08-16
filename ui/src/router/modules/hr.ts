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
    order: 1,
  },
  redirect: '/hr/candidates',
  component: () => import('@/layout/layout-template/SimpleLayout.vue'),
  children: [
    {
      path: '/hr/candidates',
      name: 'hr-candidates',
      meta: { title: '候选人', activeMenu: '/hr', sameRoute: 'hr' },
      component: () => import('@/views/hr/candidates/index.vue'),
    },
    {
      path: '/hr/jobs',
      name: 'hr-jobs',
      meta: { title: '职位', activeMenu: '/hr', sameRoute: 'hr' },
      component: () => import('@/views/hr/jobs/index.vue'),
    },
    {
      path: '/hr/search',
      name: 'hr-search',
      meta: { title: '简历检索', activeMenu: '/hr', sameRoute: 'hr' },
      component: () => import('@/views/hr/search/index.vue'),
    },
    {
      path: '/hr/my-interviews',
      name: 'hr-my-interviews',
      meta: { title: '我的面试', activeMenu: '/hr', sameRoute: 'hr' },
      component: () => import('@/views/hr/my-interviews/index.vue'),
    },
    {
      path: '/hr/access',
      name: 'hr-access',
      meta: { title: '人事成员', activeMenu: '/hr', sameRoute: 'hr', permission: [HrRoleConst.ADMIN] },
      component: () => import('@/views/hr/access/index.vue'),
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
