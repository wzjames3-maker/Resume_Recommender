interface WorkspaceItem {
  name: string,
  id?: string,
  user_count?: number,
}

interface CreateWorkspaceMemberParamsItem {
  user_ids: string[],
  role_ids: string[]
}

interface WorkspaceMemberItem {
  user_relation_id: string,
  user_id: string,
  username: string,
  nick_name: string,
  role_id: string,
  role_name: string,
}
export interface WorkspaceOffboardingCounts {
  [key: string]: number
}

export interface WorkspaceOffboardingPlan {
  workspace_id: string
  status: 'DRY_RUN' | 'PENDING' | 'BLOCKED' | 'OFFBOARDED' | 'ALREADY_OFFBOARDED'
  counts: {
    core: WorkspaceOffboardingCounts
    hr: WorkspaceOffboardingCounts
  }
  active_issues: string[]
  can_offboard: boolean
  exported_path?: string
  export?: Record<string, any> | null
  storage_cleanup_errors?: Array<{ key: string; error: string }>
}

export type { WorkspaceItem, CreateWorkspaceMemberParamsItem, WorkspaceMemberItem }
