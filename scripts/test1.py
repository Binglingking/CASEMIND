import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RateLimitConfig:
    """API限流配置类"""

    def __init__(self, api: str, max_requests: int, interval: int, qps: int):
        self.api = api
        self.ip_max_requests_per_time_unit = max_requests  # IP最大请求数
        self.ip_request_interval_time = interval  # 请求间隔时间(秒)
        self.qps = qps  # QPS限制

    def __str__(self):
        return (f"API={self.api}, "
                f"最大请求数={self.ip_max_requests_per_time_unit}, "
                f"间隔={self.ip_request_interval_time}s, "
                f"QPS={self.qps}")

    def to_dict(self):
        return {
            "api": self.api,
            "ip_max_requests_per_time_unit": self.ip_max_requests_per_time_unit,
            "ip_request_interval_time": self.ip_request_interval_time,
            "qps": self.qps
        }


class ConfigInput:
    """交互式配置输入工具"""

    @staticmethod
    def get_int_input(prompt: str, default: int, min_val: int = 1, max_val: int = 1000000) -> int:
        """获取整数输入，支持默认值"""
        while True:
            user_input = input(f"{prompt} [默认={default}]: ").strip()
            if not user_input:
                return default
            try:
                value = int(user_input)
                if min_val <= value <= max_val:
                    return value
                else:
                    print(f"  ⚠️  请输入 {min_val} 到 {max_val} 之间的整数")
            except ValueError:
                print(f"  ⚠️  输入无效，请输入整数")

    @staticmethod
    def get_yes_no(prompt: str, default: bool = True) -> bool:
        """获取是/否输入"""
        default_str = "Y/n" if default else "y/N"
        user_input = input(f"{prompt} [{default_str}]: ").strip().lower()
        if not user_input:
            return default
        return user_input in ['y', 'yes', '是', '1', 'true']

    @staticmethod
    def collect_rate_limit_configs() -> List[RateLimitConfig]:
        """交互式收集限流配置"""
        print("\n" + "=" * 80)
        print("📝 API限流参数配置")
        print("=" * 80)
        print("请输入当前服务端配置的限流参数（直接回车使用默认值）")
        print("-" * 80)

        configs = []
        apis = ["/api/list", "/api/view"]

        # 询问是否两个API使用相同配置
        same_config = ConfigInput.get_yes_no(
            "\n两个API (/api/list 和 /api/view) 是否使用相同的限流配置?",
            default=True
        )

        if same_config:
            print(f"\n请输入通用限流配置：")
            max_req = ConfigInput.get_int_input(
                "  最大请求数(ip_max_requests_per_time_unit)", 100)
            interval = ConfigInput.get_int_input(
                "  请求间隔时间(ip_request_interval_time, 秒)", 10)
            qps = ConfigInput.get_int_input(
                "  QPS(qps)", 10000)

            for api in apis:
                configs.append(RateLimitConfig(api, max_req, interval, qps))
        else:
            for api in apis:
                print(f"\n请输入 {api} 的限流配置：")
                max_req = ConfigInput.get_int_input(
                    "  最大请求数(ip_max_requests_per_time_unit)", 100)
                interval = ConfigInput.get_int_input(
                    "  请求间隔时间(ip_request_interval_time, 秒)", 10)
                qps = ConfigInput.get_int_input(
                    "  QPS(qps)", 10000)

                configs.append(RateLimitConfig(api, max_req, interval, qps))

        # 打印配置确认
        print("\n" + "=" * 80)
        print("✅ 本次测试使用的限流配置:")
        print("=" * 80)
        print(json.dumps({
            "api_limit_rule": [c.to_dict() for c in configs]
        }, indent=2, ensure_ascii=False))

        if not ConfigInput.get_yes_no("\n确认以上配置并开始测试?", default=True):
            print("❌ 已取消测试")
            exit(0)

        return configs


class RateLimitTester:
    """API服务限制测试器 - 支持动态参数配置"""

    def __init__(self, configs: List[RateLimitConfig],
                 base_url: str = "https://test-table-builder-iapi.yostar.net"):
        self.base_url = base_url
        self.view_url = f"{base_url}/api/view"
        self.list_url = f"{base_url}/api/list"
        self.headers = {'Content-Type': 'application/json'}

        self.auth_data = {
            "auth_id": "test1",
            "auth_key": "1b4f0e9851971998e732078544c96b36c3d01cedf7caa332359d6f1d83567014",
            "project_id": "cmth0gon25ng3rejrqog",
            "pid": "CN-BA",
            "db_name": "zstest",
            "table_name": "zs001"
        }
        self.test_record_id = "2052587049215737856"

        # 按API存储配置
        self.configs = {c.api: c for c in configs}
        self.test_results = []

    def _build_view_payload(self) -> str:
        return json.dumps({
            "meta_data": self.auth_data,
            "_id": self.test_record_id,
            "timezone": "UTC+8",
            "fields": ["_id", "wb", "_created", "_updated", "_creator", "_updater"]
        })

    def _build_list_payload(self, page: int = 1, page_size: int = 10) -> str:
        return json.dumps({
            "collection_id": "2052586904642273280",
            "version_id": "2052586904642273281",
            "meta_data": self.auth_data,
            "timezone": "UTC+8",
            "page": page,
            "page_size": page_size,
            "filters": []
        })

    def _send_request(self, api: str) -> Dict[str, Any]:
        """发送请求（根据api类型）"""
        start = time.time()
        try:
            if api == "/api/view":
                url = self.view_url
                payload = self._build_view_payload()
            else:
                url = self.list_url
                payload = self._build_list_payload()

            resp = requests.post(url, headers=self.headers, data=payload, timeout=15)
            elapsed = time.time() - start

            result = {
                "api": api,
                "http_status": resp.status_code,
                "elapsed": elapsed,
                "timestamp": time.time()
            }
            try:
                resp_json = resp.json()
                result["code"] = resp_json.get("code")
                result["msg"] = resp_json.get("msg", "")
                result["response"] = resp_json
            except:
                result["response_text"] = resp.text

            return result
        except Exception as e:
            return {
                "api": api,
                "http_status": -1,
                "error": str(e),
                "timestamp": time.time(),
                "elapsed": time.time() - start
            }

    def _is_rate_limited(self, result: Dict) -> bool:
        """判断响应是否为限流响应"""
        http_status = result.get("http_status")
        code = result.get("code")
        msg = str(result.get("msg", "")).lower()

        if http_status in [429, 503]:
            return True

        if code is not None and code != 200:
            # 排除鉴权错误
            if code in [100414, 100413, 100411]:
                return False
            # 限流关键词匹配
            limit_keywords = ["limit", "rate", "限流", "频繁", "too many",
                              "quota", "超出", "超过", "busy", "throttle"]
            if any(kw in msg for kw in limit_keywords):
                return True
            # 特定业务码（可以根据实际情况扩展）
            if 100000 <= code <= 109999 and code not in [100414, 100413, 100411]:
                return True

        return False

    # ==================== 测试1: QPS限制测试 ====================

    def test_qps_limit(self, api: str):
        """测试QPS限制 - 动态根据配置的QPS值发起超额并发请求"""
        config = self.configs[api]
        qps_limit = config.qps

        # 策略：发送 qps_limit * 1.5 个并发请求
        # 如果QPS很大（如10000），为了不消耗太多配额，限制上限为500
        test_requests = min(int(qps_limit * 1.5), 500)
        if qps_limit >= 1000:
            test_requests = min(int(qps_limit * 0.3), 500)  # 大QPS时只测试30%
            print(f"  💡 QPS较大({qps_limit})，仅发送{test_requests}个并发请求进行基础验证")

        print("\n" + "=" * 80)
        print(f"【TC-QPS】QPS限制测试 - {api}")
        print("=" * 80)
        print(f"配置: QPS={qps_limit}")
        print(f"策略: 1秒内并发发送 {test_requests} 个请求")

        results = []
        start_time = time.time()

        max_workers = min(test_requests, 200)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._send_request, api)
                       for _ in range(test_requests)]
            for future in as_completed(futures):
                results.append(future.result())

        total_time = time.time() - start_time
        successful = sum(1 for r in results if r.get("code") == 200)
        rate_limited = sum(1 for r in results if self._is_rate_limited(r))
        errors = sum(1 for r in results if r.get("http_status") == -1)
        actual_qps = test_requests / total_time

        print(f"\n📊 测试结果:")
        print(f"  总请求数: {test_requests}")
        print(f"  总耗时: {total_time:.2f}s")
        print(f"  实际QPS: {actual_qps:.2f}")
        print(f"  ✓ 成功: {successful}")
        print(f"  🔒 被限流: {rate_limited}")
        print(f"  ❌ 错误: {errors}")

        # 打印限流样本
        if rate_limited > 0:
            samples = [r for r in results if self._is_rate_limited(r)][:2]
            print(f"\n🔒 限流响应样本:")
            for i, s in enumerate(samples, 1):
                print(f"  样本{i}: HTTP={s.get('http_status')}, "
                      f"code={s.get('code')}, msg={s.get('msg')}")

        # 断言逻辑：根据配置的QPS判断
        passed = False
        conclusion = ""

        if qps_limit >= 1000 and test_requests < qps_limit:
            # 大QPS场景，未达上限，所有请求都应成功
            if successful >= test_requests * 0.95:
                passed = True
                conclusion = f"✓ QPS={qps_limit}足够大，{test_requests}个并发请求成功率{successful / test_requests * 100:.1f}%"
            else:
                conclusion = f"⚠️  预期高QPS下全部成功，实际只有{successful}个成功"
        else:
            # 小QPS场景，应该有请求被限流
            expected_limited_min = int(test_requests * 0.2)  # 至少20%被限流
            if rate_limited >= expected_limited_min:
                passed = True
                conclusion = f"✓ QPS限制生效：{rate_limited}个请求被限流（符合预期≥{expected_limited_min}）"
            elif successful >= test_requests * 0.95:
                conclusion = f"⚠️  疑似缺陷：超出QPS={qps_limit}的请求未被限流"
            else:
                conclusion = f"⚠️  限流触发不明显：成功{successful}, 限流{rate_limited}"

        print(f"\n结论: {conclusion}")

        self.test_results.append({
            "case": f"TC-QPS {api} QPS={qps_limit}",
            "passed": passed,
            "conclusion": conclusion,
            "config": config.to_dict(),
            "details": {
                "total": test_requests,
                "successful": successful,
                "rate_limited": rate_limited,
                "errors": errors,
                "actual_qps": f"{actual_qps:.2f}",
                "duration": f"{total_time:.2f}s"
            }
        })

        return results

    # ==================== 测试2: 最大请求数(IP)限制测试 ====================

    def test_max_requests_limit(self, api: str):
        """测试IP最大请求数限制 - 动态根据配置值"""
        config = self.configs[api]
        max_req = config.ip_max_requests_per_time_unit
        qps = config.qps

        # 发送 max_req * 1.2 个请求（多20%验证限制点）
        test_requests = int(max_req * 1.2)

        # 控制发送速率，避免触发QPS限制干扰测试
        # 发送速率 = min(qps的50%, 100/s)
        send_qps = min(qps * 0.5, 100)
        interval = 1.0 / send_qps

        estimated_time = test_requests * interval

        print("\n" + "=" * 80)
        print(f"【TC-MAX-REQ】最大请求数限制测试 - {api}")
        print("=" * 80)
        print(f"配置: 最大请求数={max_req}, QPS={qps}")
        print(f"策略: 串行发送 {test_requests} 个请求（发送QPS≈{send_qps:.0f}）")
        print(f"⏱  预计耗时: {estimated_time:.1f}秒")

        results = []
        for i in range(test_requests):
            result = self._send_request(api)
            result["request_no"] = i + 1
            results.append(result)

            # 进度打印
            if (i + 1) % max(1, test_requests // 10) == 0:
                success = sum(1 for r in results if r.get("code") == 200)
                limited = sum(1 for r in results if self._is_rate_limited(r))
                print(f"  [{i + 1}/{test_requests}] 成功:{success}, 限流:{limited}")

            time.sleep(interval)

        # 查找首次触发限流的请求编号
        first_limited_no = None
        for r in results:
            if self._is_rate_limited(r):
                first_limited_no = r.get("request_no")
                break

        # 统计
        total_success = sum(1 for r in results if r.get("code") == 200)
        total_limited = sum(1 for r in results if self._is_rate_limited(r))

        print(f"\n📊 测试结果:")
        print(f"  总请求: {test_requests}, 成功: {total_success}, 限流: {total_limited}")

        if first_limited_no:
            print(f"  🔒 首次限流触发: 第 {first_limited_no} 个请求")
            limit_sample = next(r for r in results if self._is_rate_limited(r))
            print(f"  限流响应: HTTP={limit_sample.get('http_status')}, "
                  f"code={limit_sample.get('code')}, msg={limit_sample.get('msg')}")
        else:
            print(f"  ⚠️  所有 {test_requests} 个请求均成功，未触发限流！")

        # 断言：允许±10%的误差范围
        tolerance = max(5, int(max_req * 0.1))
        lower_bound = max_req - tolerance + 1  # 第(max_req-tolerance+1)个开始可以限流
        upper_bound = max_req + tolerance + 1  # 第(max_req+tolerance+1)个之前必须限流

        passed = False
        conclusion = ""
        if first_limited_no and lower_bound <= first_limited_no <= upper_bound:
            passed = True
            conclusion = (f"✓ IP限流在第{first_limited_no}个触发，"
                          f"符合预期范围[{lower_bound}, {upper_bound}]")
        elif first_limited_no and first_limited_no < lower_bound:
            conclusion = (f"⚠️  限流过早触发（第{first_limited_no}个），"
                          f"期望范围[{lower_bound}, {upper_bound}]，实际限制值可能<{max_req}")
        elif first_limited_no and first_limited_no > upper_bound:
            conclusion = (f"⚠️  限流过晚触发（第{first_limited_no}个），"
                          f"期望范围[{lower_bound}, {upper_bound}]，实际限制值可能>{max_req}")
        else:
            conclusion = f"❌ 疑似缺陷：发送{test_requests}个请求未触发限流（配置值={max_req}）"

        print(f"\n结论: {conclusion}")

        self.test_results.append({
            "case": f"TC-MAX-REQ {api} 最大请求数={max_req}",
            "passed": passed,
            "conclusion": conclusion,
            "config": config.to_dict(),
            "details": {
                "configured_max": max_req,
                "total_sent": test_requests,
                "total_success": total_success,
                "total_limited": total_limited,
                "first_limited_request_no": first_limited_no,
                "expected_range": f"[{lower_bound}, {upper_bound}]"
            }
        })

        return results

    # ==================== 测试3: 请求间隔恢复测试 ====================

    def test_interval_recovery(self, api: str):
        """测试请求间隔恢复 - 动态根据配置的interval值"""
        config = self.configs[api]
        interval_sec = config.ip_request_interval_time
        max_req = config.ip_max_requests_per_time_unit

        print("\n" + "=" * 80)
        print(f"【TC-INTERVAL】请求间隔恢复测试 - {api}")
        print("=" * 80)
        print(f"配置: 最大请求数={max_req}, 请求间隔={interval_sec}秒")
        print(f"策略: 触发限流 → 等待{interval_sec}秒 → 验证恢复")

        # 步骤1: 触发限流
        print(f"\n步骤1: 快速发送 {max_req + 20} 个请求，触发限流...")
        trigger_results = []
        for i in range(max_req + 20):
            r = self._send_request(api)
            trigger_results.append(r)
            if (i + 1) % 20 == 0:
                limited = sum(1 for x in trigger_results if self._is_rate_limited(x))
                print(f"  已发送 {i + 1}, 已触发限流 {limited} 次")
            # 快速发送但不超过QPS上限
            time.sleep(min(0.01, 1.0 / config.qps))

        triggered = any(self._is_rate_limited(r) for r in trigger_results)

        if not triggered:
            print(f"  ⚠️  未能触发限流，无法进行恢复测试")
            self.test_results.append({
                "case": f"TC-INTERVAL {api} 间隔={interval_sec}s",
                "passed": False,
                "conclusion": "⚠️ 无法触发限流，测试无法进行",
                "config": config.to_dict(),
                "details": {"triggered": False}
            })
            return

        # 步骤2: 立即再试（应仍被限流）
        print(f"\n步骤2: 立即请求（预期仍被限流）...")
        immediate = self._send_request(api)
        immediate_limited = self._is_rate_limited(immediate)
        print(f"  结果: {'被限流 ✓' if immediate_limited else '成功（意外！）'} "
              f"- code={immediate.get('code')}, msg={immediate.get('msg')}")

        # 步骤3: 等待 interval_sec 秒
        print(f"\n步骤3: 等待配置的间隔时间 {interval_sec} 秒...")
        for remain in range(interval_sec, 0, -1):
            print(f"  倒计时 {remain}s ...   ", end='\r')
            time.sleep(1)
        print("  等待完成                    ")

        # 步骤4: 验证恢复
        print(f"\n步骤4: {interval_sec}秒后再次请求（预期恢复）...")
        recovery = self._send_request(api)
        recovered = recovery.get("code") == 200
        print(f"  结果: {'恢复成功 ✓' if recovered else '仍被限流 ✗'} "
              f"- code={recovery.get('code')}, msg={recovery.get('msg')}")

        # 附加：测试是否"早于"interval就恢复了（验证interval的严格性）
        # 这里不执行以避免干扰，但可以在报告中建议

        passed = recovered and immediate_limited
        conclusion = ""
        if recovered and immediate_limited:
            conclusion = f"✓ 限流在{interval_sec}秒后正确恢复，符合配置"
        elif not immediate_limited:
            conclusion = "⚠️  限流状态不稳定：触发后立即可再次请求"
        elif not recovered:
            conclusion = f"⚠️  {interval_sec}秒后仍被限流，恢复时间可能 > {interval_sec}秒"

        print(f"\n结论: {conclusion}")

        self.test_results.append({
            "case": f"TC-INTERVAL {api} 间隔={interval_sec}s",
            "passed": passed,
            "conclusion": conclusion,
            "config": config.to_dict(),
            "details": {
                "configured_interval": interval_sec,
                "triggered": triggered,
                "immediate_still_limited": immediate_limited,
                "recovered_after_interval": recovered,
                "recovery_code": recovery.get("code"),
                "recovery_msg": recovery.get("msg")
            }
        })

    # ==================== 测试4: 边界值测试 ====================

    def test_boundary(self, api: str):
        """边界值测试 - 精确在 max_req 处的表现"""
        config = self.configs[api]
        max_req = config.ip_max_requests_per_time_unit

        print("\n" + "=" * 80)
        print(f"【TC-BOUNDARY】边界值测试 - {api}")
        print("=" * 80)
        print(f"策略: 精确发送 {max_req} 个请求（边界值），全部应成功")

        # 发送速率控制在QPS的50%
        interval = 1.0 / min(config.qps * 0.5, 100)

        results = []
        for i in range(max_req):
            r = self._send_request(api)
            results.append(r)
            time.sleep(interval)

        success = sum(1 for r in results if r.get("code") == 200)
        limited = sum(1 for r in results if self._is_rate_limited(r))

        print(f"\n📊 测试结果:")
        print(f"  发送 {max_req} 个请求: 成功={success}, 限流={limited}")

        passed = success >= max_req * 0.95  # 允许5%的网络波动
        conclusion = ""
        if passed:
            conclusion = f"✓ 边界内({max_req}个)请求成功率{success / max_req * 100:.1f}%，符合预期"
        else:
            conclusion = f"⚠️  边界内请求成功率不足: {success}/{max_req}"

        print(f"\n结论: {conclusion}")

        # 额外测试第 max_req + 1 个请求
        print(f"\n额外验证: 发送第 {max_req + 1} 个请求（应被限流）...")
        extra = self._send_request(api)
        extra_limited = self._is_rate_limited(extra)
        print(f"  结果: {'被限流 ✓' if extra_limited else '成功（可能未限流）'} "
              f"- code={extra.get('code')}, msg={extra.get('msg')}")

        self.test_results.append({
            "case": f"TC-BOUNDARY {api} 边界={max_req}",
            "passed": passed and extra_limited,
            "conclusion": conclusion + f"; 超限第{max_req + 1}个请求{'被限流' if extra_limited else '未被限流'}",
            "config": config.to_dict(),
            "details": {
                "boundary_requests": max_req,
                "success_in_boundary": success,
                "limited_in_boundary": limited,
                "exceed_request_limited": extra_limited
            }
        })

    # ==================== 报告生成 ====================

    def generate_report(self):
        print("\n" + "=" * 80)
        print("🧪 API服务限制测试 - 最终报告")
        print("=" * 80)

        total = len(self.test_results)
        passed = sum(1 for t in self.test_results if t["passed"])

        print(f"\n测试总数: {total}")
        print(f"通过: {passed} ✓")
        print(f"失败: {total - passed} ✗")
        print(f"通过率: {passed / total * 100 if total else 0:.1f}%")

        print(f"\n📋 测试用例详情:")
        print("-" * 80)
        for tc in self.test_results:
            status = "✓ PASS" if tc["passed"] else "✗ FAIL"
            print(f"\n  [{status}] {tc['case']}")
            print(f"    配置: {tc['config']}")
            print(f"    结论: {tc['conclusion']}")
            print(f"    数据: {json.dumps(tc['details'], ensure_ascii=False)}")

        # 保存JSON报告
        report = {
            "timestamp": datetime.now().isoformat(),
            "test_configs": [c.to_dict() for c in self.configs.values()],
            "summary": {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": f"{passed / total * 100 if total else 0:.1f}%"
            },
            "test_cases": self.test_results
        }

        # 使用时间戳命名报告
        report_name = f"rate_limit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_name, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✓ 报告已保存: {report_name}")
        print("=" * 80)


def select_test_suite() -> List[str]:
    """让用户选择要运行的测试用例"""
    print("\n" + "=" * 80)
    print("🎯 选择要执行的测试")
    print("=" * 80)
    print("  1) QPS限制测试           (TC-QPS)")
    print("  2) 最大请求数限制测试     (TC-MAX-REQ)")
    print("  3) 请求间隔恢复测试       (TC-INTERVAL)")
    print("  4) 边界值测试            (TC-BOUNDARY)")
    print("  5) 全部测试 (推荐)")
    print("-" * 80)

    choice = input("请选择 [1-5，多选用逗号分隔，默认=5]: ").strip() or "5"

    if "5" in choice:
        return ["qps", "max_req", "interval", "boundary"]

    selected = []
    mapping = {"1": "qps", "2": "max_req", "3": "interval", "4": "boundary"}
    for c in choice.split(","):
        c = c.strip()
        if c in mapping:
            selected.append(mapping[c])

    return selected or ["qps", "max_req", "interval", "boundary"]


def select_test_apis() -> List[str]:
    """让用户选择要测试的API"""
    print("\n" + "=" * 80)
    print("🎯 选择要测试的API")
    print("=" * 80)
    print("  1) /api/view")
    print("  2) /api/list")
    print("  3) 全部 (推荐)")
    print("-" * 80)

    choice = input("请选择 [1-3，默认=3]: ").strip() or "3"

    if "3" in choice:
        return ["/api/view", "/api/list"]
    elif "1" in choice and "2" in choice:
        return ["/api/view", "/api/list"]
    elif "1" in choice:
        return ["/api/view"]
    elif "2" in choice:
        return ["/api/list"]
    else:
        return ["/api/view", "/api/list"]


def main():
    print("\n" + "=" * 80)
    print("🚦 API 服务限制动态测试套件")
    print("=" * 80)
    print("本工具可根据服务端实际配置的限流参数进行测试验证")
    print("=" * 80)

    # 步骤1: 交互式输入限流配置
    configs = ConfigInput.collect_rate_limit_configs()

    # 步骤2: 选择测试API
    test_apis = select_test_apis()

    # 步骤3: 选择测试用例
    test_cases = select_test_suite()

    # 预估耗时
    print("\n" + "=" * 80)
    print("📊 测试计划:")
    print("=" * 80)
    print(f"  测试API: {test_apis}")
    print(f"  测试用例: {test_cases}")

    estimated_min = 0
    for api in test_apis:
        config = next(c for c in configs if c.api == api)
        if "qps" in test_cases:
            estimated_min += 0.5
        if "max_req" in test_cases:
            estimated_min += config.ip_max_requests_per_time_unit * 1.2 * 0.02 / 60
        if "interval" in test_cases:
            estimated_min += (config.ip_request_interval_time + 10) / 60
        if "boundary" in test_cases:
            estimated_min += config.ip_max_requests_per_time_unit * 0.02 / 60

    print(f"  预计耗时: ~{estimated_min:.1f} 分钟（含冷却等待）")
    print("=" * 80)

    if not ConfigInput.get_yes_no("\n开始执行测试?", default=True):
        print("已取消")
        return

    # 执行测试
    tester = RateLimitTester(configs)

    try:
        for api in test_apis:
            print(f"\n\n{'#' * 80}")
            print(f"# 开始测试 API: {api}")
            print(f"{'#' * 80}")

            config = tester.configs[api]
            cooldown = max(config.ip_request_interval_time + 5, 15)

            if "qps" in test_cases:
                tester.test_qps_limit(api)
                print(f"\n⏱  冷却 {cooldown} 秒...")
                time.sleep(cooldown)

            if "boundary" in test_cases:
                tester.test_boundary(api)
                print(f"\n⏱  冷却 {cooldown} 秒...")
                time.sleep(cooldown)

            if "max_req" in test_cases:
                tester.test_max_requests_limit(api)
                print(f"\n⏱  冷却 {cooldown} 秒...")
                time.sleep(cooldown)

            if "interval" in test_cases:
                tester.test_interval_recovery(api)
                print(f"\n⏱  冷却 {cooldown} 秒...")
                time.sleep(cooldown)

    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")
    except Exception as e:
        logger.error(f"测试异常: {e}", exc_info=True)
    finally:
        tester.generate_report()


if __name__ == "__main__":
    main()