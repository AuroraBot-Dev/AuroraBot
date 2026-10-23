import type { MermaidConfig } from 'mermaid';

export const mermaid = {
  theme: 'default',
  securityLevel: 'loose',
  look: 'handDrawn',
  startOnLoad: false,
  flowchart: {
    curve: 'basis',
  },
} satisfies MermaidConfig;
