<script setup lang="ts">
import { computed } from 'vue'
import {
  NConfigProvider,
  NDialogProvider,
  NGlobalStyle,
  NMessageProvider,
  darkTheme,
  useOsTheme,
  type GlobalThemeOverrides,
} from 'naive-ui'
import { RouterView } from 'vue-router'

const osTheme = useOsTheme()
const theme = computed(() => (osTheme.value === 'dark' ? darkTheme : null))

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#aa3bff',
    primaryColorHover: '#b862ff',
    primaryColorPressed: '#8f2fd8',
    primaryColorSuppl: '#b862ff',
  },
}
</script>

<template>
  <n-config-provider
    class="h-full"
    :theme="theme"
    :theme-overrides="themeOverrides"
  >
    <n-global-style />
    <n-message-provider class="h-full">
      <n-dialog-provider class="h-full">
        <div class="h-full">
          <router-view />
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
.h-full {
  height: 100%;
}
</style>
