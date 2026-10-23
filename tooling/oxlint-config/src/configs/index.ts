import type { OxlintConfig } from 'oxlint';

import { defineConfig as defineOxlintConfig } from 'oxlint';

import { command } from './command.ts';
import { comments } from './comments.ts';
import { ignores } from './ignores.ts';
import { importPluginConfig } from './import.ts';
import { javascript } from './javascript.ts';
import { node } from './node.ts';
import { overrides } from './overrides.ts';
import { plugins } from './plugins.ts';
import { test } from './test.ts';
import { typescript } from './typescript.ts';
import { unicorn } from './unicorn.ts';
import { vue } from './vue.ts';

function mergeOxlintConfigs(...configs: OxlintConfig[]): OxlintConfig {
  const merged: OxlintConfig = {};

  for (const config of configs) {
    merged.categories =
      merged.categories && config.categories
        ? { ...merged.categories, ...config.categories }
        : (config.categories ?? merged.categories);
    merged.env = merged.env && config.env ? { ...merged.env, ...config.env } : (config.env ?? merged.env);
    merged.globals =
      merged.globals && config.globals ? { ...merged.globals, ...config.globals } : (config.globals ?? merged.globals);
    merged.ignorePatterns = [...(merged.ignorePatterns ?? []), ...(config.ignorePatterns ?? [])];
    merged.jsPlugins = [...new Set([...(merged.jsPlugins ?? []), ...(config.jsPlugins ?? [])])];
    merged.overrides = [...(merged.overrides ?? []), ...(config.overrides ?? [])];
    merged.plugins = [...new Set([...(merged.plugins ?? []), ...(config.plugins ?? [])])];
    merged.rules = merged.rules && config.rules ? { ...merged.rules, ...config.rules } : (config.rules ?? merged.rules);
    merged.settings =
      merged.settings && config.settings
        ? { ...merged.settings, ...config.settings }
        : (config.settings ?? merged.settings);
  }

  return merged;
}

const oxlintConfig = defineOxlintConfig(
  mergeOxlintConfigs(
    javascript,
    command,
    comments,
    ignores,
    plugins,
    importPluginConfig,
    node,
    overrides,
    test,
    typescript,
    unicorn,
    vue,
  ),
);

export {
  command,
  comments,
  ignores,
  importPluginConfig,
  javascript,
  mergeOxlintConfigs,
  node,
  overrides,
  oxlintConfig,
  plugins,
  test,
  typescript,
  unicorn,
  vue,
};
