"""默认阶段的可选预算和压缩资源；模型与归档服务由装配借入。"""

from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport

from .compaction import HistoryCompactor
from .input_budget import ModelInputBudget
from .plugins.defaults._meta import BUDGET_CONFIGURE, COMPACTION_CONFIGURE


class BudgetResource(ModelInputBudget):
    def __init__(self, *, ctx, states, options):
        if "config" in states and options:
            raise ValueError("参数须选择配置状态或显式 options")
        super().__init__(options.get("max_chars", 128000))
        self.ctx, self.states = ctx, states

    @plug(BUDGET_CONFIGURE)
    def configure(self):
        if "config" in self.states:
            self.max_chars = self.ctx.get(self.states["config"].key, location=dict(self.states["config"].location))[
                "max_chars"
            ]


class CompactionResource(HistoryCompactor):
    def __init__(self, *, ctx, states, options):
        if "config" in states and options:
            raise ValueError("参数须选择配置状态或显式 options")
        self.ctx, self.states, self.options = ctx, states, options
        self.recorder = None

    def bind(self, *, chat, budget, recorder=None):
        self.client, self.budget, self.recorder = chat, budget, recorder

    @plug(COMPACTION_CONFIGURE)
    def configure(self):
        parameters = (
            self.ctx.get(self.states["config"].key, location=dict(self.states["config"].location))
            if "config" in self.states
            else self.options
        )
        super().__init__(
            self.client,
            self.budget,
            summary_chars=parameters.get("summary_chars", 6000),
            timeout=parameters.get("timeout_seconds", 60),
            recorder=self.recorder,
        )


def factories():
    return {
        "input_budget": ComponentFactory(
            BudgetResource,
            lambda instance: InstanceExport(
                plugs={BUDGET_CONFIGURE: instance.configure}, resources={"input_budget": instance}
            ),
            plugs=(BudgetResource.configure,),
        ),
        "compaction": ComponentFactory(
            CompactionResource,
            lambda instance: InstanceExport(
                plugs={COMPACTION_CONFIGURE: instance.configure}, resources={"compaction": instance}
            ),
            plugs=(CompactionResource.configure,),
            bind=lambda instance, resources: instance.bind(**resources),
        ),
    }
