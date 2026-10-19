import { nextTick, onMounted, onUnmounted, ref, watchEffect } from "vue";
import zh from "./assets/i18n/zh-CN.json";
import en from "./assets/i18n/en-US.json";
import ja from "./assets/i18n/ja-JP.json";

const messages = { "zh-CN": zh, "en-US": en, "ja-JP": ja };
type Locale = keyof typeof messages;
const aliases: Record<string, Locale> = {
  zh: "zh-CN",
  "zh-cn": "zh-CN",
  "zh-hans": "zh-CN",
  en: "en-US",
  "en-us": "en-US",
  ja: "ja-JP",
  "ja-jp": "ja-JP",
};

function normalizeLocale(value: string): Locale {
  const key = value.replaceAll("_", "-").toLowerCase();
  return aliases[key] ?? aliases[key.split("-")[0]!] ?? "zh-CN";
}

// 浏览器禁用持久存储时仍可使用页面全部交互。
function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存储不可用时保留本次会话状态。 */
  }
}

export function useLanding() {
  const locale = ref<Locale>(
    normalizeLocale(new URLSearchParams(location.search).get("lang") ?? stored("aurora-locale") ?? navigator.language),
  );
  const theme = ref(stored("aurora-theme") ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const menuOpen = ref(false);
  const copied = ref(false);
  const languagePicker = ref<HTMLElement>();
  const languageButton = ref<HTMLButtonElement>();
  const languageMenu = ref<HTMLElement>();
  let copyTimer: ReturnType<typeof setTimeout> | undefined;

  function t(path: string): string {
    let value: unknown = messages[locale.value];
    for (const part of path.split(".")) value = (value as Record<string, unknown> | undefined)?.[part];
    return typeof value === "string" ? value : "";
  }

  watchEffect(() => {
    const meta = messages[locale.value].meta;
    document.documentElement.lang = meta.locale;
    document.documentElement.dir = meta.direction;
    document.documentElement.dataset.theme = theme.value;
    document.title = meta.title;
    document.querySelectorAll<HTMLElement>("head [data-i18n-attr]").forEach((element) => {
      for (const binding of element.dataset.i18nAttr!.split(",")) {
        const separator = binding.indexOf(":");
        element.setAttribute(binding.slice(0, separator), t(binding.slice(separator + 1)));
      }
    });
    const schema = document.getElementById("structured-data");
    if (schema) schema.textContent = JSON.stringify(meta.schema);
  });

  async function openLanguageMenu(): Promise<void> {
    menuOpen.value = true;
    await nextTick();
    languageMenu.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
  }
  function closeLanguageMenu(): void {
    menuOpen.value = false;
    languageButton.value?.focus();
  }
  function toggleLanguageMenu(): void {
    if (menuOpen.value) closeLanguageMenu();
    else void openLanguageMenu();
  }
  function navigateLanguageMenu(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      closeLanguageMenu();
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const options = Array.from(languageMenu.value?.querySelectorAll<HTMLButtonElement>("button") ?? []);
      const index = options.indexOf(document.activeElement as HTMLButtonElement);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? options.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      options[next]?.focus();
    }
  }
  function selectLocale(value: Locale): void {
    locale.value = value;
    remember("aurora-locale", value);
    const url = new URL(location.href);
    url.searchParams.set("lang", value);
    history.replaceState(null, "", url);
    closeLanguageMenu();
  }
  function toggleTheme(): void {
    theme.value = theme.value === "dark" ? "light" : "dark";
    remember("aurora-theme", theme.value);
  }
  async function copyInstall(): Promise<void> {
    const command = document.getElementById("quick-command")?.innerText;
    if (!command || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(command);
      copied.value = true;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => {
        copied.value = false;
      }, 1600);
    } catch {
      /* 复制权限不可用时仍可手动选择命令。 */
    }
  }
  function outsideClick(event: MouseEvent): void {
    if (event.target instanceof Node && !languagePicker.value?.contains(event.target)) menuOpen.value = false;
  }
  onMounted(() => document.addEventListener("click", outsideClick));
  onUnmounted(() => {
    document.removeEventListener("click", outsideClick);
    clearTimeout(copyTimer);
  });

  return {
    t,
    locale,
    menuOpen,
    copied,
    languagePicker,
    languageButton,
    languageMenu,
    toggleLanguageMenu,
    openLanguageMenu,
    navigateLanguageMenu,
    selectLocale,
    toggleTheme,
    copyInstall,
  };
}
