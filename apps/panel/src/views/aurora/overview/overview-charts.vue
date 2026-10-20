<script lang="ts" setup>
import type { AgentTreeSummary, MemorySnapshot } from '#/api';

import { computed, onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';
import { preferences } from '@vben/preferences';

const props = defineProps<{
  kind: 'memory' | 'trees';
  memory?: MemorySnapshot;
  trees: AgentTreeSummary[];
}>();

const chartRef = ref();
const { renderEcharts } = useEcharts(chartRef);
type ChartOption = Parameters<typeof renderEcharts>[0];

const treeData = computed(() => {
  const counts = new Map<string, number>();
  props.trees.forEach((tree) => counts.set(tree.status, (counts.get(tree.status) ?? 0) + 1));
  return [...counts].map(([name, value]) => ({ name, value }));
});
const memoryData = computed(() =>
  (props.memory?.scopes ?? []).map((scope) => ({
    name: scope.scope,
    value: scope.commits.length,
  })),
);

function options(): ChartOption {
  const values = props.kind === 'trees' ? treeData.value : memoryData.value;
  if (props.kind === 'trees') {
    return {
      color: ['#1677ff', '#52c41a', '#ff4d4f'],
      legend: { bottom: 0, textStyle: { color: '#64748b' } },
      series: [{ data: values, radius: ['42%', '68%'], type: 'pie' }],
      title: values.length > 0 ? undefined : { left: 'center', text: '暂无 Tree', top: 'middle' },
      tooltip: { trigger: 'item' },
    };
  }
  return {
    color: ['#13c2c2'],
    grid: { bottom: 50, containLabel: true, left: 15, right: 25, top: 20 },
    series: [{ barMaxWidth: 30, data: values.map((item) => item.value), type: 'bar' }],
    title: values.length > 0 ? undefined : { left: 'center', text: '暂无 Memory scope', top: 'middle' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      axisLabel: { color: '#64748b', interval: 0, rotate: 20 },
      data: values.map((item) => item.name),
      type: 'category',
    },
    yAxis: { axisLabel: { color: '#64748b' }, type: 'value' },
  };
}

function render() {
  void renderEcharts(options());
}

watch(() => [props.trees, props.memory, preferences.theme.mode], render, {
  deep: true,
});
onMounted(render);
</script>

<template>
  <EchartsUI ref="chartRef" class="h-72" />
</template>
