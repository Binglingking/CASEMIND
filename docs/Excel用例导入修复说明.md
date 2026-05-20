# Excel 用例导入修复说明

## 问题描述

之前上传 Excel 用例时，存在两个问题：

1. **内容丢失**：当"用例步骤"和"预期结果"的数量不一致时，系统会按较短的对齐，导致用例内容丢失
2. **不必要的警告**：即使数量不一致是正常情况，系统也会产生警告信息
3. **对齐逻辑不合理**：预期结果对齐到步骤的前几步，而不是最后几步

例如：
- 3个步骤 + 1个预期 → 只保留1个步骤（❌ 丢失数据）
- 2个步骤 + 4个预期 → 只保留2个预期（❌ 丢失数据）
- 4个步骤 + 2个预期 → 预期对齐到第1、2步（❌ 不符合实际需求）

## 解决方案

修改了 `backend/core/legacy/excel_parser.py` 中的解析逻辑：

### 1. 移除警告提示
```python
# ❌ 修改前：产生警告
if len(steps_raw) != len(expected_raw) and steps_raw and expected_raw:
    warnings.append(ParseWarning(...))

# ✅ 修改后：不再产生警告
# 步骤和预期数量不一致是正常情况，无需警告
```

### 2. 完整保存所有数据
```python
# ❌ 修改前：按短的对齐
n = min(len(steps_raw), len(expected_raw))

# ✅ 修改后：保留所有内容
n = max(len(steps_raw), len(expected_raw))
```

### 3. 预期结果对齐到最后几步
```python
# ✅ 新增逻辑：当步骤数多于预期数时，预期对齐到步骤的最后几步
# 例如：步骤有4个，预期有2个，则预期的第1个对齐步骤的第3个，预期的第2个对齐步骤的第4个
expected_index = k - (len(steps_raw) - len(expected_raw)) if len(steps_raw) > len(expected_raw) else k
```

## 新行为

现在系统会：
1. ✅ **完整保存所有步骤和预期结果**，即使数量不匹配
2. ✅ **不再产生警告信息**，步骤和预期数量不一致是正常情况
3. ✅ **预期结果对齐到步骤的最后几步**（更符合实际业务场景）
4. 对于没有对应预期的步骤，`expected` 字段为空字符串
5. 对于没有对应步骤的预期，`action` 字段为空字符串

### 示例1：步骤多于预期

**输入：**
- 用例步骤：`1. 第一步\n2. 第二步\n3. 第三步\n4. 第四步`
- 预期结果：`1. 预期A\n2. 预期B`

**输出（4个步骤）：**
```python
steps[0]: action="第一步", expected=""      # 前两步没有预期
steps[1]: action="第二步", expected=""
stes[2]: action="第三步", expected="预期A"  # 后两步有预期
steps[3]: action="第四步", expected="预期B"
```

### 示例2：预期多于步骤

**输入：**
- 用例步骤：`1. 第一步\n2. 第二步`
- 预期结果：`1. 预期1\n2. 预期2\n3. 预期3\n4. 预期4`

**输出（4个步骤）：**
```python
steps[0]: action="第一步", expected="预期1"
steps[1]: action="第二步", expected="预期2"
steps[2]: action="", expected="预期3"       # 后两步没有步骤
steps[3]: action="", expected="预期4"
```

## 基础字段保证

系统始终按照以下基础字段表头保存用例（可以添加其他字段，但不影响基础字段展示）：

| 字段名 | 说明 |
|--------|------|
| 用例目录 | suite |
| 模块 | module |
| 子项 | sub_item |
| 用例名称 | title |
| 前置条件 | preconditions |
| 用例步骤 | steps (数组) |
| 预期结果 | steps[*].expected |

## 测试验证

运行以下测试验证修改：
```bash
python -m pytest backend/tests/test_legacy_excel_parser.py -v
python -m pytest backend/tests/test_legacy_service.py -v
```

所有测试均已通过 ✅

## 相关文件

- `backend/core/legacy/excel_parser.py` - Excel 解析器核心逻辑
- `backend/tests/test_legacy_excel_parser.py` - 解析器测试
- `backend/schemas/legacy_case.py` - 用例数据模型
