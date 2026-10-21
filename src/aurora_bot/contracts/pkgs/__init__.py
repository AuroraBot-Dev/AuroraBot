"""按提供方组织的全局契约端口。

每个 ``src/aurora_bot/<pkg>`` 若向全局暴露端口，就在本目录放一个同名 ``<pkg>.py``，只定义 Protocol，
并从 ``aurora_bot.contracts`` 的基础值对象导入所需类型。消费方直接从 ``aurora_bot.contracts.pkgs.<pkg>``
导入即可，无需中心化再导出，也不需要修改任何聚合入口。
"""
