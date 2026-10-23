import { defineConfig } from 'vitepress';
import { withMermaid } from 'vitepress-plugin-mermaid';
import { withSidebar } from 'vitepress-sidebar';

import { markdown } from './configs/markdown.ts';
import { mermaid } from './configs/mermaid.ts';
import { sidebar } from './configs/sidebar.ts';
import { site } from './configs/site.ts';
import { themeConfig } from './configs/theme.ts';
import { vite, withMermaidPrebundle } from './configs/vite.ts';

export default withSidebar(
  withMermaidPrebundle(
    withMermaid(
      defineConfig({
        ...site,
        markdown,
        mermaid,
        themeConfig,
        vite,
      }),
    ),
  ),
  sidebar,
);
