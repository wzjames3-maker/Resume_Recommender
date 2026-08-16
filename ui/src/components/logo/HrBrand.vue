<template>
  <div class="hr-brand" :class="size">
    <div class="hr-brand__mark">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
        <path d="M4 20V6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H8l-3.2 2.4A.6.6 0 0 1 4 20Z" fill="currentColor" />
        <path d="M8.5 9h7M8.5 12.5h4.5" stroke="#fff" stroke-width="1.6" stroke-linecap="round" />
      </svg>
    </div>
    <div class="hr-brand__text">
      <span class="hr-brand__name">{{ name }}</span>
      <span v-if="subtitle" class="hr-brand__sub">{{ subtitle }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 主标题文案 */
    name?: string
    /** 副标题文案 */
    subtitle?: string
    /** 尺寸: header 用于顶栏, login 用于登录页 */
    size?: 'header' | 'login'
  }>(),
  {
    name: '人事招聘工作台',
    subtitle: '',
    size: 'header',
  },
)
</script>

<style lang="scss" scoped>
.hr-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;

  &__mark {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    background: linear-gradient(135deg, #3370ff 0%, #6d5ef2 100%);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    box-shadow: 0 2px 6px rgba(51, 112, 255, 0.35);
  }

  &__text {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }

  &__name {
    font-size: 16px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    letter-spacing: 0.5px;
    white-space: nowrap;
  }

  &__sub {
    font-size: 11px;
    color: var(--el-text-color-secondary);
    white-space: nowrap;
  }

  &.login {
    &__mark {
      width: 44px;
      height: 44px;
      border-radius: 12px;
    }

    &__name {
      font-size: 20px;
    }

    &__sub {
      font-size: 12px;
    }
  }
}
</style>
