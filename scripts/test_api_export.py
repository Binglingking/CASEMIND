"""通过HTTP API测试Excel导出"""
import requests
import json

url = "http://127.0.0.1:8888/api/outputs/export-excel"
data = {
    "project": "投放管理平台",
    "kind": "testcase",
    "filename": "testcase_20260507-083220.json"
}

print(f"测试API: {url}")
print(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
print("=" * 60)

try:
    response = requests.post(url, json=data)
    print(f"响应状态码: {response.status_code}")
    print(f"响应头: {dict(response.headers)}")
    
    if response.status_code == 200:
        # 保存文件
        output_path = "test_api_export.xlsx"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        print(f"✅ 导出成功!")
        print(f"文件大小: {len(response.content)} bytes")
        print(f"文件已保存到: {output_path}")
    else:
        print(f"❌ 导出失败!")
        print(f"响应内容: {response.text}")
        try:
            error_data = response.json()
            print(f"错误信息: {error_data}")
        except:
            pass
            
except Exception as e:
    print(f"❌ 请求失败: {e}")
    import traceback
    traceback.print_exc()
