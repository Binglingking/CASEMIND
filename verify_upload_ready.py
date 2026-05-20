#!/usr/bin/env python3
"""
验证 Git 上传准备状态

检查项目是否已准备好上传到 GitHub
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent

def check_gitignore():
    """检查 .gitignore 是否包含必要的排除规则"""
    print("🔍 检查 .gitignore...")
    
    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        print("   ❌ .gitignore 不存在")
        return False
    
    content = gitignore_path.read_text(encoding='utf-8')
    
    required_patterns = [
        "memory/*/",
        "vector_store/",
        "docs/AI用例/",
        "docs/投放管理平台/",
        ".env",
        ".claude/",
    ]
    
    missing = []
    for pattern in required_patterns:
        if pattern not in content:
            missing.append(pattern)
    
    if missing:
        print(f"   ❌ 缺少排除规则: {missing}")
        return False
    
    print("   ✅ .gitignore 配置正确")
    return True


def check_required_files():
    """检查必要的文件是否存在"""
    print("\n📄 检查必要文件...")
    
    required_files = [
        ("README.md", "项目说明"),
        ("GETTING_STARTED.md", "新手指南"),
        ("MIGRATION_GUIDE.md", "迁移指南"),
        (".env.example", "环境变量模板"),
        ("init_data.py", "初始化脚本"),
    ]
    
    all_exist = True
    for file_path, description in required_files:
        if (ROOT / file_path).exists():
            print(f"   ✅ {file_path} ({description})")
        else:
            print(f"   ❌ {file_path} 缺失 ({description})")
            all_exist = False
    
    return all_exist


def check_personal_data_intact():
    """验证个人数据是否完好（未被删除）"""
    print("\n💾 验证个人数据完整性...")
    
    # 检查一些关键的个人数据文件
    personal_files = [
        "memory/投放管理平台/memory.md",
        "memory/国内GM平台/knowledge_points.json",
        "docs/投放管理平台",
    ]
    
    all_intact = True
    for file_path in personal_files:
        path = ROOT / file_path
        if path.exists():
            status = "目录" if path.is_dir() else "文件"
            print(f"   ✅ {file_path} ({status})")
        else:
            print(f"   ⚠️  {file_path} 不存在（可能已被清理）")
            all_intact = False
    
    if all_intact:
        print("   ✅ 所有个人数据完好无损")
    
    return all_intact


def check_no_hardcoded_secrets():
    """检查是否有硬编码的密钥"""
    print("\n🔐 检查硬编码密钥...")
    
    # 简单的检查：查找常见的密钥模式
    suspicious_patterns = [
        "sk-or-v1-",
        "OPENROUTER_API_KEY = '",
        'OPENROUTER_API_KEY = "',
    ]
    
    found_issues = []
    
    # 检查 Python 文件
    for py_file in ROOT.glob("backend/**/*.py"):
        if "tests" in str(py_file):
            continue
        
        try:
            content = py_file.read_text(encoding='utf-8')
            for pattern in suspicious_patterns:
                if pattern in content:
                    found_issues.append(f"{py_file.relative_to(ROOT)} 包含 '{pattern}'")
        except:
            pass
    
    if found_issues:
        print("   ⚠️  发现潜在问题:")
        for issue in found_issues:
            print(f"      - {issue}")
        return False
    else:
        print("   ✅ 未发现硬编码密钥")
        return True


def check_demo_project():
    """检查演示项目是否存在"""
    print("\n🎨 检查演示项目...")
    
    demo_path = ROOT / "memory" / "demo"
    if demo_path.exists():
        print(f"   ✅ 演示项目存在: {demo_path}")
        return True
    else:
        print("   ℹ️  演示项目不存在（可选）")
        print("   💡 运行 `python init_data.py --demo` 创建")
        return True  # 不是必须的


def main():
    print("="*60)
    print("🚀 CaseMind GitHub 上传准备验证")
    print("="*60)
    
    checks = [
        ("GitIgnore 配置", check_gitignore),
        ("必要文件", check_required_files),
        ("个人数据完整性", check_personal_data_intact),
        ("硬编码密钥检查", check_no_hardcoded_secrets),
        ("演示项目", check_demo_project),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"   ❌ 检查失败: {e}")
            results.append((name, False))
    
    # 汇总结果
    print("\n" + "="*60)
    print("📊 验证结果汇总")
    print("="*60)
    
    all_passed = True
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")
        if not result:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 所有检查通过！项目已准备好上传到 GitHub")
        print("\n下一步:")
        print("1. 初始化 Git: git init")
        print("2. 添加文件: git add .")
        print("3. 检查状态: git status")
        print("4. 提交: git commit -m \"initial commit\"")
        print("5. 关联远程仓库并推送")
    else:
        print("⚠️  存在一些问题，请先解决后再上传")
        print("\n请查看上面的详细检查结果")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
