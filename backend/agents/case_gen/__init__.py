"""Map-Reduce 用例生成流水线（四步 Agent）。

详见 docs/design/03_case_gen_pipeline.md。

子模块组织：
  - pipeline_io     : pipeline_id 生成、目录布局、state 持久化
  - slicer          : Step 1 需求切片
  - generator       : Step 2 并行用例生成
  - merger          : Step 3 合并去重 + 集成场景补充
  - validator       : Step 4 质量校验（纯代码）
  - pipeline        : CaseGenPipeline 编排器（把四步串起来）
"""
