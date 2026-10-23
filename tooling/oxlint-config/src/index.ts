import type { OxlintConfig } from 'oxlint';

import { defineConfig as defineOxlintConfig } from 'oxlint';

import { mergeOxlintConfigs, oxlintConfig } from './configs/index.ts';

type VbenOxlintConfig = Omit<OxlintConfig, 'extends'> & {
  extends?: OxlintConfig[];
};

function defineConfig(config: VbenOxlintConfig = {}) {
  const { extends: extendedConfigs = [], ...restConfig } = config;

  return defineOxlintConfig(mergeOxlintConfigs(oxlintConfig, ...extendedConfigs, restConfig));
}

export { defineConfig, oxlintConfig };
export * from './configs/index.ts';
export type { OxlintConfig, VbenOxlintConfig };
