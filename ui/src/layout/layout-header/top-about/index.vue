<template>
  <div class="flex align-center top-about">

    <el-tooltip
      effect="dark"
      :content="$t('layout.github')"
      placement="top"
      v-if="theme.themeInfo?.showProject"
    >
      <el-button text @click="toUrl(theme.themeInfo?.projectUrl)">
        <AppIcon
          iconName="app-github"
          class="cursor color-secondary"
          style="font-size: 20px"
        ></AppIcon>
      </el-button>
    </el-tooltip>
    <el-tooltip
      effect="dark"
      :content="$t('layout.wiki')"
      placement="top"
      v-if="theme.themeInfo?.showUserManual"
    >
      <el-button text @click="toUrl(theme.themeInfo?.userManualUrl)">
        <AppIcon
          iconName="app-user-manual"
          class="cursor color-secondary"
          style="font-size: 20px"
        ></AppIcon>
      </el-button>
    </el-tooltip>
    <el-tooltip
      effect="dark"
      :content="$t('layout.forum')"
      placement="top"
      v-if="theme.themeInfo?.showForum"
    >
      <el-button text @click="toUrl(theme.themeInfo?.forumUrl)">
        <AppIcon
          iconName="app-problems"
          class="cursor color-secondary"
          style="font-size: 20px"
        ></AppIcon>
      </el-button>
    </el-tooltip>
  </div>
</template>
<script setup lang="ts">
import useStore from '@/stores'
const { theme } = useStore()
function toUrl(url: string) {
  window.open(url, '_blank')
}
</script>
<style scoped lang="scss">
.top-about {
  .el-button.is-text {
    max-height: 32px;
    padding: 6px !important;
  }
  .el-button + .el-button {
    margin-left: 8px !important;
  }
  .active {
    background-color: #ffffff;
    box-shadow: 0px 2px 4px 0px rgba(var(--el-text-color-primary-rgb), 0.12);
    &:hover {
      background: #ffffff;
    }
  }
}
</style>
