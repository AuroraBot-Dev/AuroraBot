import { defineConfig } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";
import { generateSidebar } from "vitepress-sidebar";

export default withMermaid(
  defineConfig({
    title: "AuroraBot 文档站",
    description: "AuroraBot — 新一代内驱式、自主决策的智能体框架",
    base: "/AuroraBot/",
    cleanUrls: true,
    lastUpdated: true,
    ignoreDeadLinks: true,
    head: [
      [
        "link",
        { rel: "icon", type: "image/svg+xml", href: "/AuroraBot/logo.svg" },
      ],
    ],
    mermaid: {
      theme: "default",
      securityLevel: "loose",
      look: "handDrawn",
      startOnLoad: false,
      flowchart: {
        curve: "basis",
      },
    },
    markdown: {
      container: {
        tipLabel: "💡 小贴士",
        warningLabel: "⚠️ 注意",
        dangerLabel: "💀 危险操作",
        infoLabel: "🪧 告示牌",
        detailsLabel: "展开",
      },
    },
    themeConfig: {
      nav: [
        { text: "首页", link: "/" },
        { text: "开始", link: "/start/overview" },
        { text: "开发", link: "/develop/app-development" },
        { text: "架构", link: "/architecture/system-overview" },
        { text: "问答", link: "/qa/cross-platform" },
      ],
      sidebar: (() => {
        const raw = generateSidebar({
          documentRootPath: ".",
          scanStartPath: ".",
          resolvePath: "/",
          useTitleFromFileHeading: true,
          useFolderTitleFromIndexFile: true,
          includeFolderIndexFile: false,
          sortMenusByFrontmatterOrder: true,
          frontmatterOrderDefaultValue: 99,
          collapsed: false,
        });
        // 确保每个 link 以 "/" 开头，否则 VitePress prev/next 匹配会失效
        const prefixSlash = (items: any) => {
          for (const item of items) {
            if (item.link && !item.link.startsWith("/"))
              item.link = "/" + item.link;
            if (item.items) prefixSlash(item.items);
          }
        };
        prefixSlash(raw);
        return raw;
      })(),
      search: {
        provider: "local",
      },
      socialLinks: [
        { icon: "github", link: "https://github.com/JuFireX/AuroraBot" },
      ],
      outline: {
        label: "本页内容",
      },
      docFooter: {
        prev: "上一页",
        next: "下一页",
      },
      lastUpdated: {
        text: "最后更新",
        formatOptions: {
          dateStyle: "short",
          timeStyle: "medium",
        },
      },
      footer: {
        message: "Built with VitePress",
        copyright: "Copyright © 2026 JuFireX",
      },
    },
  }),
);
