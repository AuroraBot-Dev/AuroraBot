import { ref, watchEffect } from 'vue';

import { remember, stored } from '../storage';

type Theme = 'dark' | 'light';

function initialTheme(): Theme {
  const saved = stored('aurora-theme');
  if (saved === 'dark' || saved === 'light') return saved;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function createTheme() {
  const theme = ref<Theme>(initialTheme());

  watchEffect(() => {
    document.documentElement.dataset.theme = theme.value;
  });

  function toggleTheme(): void {
    theme.value = theme.value === 'dark' ? 'light' : 'dark';
    remember('aurora-theme', theme.value);
  }

  return { theme, toggleTheme };
}

let theme: ReturnType<typeof createTheme> | undefined;

export function useTheme() {
  theme ??= createTheme();
  return theme;
}
