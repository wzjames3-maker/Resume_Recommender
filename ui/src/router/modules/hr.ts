import { RoleConst } from '@/utils/permission/data'

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
  ],
}

export default hrRouter
