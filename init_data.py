#!/usr/bin/env python3
"""
CaseMind 数据初始化工具

用途：
1. 为新用户创建必要的目录结构
2. 提供示例项目供测试
3. 验证环境配置

使用方法：
    python init_data.py              # 交互式初始化
    python init_data.py --demo       # 创建演示项目
    python init_data.py --clean      # 清理所有个人数据（谨慎使用）
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent


def create_directory_structure():
    """创建必要的目录结构"""
    print("📁 创建目录结构...")
    
    dirs = [
        "memory/_global",
        "memory/demo/kp_cache",
        "memory/demo/per_doc",
        "memory/demo/legacy/raw",
        "memory/demo/legacy/cases",
        "memory/demo/legacy/xmind",
        "memory/demo/builds",
        "memory/demo/versions",
        "vector_store",
        "outputs/xmind",
        "outputs/testcases",
        "docs",
    ]
    
    for dir_path in dirs:
        (ROOT / dir_path).mkdir(parents=True, exist_ok=True)
    
    # 创建 .gitkeep 文件
    (ROOT / "memory" / ".gitkeep").touch()
    (ROOT / "vector_store" / ".gitkeep").touch()
    
    print("✅ 目录结构创建完成")


def init_features_config():
    """初始化功能开关配置"""
    print("⚙️  初始化功能配置...")
    
    features_path = ROOT / "memory" / "_global" / "features.json"
    
    if not features_path.exists():
        default_features = {
            "enable_knowledge_extraction": False,
            "enable_hybrid_retrieval": False,
            "enable_case_gen_pipeline": False,
            "enable_coverage_report": False,
            "enable_conflict_detection": False,
            "enable_feedback_loop": False,
            "enable_reranker": False,
            "enable_legacy_style_reference": False,
            "enable_legacy_inference": False,
            "enable_legacy_inference_auto_accept": False,
        }
        
        with open(features_path, 'w', encoding='utf-8') as f:
            json.dump(default_features, f, indent=2, ensure_ascii=False)
        
        print("✅ 功能配置已初始化（所有实验性功能默认关闭）")
    else:
        print("ℹ️  功能配置已存在，跳过")


def create_demo_project():
    """创建演示项目"""
    print("\n🎨 创建演示项目...")
    
    demo_memory_dir = ROOT / "memory" / "demo"
    
    # 创建 project.json
    project_info = {
        "name": "demo",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "CaseMind 演示项目 - 用于测试和学习"
    }
    
    with open(demo_memory_dir / "project.json", 'w', encoding='utf-8') as f:
        json.dump(project_info, f, indent=2, ensure_ascii=False)
    
    # 创建空的 folders.json
    folders_info = {
        "folders": []
    }
    
    with open(demo_memory_dir / "folders.json", 'w', encoding='utf-8') as f:
        json.dump(folders_info, f, indent=2, ensure_ascii=False)
    
    # 创建空的 file_index.json
    file_index = {
        "files": {},
        "last_scan": None
    }
    
    with open(demo_memory_dir / "file_index.json", 'w', encoding='utf-8') as f:
        json.dump(file_index, f, indent=2, ensure_ascii=False)
    
    # 创建示例 memory.md
    memory_content = """# 演示项目记忆

这是一个空的演示项目，用于测试 CaseMind 的功能。

## 快速开始

1. 在前端创建一个新项目或切换到 "demo" 项目
2. 在「目录管理」中添加包含需求文档的文件夹
3. 点击「构建 AI 记忆」开始分析
4. 在「AI 对话」中提问或生成测试用例

## 提示

- 支持 Markdown (.md)、Word (.docx)、PDF (.pdf) 等格式
- 建议使用纯文本格式获得最佳效果
- 大型文档可能需要几分钟处理时间
"""
    
    with open(demo_memory_dir / "memory.md", 'w', encoding='utf-8') as f:
        f.write(memory_content)
    
    # 创建空的 knowledge_points.json
    with open(demo_memory_dir / "knowledge_points.json", 'w', encoding='utf-8') as f:
        json.dump([], f, indent=2, ensure_ascii=False)
    
    print("✅ 演示项目创建完成")
    print("   📂 位置: memory/demo/")
    print("   💡 提示: 添加文档后即可开始使用")


def create_env_example():
    """创建环境变量示例文件"""
    print("\n🔧 创建环境变量模板...")
    
    env_example = ROOT / ".env.example"
    
    if not env_example.exists():
        content = """# CaseMind 环境变量配置示例
# 
# 使用说明：
# 1. 复制此文件为 .env：copy .env.example .env (Windows) 或 cp .env.example .env (Linux/Mac)
# 2. 取消注释并填写实际值
# 3. .env 文件不会被提交到 Git，请放心填写敏感信息
#
# 注意：你也可以在前端「设置」页面配置这些参数（推荐方式）

# ============================================
# LLM 配置（可选，前端配置优先级更高）
# ============================================

# OpenRouter API Base URL
# CASEMIND_DEFAULT_OPENROUTER_BASE=https://openrouter.ai/api/v1

# 默认使用的模型
# CASEMIND_DEFAULT_MODEL=anthropic/claude-3.5-sonnet

# ============================================
# 嵌入模型配置
# ============================================

# 中文嵌入模型（首次使用会自动下载 ~100MB）
# CASEMIND_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5

# 重排序模型（可选，首次使用会下载 ~300MB）
# CASEMIND_RERANKER_MODEL=BAAI/bge-reranker-base

# ============================================
# 功能开关（可选，前端配置优先级更高）
# ============================================

# 知识抽取
# CASEMIND_FEATURES__ENABLE_KNOWLEDGE_EXTRACTION=false

# 混合检索（BM25 + 向量）
# CASEMIND_FEATURES__ENABLE_HYBRID_RETRIEVAL=false

# 用例生成流水线
# CASEMIND_FEATURES__ENABLE_CASE_GEN_PIPELINE=false

# 覆盖率报告
# CASEMIND_FEATURES__ENABLE_COVERAGE_REPORT=false

# 冲突检测
# CASEMIND_FEATURES__ENABLE_CONFLICT_DETECTION=false

# 反馈闭环
# CASEMIND_FEATURES__ENABLE_FEEDBACK_LOOP=false

# 重排序
# CASEMIND_FEATURES__ENABLE_RERANKER=false

# 历史用例风格参考
# CASEMIND_FEATURES__ENABLE_LEGACY_STYLE_REFERENCE=false

# 历史反哺审核
# CASEMIND_FEATURES__ENABLE_LEGACY_INFERENCE=false

# 自动接受高置信反哺（高风险）
# CASEMIND_FEATURES__ENABLE_LEGACY_INFERENCE_AUTO_ACCEPT=false
"""
        
        with open(env_example, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✅ 环境变量模板已创建: .env.example")
    else:
        print("ℹ️  环境变量模板已存在")


def clean_personal_data(dry_run=True):
    """清理个人数据
    
    Args:
        dry_run: 如果为 True，仅显示将要删除的文件，不实际删除
    """
    print("\n⚠️  清理个人数据..." )
    if dry_run:
        print("   🔍 预览模式（不会实际删除）\n")
    else:
        print("   ❌ 警告：这将永久删除所有个人数据！\n")
    
    # 定义要清理的模式
    patterns_to_clean = [
        ("memory/*/builds", True),
        ("memory/*/kp_cache", True),
        ("memory/*/per_doc", True),
        ("memory/*/legacy", True),
        ("memory/*/versions", True),
        ("memory/*/references", True),
        ("memory/*/knowledge_points.json", False),
        ("memory/*/knowledge_points.seq.json", False),
        ("memory/*/conflicts.json", False),
        ("memory/*/feedback.json", False),
        ("memory/*/file_index.json", False),
        ("memory/*/folders.json", False),
        ("memory/*/project.json", False),
        ("memory/*/memory.md", False),
        ("memory/*/memory_prompt.txt", False),
        ("memory/*/chunks.jsonl", False),
        ("vector_store/*.faiss", False),
        ("vector_store/*.npy", False),
        ("vector_store/*.bm25.chunks.pkl", False),
        ("vector_store/*.meta.jsonl", False),
        ("outputs/testcases/*/*", True),
        ("outputs/xmind/*/*", True),
        ("docs/AI用例", True),
        ("docs/国内GM平台", True),
        ("docs/投放管理平台", True),
        ("docs/风格参考", True),
        ("docs/design", True),
        ("rate_limit_report*.json", False),
        ("test_report*.json", False),
        ("test_report.html", False),
    ]
    
    deleted_count = 0
    
    for pattern, is_dir in patterns_to_clean:
        for path in ROOT.glob(pattern):
            if path.exists():
                action = "删除" if not dry_run else "将删除"
                item_type = "目录" if (is_dir or path.is_dir()) else "文件"
                print(f"   {action} {item_type}: {path.relative_to(ROOT)}")
                
                if not dry_run:
                    if is_dir or path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                
                deleted_count += 1
    
    if deleted_count == 0:
        print("   ℹ️  没有需要清理的文件")
    else:
        status = "已清理" if not dry_run else "待清理"
        print(f"\n   ✅ {status} {deleted_count} 个项目")
    
    if dry_run:
        print("\n💡 如需实际清理，请运行: python init_data.py --clean")


def print_usage_guide():
    """打印使用指南"""
    print("\n" + "="*60)
    print("📖 CaseMind 使用指南")
    print("="*60)
    print("""
✨ 快速开始：

1️⃣  启动应用
   Windows: 双击 start.bat
   Linux/Mac: ./start.sh

2️⃣  配置 LLM（首次使用）
   - 打开浏览器 http://127.0.0.1:5173
   - 进入「设置」页面
   - 填写 OpenRouter API Key 和模型

3️⃣  创建项目
   - 进入「项目管理」
   - 点击「新建项目」
   - 输入项目名称（如：我的项目）

4️⃣  添加文档
   - 进入「目录管理」
   - 点击「添加文件夹」
   - 选择包含需求文档的本地文件夹
   - 支持的格式：.md, .docx, .pdf, .txt 等

5️⃣  构建记忆
   - 进入「记忆面板」
   - 点击「构建 AI 记忆」
   - 等待分析完成（时间取决于文档数量）

6️⃣  开始使用
   - 问答模式：基于文档提问
   - 测试用例：自动生成测试用例
   - XMind：生成思维导图
   - 聊天：自由对话

📚 更多信息请查看 README.md
""")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="CaseMind 数据初始化工具")
    parser.add_argument("--demo", action="store_true", help="创建演示项目")
    parser.add_argument("--clean", action="store_true", help="清理所有个人数据")
    parser.add_argument("--preview-clean", action="store_true", help="预览将要清理的数据（不删除）")
    
    args = parser.parse_args()
    
    print("🚀 CaseMind 数据初始化工具")
    print("="*60)
    
    if args.preview_clean or args.clean:
        clean_personal_data(dry_run=not args.clean)
        return
    
    # 默认执行完整初始化
    create_directory_structure()
    init_features_config()
    create_env_example()
    
    if args.demo:
        create_demo_project()
    
    print_usage_guide()
    
    print("\n✅ 初始化完成！你现在可以启动 CaseMind 了。")


if __name__ == "__main__":
    main()
