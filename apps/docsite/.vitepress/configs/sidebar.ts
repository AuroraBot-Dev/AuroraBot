import type { VitePressSidebarOptions } from 'vitepress-sidebar/types';

export const sidebar = [
  {
    documentRootPath: './src',
    scanStartPath: '/',
    resolvePath: '/',
    useTitleFromFileHeading: true,
    useTitleFromFrontmatter: true,
    useFolderTitleFromIndexFile: true,
    useFolderLinkFromIndexFile: true,
    includeFolderIndexFile: false,
    sortMenusByFrontmatterOrder: true,
    frontmatterOrderDefaultValue: 1000,
    excludeByGlobPattern: ['.vitepress/**', 'node_modules/**', 'public/**', 'README*'],
  },
] satisfies VitePressSidebarOptions[];
