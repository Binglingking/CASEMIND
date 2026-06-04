import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestResult:
    """测试结果类，带断言功能"""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.passed = False
        self.expected = None
        self.actual = None
        self.message = ""
        self.details = {}

    def assert_equal(self, expected, actual, message=""):
        self.expected = expected
        self.actual = actual
        self.passed = (expected == actual)
        self.message = message
        return self

    def assert_in(self, expected_list, actual, message=""):
        self.expected = f"in {expected_list}"
        self.actual = actual
        self.passed = (actual in expected_list)
        self.message = message
        return self

    def assert_true(self, condition, message=""):
        self.expected = True
        self.actual = condition
        self.passed = bool(condition)
        self.message = message
        return self

    def assert_not_none(self, value, message=""):
        self.expected = "not None"
        self.actual = value
        self.passed = (value is not None)
        self.message = message
        return self

    def to_dict(self):
        return {
            "test_name": self.test_name,
            "passed": self.passed,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "message": self.message,
            "details": self.details
        }


class ResponseValidator:
    """响应格式验证器"""

    # 预期的公共字段
    COMMON_FIELDS = ["_id", "_created", "_creator", "_updated", "_updater"]

    # view接口必须的响应字段
    VIEW_RESPONSE_FIELDS = ["code", "data", "msg"]

    # list接口必须的响应字段
    LIST_RESPONSE_FIELDS = ["code", "data", "msg"]

    # paginate必须的字段
    PAGINATE_FIELDS = ["page", "page_size", "total"]

    @staticmethod
    def validate_view_response(response: Dict) -> Dict[str, Any]:
        """验证view接口响应格式
        预期格式：
        {
            "code": 200,
            "data": {...记录字段...},
            "msg": "OK"
        }
        """
        errors = []

        # 检查顶层字段
        for field in ResponseValidator.VIEW_RESPONSE_FIELDS:
            if field not in response:
                errors.append(f"缺少顶层字段: {field}")

        # 检查code类型
        if "code" in response and not isinstance(response["code"], int):
            errors.append(f"code字段类型错误: 期望int, 实际{type(response['code']).__name__}")

        # 检查msg类型
        if "msg" in response and not isinstance(response["msg"], str):
            errors.append(f"msg字段类型错误: 期望str, 实际{type(response['msg']).__name__}")

        # 成功响应时验证data结构
        if response.get("code") == 200 and response.get("data"):
            data = response["data"]
            if not isinstance(data, dict):
                errors.append(f"data字段类型错误: 期望dict, 实际{type(data).__name__}")
            else:
                # 检查公共字段
                for field in ResponseValidator.COMMON_FIELDS:
                    if field not in data:
                        errors.append(f"data中缺少字段: {field}")

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    @staticmethod
    def validate_list_response(response: Dict) -> Dict[str, Any]:
        """验证list接口响应格式
        预期格式：
        {
            "code": 200,
            "data": {
                "list": [...],
                "paginate": {"page": 1, "page_size": 10, "total": 1}
            },
            "msg": "OK"
        }
        """
        errors = []

        # 检查顶层字段
        for field in ResponseValidator.LIST_RESPONSE_FIELDS:
            if field not in response:
                errors.append(f"缺少顶层字段: {field}")

        # 成功响应时验证data结构
        if response.get("code") == 200:
            data = response.get("data")
            if not isinstance(data, dict):
                errors.append(f"data字段类型错误: 期望dict, 实际{type(data).__name__}")
                return {"valid": len(errors) == 0, "errors": errors}

            # 检查list字段
            if "list" not in data:
                errors.append("data中缺少list字段")
            elif not isinstance(data["list"], list):
                errors.append(f"list字段类型错误: 期望list, 实际{type(data['list']).__name__}")
            else:
                # 检查list中每条记录的字段
                for idx, item in enumerate(data["list"]):
                    if not isinstance(item, dict):
                        errors.append(f"list[{idx}] 不是dict类型")
                        continue
                    for field in ResponseValidator.COMMON_FIELDS:
                        if field not in item:
                            errors.append(f"list[{idx}] 缺少字段: {field}")

            # 检查paginate字段
            if "paginate" not in data:
                errors.append("data中缺少paginate字段")
            elif not isinstance(data["paginate"], dict):
                errors.append(f"paginate字段类型错误")
            else:
                paginate = data["paginate"]
                for field in ResponseValidator.PAGINATE_FIELDS:
                    if field not in paginate:
                        errors.append(f"paginate中缺少字段: {field}")
                    elif not isinstance(paginate[field], int):
                        errors.append(f"paginate.{field}类型错误: 期望int")

                # 逻辑校验
                if all(k in paginate for k in ["page", "page_size", "total"]):
                    if paginate["page"] < 1:
                        errors.append(f"paginate.page值异常: {paginate['page']}")
                    if paginate["page_size"] < 1:
                        errors.append(f"paginate.page_size值异常: {paginate['page_size']}")
                    if paginate["total"] < 0:
                        errors.append(f"paginate.total值异常: {paginate['total']}")
                    # list数量应该 <= page_size
                    if "list" in data and len(data["list"]) > paginate["page_size"]:
                        errors.append(f"返回list数量({len(data['list'])})超过page_size({paginate['page_size']})")

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }


class APITester:
    """API测试器类"""

    def __init__(self, base_url: str = "https://test-table-builder-iapi.yostar.net"):
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

        self.api_limits = {
            "/api/list": {"max_requests": 100, "request_interval": 10, "qps": 100},
            "/api/view": {"max_requests": 100, "request_interval": 10, "qps": 100}
        }

        self.request_count = {"/api/list": 0, "/api/view": 0}
        self.last_request_time = {"/api/list": 0, "/api/view": 0}
        self.lock = threading.Lock()
        self.test_results: List[TestResult] = []

    def create_view_payload(self, record_id: str = None,
                            auth_override: Optional[Dict] = None) -> str:
        """创建view请求payload"""
        auth = auth_override if auth_override else self.auth_data
        payload = {
            "meta_data": auth,
            "_id": record_id or self.test_record_id,
            "timezone": "UTC+8",
            "fields": ["_id", "wb", "_created", "_updated", "_creator", "_updater", "status"]
        }
        return json.dumps(payload)

    def create_list_payload(self, page: int = 1, page_size: int = 10,
                            auth_override: Optional[Dict] = None,
                            filters_override: Optional[List] = None) -> str:
        """创建list请求payload"""
        auth = auth_override if auth_override else self.auth_data
        default_filters = [
            {"field_name": "_id", "expression": 1, "value": self.test_record_id},
            {"field_name": "wb", "expression": 9, "value": "zs"},
        ]
        filters = filters_override if filters_override is not None else default_filters

        payload = {
            "collection_id": "2052586904642273280",
            "version_id": "2052586904642273281",
            "meta_data": auth,
            "timezone": "UTC+8",
            "page": page,
            "page_size": page_size,
            "filters": filters
        }
        return json.dumps(payload)

    def _send_request(self, url: str, endpoint: str, payload: str,
                      check_limit: bool = True) -> Dict[str, Any]:
        """通用请求发送方法"""
        if check_limit and not self._check_rate_limit(endpoint):
            return {"status": "failed", "reason": "Rate limit exceeded", "endpoint": endpoint}

        try:
            start_time = time.time()
            response = requests.post(url, headers=self.headers, data=payload, timeout=15)
            elapsed_time = time.time() - start_time

            with self.lock:
                self.request_count[endpoint] += 1

            result = {
                "endpoint": endpoint,
                "status_code": response.status_code,
                "response_time": elapsed_time,
                "request_count": self.request_count[endpoint],
                "success": response.status_code == 200
            }

            try:
                response_json = response.json()
                result["response_data"] = response_json
                result["response_code"] = response_json.get("code")
                result["response_msg"] = response_json.get("msg", "")
                result["data"] = response_json.get("data")
            except:
                result["response_data"] = response.text

            return result
        except requests.exceptions.Timeout:
            return {"endpoint": endpoint, "status": "timeout", "success": False}
        except Exception as e:
            return {"endpoint": endpoint, "status": "failed", "error": str(e), "success": False}

    def _check_rate_limit(self, endpoint: str) -> bool:
        """检查速率限制"""
        with self.lock:
            limit = self.api_limits[endpoint]
            if self.request_count[endpoint] >= limit["max_requests"]:
                logger.warning(f"[{endpoint}] 已达最大请求数限制")
                return False

            current = time.time()
            elapsed = current - self.last_request_time[endpoint]
            min_interval = 1.0 / limit["qps"]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

            self.last_request_time[endpoint] = time.time()
            return True

    def test_view(self, record_id: str = None, auth_override: Optional[Dict] = None,
                  check_limit: bool = True) -> Dict[str, Any]:
        """发送view请求"""
        payload = self.create_view_payload(record_id, auth_override)
        return self._send_request(self.view_url, "/api/view", payload, check_limit)

    def test_list(self, page: int = 1, page_size: int = 10,
                  auth_override: Optional[Dict] = None,
                  filters_override: Optional[List] = None,
                  check_limit: bool = True) -> Dict[str, Any]:
        """发送list请求"""
        payload = self.create_list_payload(page, page_size, auth_override, filters_override)
        return self._send_request(self.list_url, "/api/list", payload, check_limit)

    # ==================== 测试用例 ====================

    def test_case_view_response_format(self):
        """TC01: View接口响应格式完整性测试"""
        print("\n" + "=" * 80)
        print("[TC01] View接口响应格式验证")
        print("=" * 80)

        result = self.test_view()
        response_data = result.get("response_data", {})

        # 1.1 HTTP状态码
        tr = TestResult("TC01.1 View - HTTP状态码=200")
        tr.assert_equal(200, result.get("status_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.2 响应code=200
        tr = TestResult("TC01.2 View - 业务code=200")
        tr.assert_equal(200, response_data.get("code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.3 msg="OK"
        tr = TestResult("TC01.3 View - msg字段='OK'")
        tr.assert_equal("OK", response_data.get("msg"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.4 完整响应结构验证
        validation = ResponseValidator.validate_view_response(response_data)
        tr = TestResult("TC01.4 View - 完整响应结构验证")
        tr.assert_true(validation["valid"],
                       "结构无误" if validation["valid"] else f"错误: {validation['errors']}")
        tr.details = validation
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.5 验证data中的_id与请求一致
        data = response_data.get("data", {})
        tr = TestResult("TC01.5 View - 返回的_id与请求一致")
        tr.assert_equal(self.test_record_id, data.get("_id"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.6 验证必需字段都存在
        required_fields = ["_id", "_created", "_creator", "_updated", "_updater", "wb"]
        missing = [f for f in required_fields if f not in data]
        tr = TestResult("TC01.6 View - 必需字段完整性")
        tr.assert_equal(True, len(missing) == 0,
                        f"缺失字段: {missing}" if missing else "所有字段存在")
        tr.details = {"required": required_fields, "missing": missing}
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 1.7 时间字段格式验证 (YYYY-MM-DD HH:MM:SS)
        time_pattern_valid = True
        for time_field in ["_created", "_updated"]:
            time_val = data.get(time_field, "")
            try:
                datetime.strptime(time_val, "%Y-%m-%d %H:%M:%S")
            except:
                time_pattern_valid = False
                break
        tr = TestResult("TC01.7 View - 时间字段格式正确")
        tr.assert_true(time_pattern_valid, "时间格式应为 YYYY-MM-DD HH:MM:SS")
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_list_response_format(self):
        """TC02: List接口响应格式完整性测试"""
        print("\n" + "=" * 80)
        print("[TC02] List接口响应格式验证")
        print("=" * 80)

        result = self.test_list()
        response_data = result.get("response_data", {})

        # 2.1 HTTP状态码
        tr = TestResult("TC02.1 List - HTTP状态码=200")
        tr.assert_equal(200, result.get("status_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.2 业务code=200
        tr = TestResult("TC02.2 List - 业务code=200")
        tr.assert_equal(200, response_data.get("code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.3 msg="OK"
        tr = TestResult("TC02.3 List - msg字段='OK'")
        tr.assert_equal("OK", response_data.get("msg"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.4 完整响应结构验证
        validation = ResponseValidator.validate_list_response(response_data)
        tr = TestResult("TC02.4 List - 完整响应结构验证")
        tr.assert_true(validation["valid"],
                       "结构无误" if validation["valid"] else f"错误: {validation['errors']}")
        tr.details = validation
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.5 data.list 是数组
        data = response_data.get("data", {})
        tr = TestResult("TC02.5 List - data.list为数组类型")
        tr.assert_true(isinstance(data.get("list"), list))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.6 paginate字段完整
        paginate = data.get("paginate", {})
        tr = TestResult("TC02.6 List - paginate包含page/page_size/total")
        has_all = all(k in paginate for k in ["page", "page_size", "total"])
        tr.assert_true(has_all, f"paginate: {paginate}")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.7 paginate.page 与请求的page一致
        tr = TestResult("TC02.7 List - paginate.page=1")
        tr.assert_equal(1, paginate.get("page"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.8 paginate.page_size 与请求一致
        tr = TestResult("TC02.8 List - paginate.page_size=10")
        tr.assert_equal(10, paginate.get("page_size"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.9 list数量 <= page_size
        list_data = data.get("list", [])
        tr = TestResult("TC02.9 List - 返回数量不超过page_size")
        tr.assert_true(len(list_data) <= paginate.get("page_size", 10),
                       f"返回{len(list_data)}条, page_size={paginate.get('page_size')}")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 2.10 list中每条记录字段完整
        if list_data:
            required_fields = ["_id", "_created", "_creator", "_updated", "_updater", "wb"]
            all_complete = True
            for item in list_data:
                if not all(f in item for f in required_fields):
                    all_complete = False
                    break
            tr = TestResult("TC02.10 List - 每条记录字段完整")
            tr.assert_true(all_complete)
            self.test_results.append(tr)
            self._print_test_result(tr)

        # 2.11 total >= 返回的list长度
        tr = TestResult("TC02.11 List - total >= list长度")
        tr.assert_true(paginate.get("total", 0) >= len(list_data))
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_data_consistency(self):
        """TC03: 数据一致性测试 - view和list返回同一记录应一致"""
        print("\n" + "=" * 80)
        print("[TC03] 数据一致性测试")
        print("=" * 80)

        # 通过view获取数据
        view_result = self.test_view()
        view_data = view_result.get("response_data", {}).get("data", {})

        # 通过list获取数据
        list_result = self.test_list()
        list_items = list_result.get("response_data", {}).get("data", {}).get("list", [])
        list_item = next((item for item in list_items
                          if item.get("_id") == self.test_record_id), None)

        if view_data and list_item:
            # 3.1 _id一致
            tr = TestResult("TC03.1 view和list的_id一致")
            tr.assert_equal(view_data.get("_id"), list_item.get("_id"))
            self.test_results.append(tr)
            self._print_test_result(tr)

            # 3.2 wb字段一致
            tr = TestResult("TC03.2 view和list的wb字段一致")
            tr.assert_equal(view_data.get("wb"), list_item.get("wb"))
            self.test_results.append(tr)
            self._print_test_result(tr)

            # 3.3 _created一致
            tr = TestResult("TC03.3 view和list的_created一致")
            tr.assert_equal(view_data.get("_created"), list_item.get("_created"))
            self.test_results.append(tr)
            self._print_test_result(tr)

            # 3.4 _creator一致
            tr = TestResult("TC03.4 view和list的_creator一致")
            tr.assert_equal(view_data.get("_creator"), list_item.get("_creator"))
            self.test_results.append(tr)
            self._print_test_result(tr)
        else:
            tr = TestResult("TC03 数据一致性 - 无法获取数据")
            tr.assert_true(False, "view或list返回数据为空")
            self.test_results.append(tr)
            self._print_test_result(tr)

    def test_case_pagination(self):
        """TC04: 分页功能测试"""
        print("\n" + "=" * 80)
        print("[TC04] 分页功能测试")
        print("=" * 80)

        # 4.1 page_size=1
        result = self.test_list(page=1, page_size=1, filters_override=[])
        paginate = result.get("response_data", {}).get("data", {}).get("paginate", {})
        tr = TestResult("TC04.1 page_size=1返回paginate.page_size=1")
        tr.assert_equal(1, paginate.get("page_size"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 4.2 page_size=50
        result = self.test_list(page=1, page_size=50, filters_override=[])
        paginate = result.get("response_data", {}).get("data", {}).get("paginate", {})
        tr = TestResult("TC04.2 page_size=50返回paginate.page_size=50")
        tr.assert_equal(50, paginate.get("page_size"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 4.3 超出范围的page返回空list
        result = self.test_list(page=99999, page_size=10, filters_override=[])
        list_data = result.get("response_data", {}).get("data", {}).get("list", [])
        tr = TestResult("TC04.3 超大page(99999)返回空list")
        tr.assert_equal(0, len(list_data))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 4.4 page=0 边界（按规范应该从1开始）
        result = self.test_list(page=0, page_size=10)
        code = result.get("response_code")
        tr = TestResult("TC04.4 page=0应被拒绝")
        tr.assert_true(code != 200, f"实际code={code}, 建议API校验page>=1")
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_auth_validation(self):
        """TC05: 认证测试"""
        print("\n" + "=" * 80)
        print("[TC05] 认证测试")
        print("=" * 80)

        # 5.1 错误的auth_key
        invalid_auth = self.auth_data.copy()
        invalid_auth["auth_key"] = "invalid_key_xxxxx"
        result = self.test_view(auth_override=invalid_auth)
        tr = TestResult("TC05.1 错误auth_key - 返回code=100414")
        tr.assert_equal(100414, result.get("response_code"))
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 5.2 错误的auth_id
        invalid_auth = self.auth_data.copy()
        invalid_auth["auth_id"] = "nonexistent_user_xyz"
        result = self.test_view(auth_override=invalid_auth)
        tr = TestResult("TC05.2 错误auth_id - 返回鉴权错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 5.3 空auth_key
        invalid_auth = self.auth_data.copy()
        invalid_auth["auth_key"] = ""
        result = self.test_view(auth_override=invalid_auth)
        tr = TestResult("TC05.3 空auth_key - 返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 5.4 错误的project_id
        invalid_auth = self.auth_data.copy()
        invalid_auth["project_id"] = "wrong_project_id"
        result = self.test_view(auth_override=invalid_auth)
        tr = TestResult("TC05.4 错误project_id - 返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_parameter_validation(self):
        """TC06: 参数校验测试"""
        print("\n" + "=" * 80)
        print("[TC06] 参数校验测试")
        print("=" * 80)

        # 6.1 不存在的_id
        result = self.test_view(record_id="9999999999999999999")
        response = result.get("response_data", {})
        data = response.get("data")
        tr = TestResult("TC06.1 不存在的_id - data应为null")
        tr.assert_equal(None, data)
        tr.details = response
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 6.2 空的_id
        result = self.test_view(record_id="")
        tr = TestResult("TC06.2 空_id - 应返回错误")
        tr.assert_true(result.get("response_code") != 200 or
                       result.get("response_data", {}).get("data") is None)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 6.3 超大page_size (疑似BUG)
        result = self.test_list(page=1, page_size=100000)
        tr = TestResult("TC06.3 page_size=100000 - 🐛应有上限校验")
        # 标记这个测试，观察是否有限制
        code = result.get("response_code")
        paginate = result.get("response_data", {}).get("data", {}).get("paginate", {})
        actual_page_size = paginate.get("page_size")
        tr.details = {
            "response_code": code,
            "actual_page_size": actual_page_size,
            "note": "如果code=200且page_size=100000，说明未做上限校验（潜在DOS风险）"
        }
        tr.assert_true(code != 200 or actual_page_size < 1000,
                       f"code={code}, page_size={actual_page_size}")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 6.4 负数page
        result = self.test_list(page=-1)
        tr = TestResult("TC06.4 负数page - 应返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 6.5 负数page_size
        result = self.test_list(page=1, page_size=-10)
        tr = TestResult("TC06.5 负数page_size - 应返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_filter_expressions(self):
        """TC07: 过滤表达式测试"""
        print("\n" + "=" * 80)
        print("[TC07] 过滤表达式测试")
        print("=" * 80)

        # 7.1 等于查询 (expression=1)
        filters = [{"field_name": "wb", "expression": 1, "value": "zs002"}]
        result = self.test_list(filters_override=filters)
        list_data = result.get("response_data", {}).get("data", {}).get("list", [])
        tr = TestResult("TC07.1 等于查询 wb='zs002'")
        all_match = all(item.get("wb") == "zs002" for item in list_data) if list_data else True
        tr.assert_true(result.get("response_code") == 200 and all_match,
                       f"返回{len(list_data)}条记录")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.2 等于查询-无匹配
        filters = [{"field_name": "wb", "expression": 1, "value": "nonexistent_value_xxx"}]
        result = self.test_list(filters_override=filters)
        list_data = result.get("response_data", {}).get("data", {}).get("list", [])
        tr = TestResult("TC07.2 等于查询-无匹配应返回空list")
        tr.assert_equal(0, len(list_data))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.3 包含查询 (expression=9)
        filters = [{"field_name": "wb", "expression": 9, "value": "zs"}]
        result = self.test_list(filters_override=filters)
        tr = TestResult("TC07.3 包含查询 wb contains 'zs'")
        tr.assert_equal(200, result.get("response_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.4 范围查询 (expression=15)
        filters = [{
            "field_name": "_created",
            "expression": 15,
            "value": ["2020-01-01 00:00:00", "2030-12-31 23:59:59"]
        }]
        result = self.test_list(filters_override=filters)
        tr = TestResult("TC07.4 范围查询 _created")
        tr.assert_equal(200, result.get("response_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.5 空过滤器
        result = self.test_list(filters_override=[])
        tr = TestResult("TC07.5 空过滤器-返回所有数据")
        tr.assert_equal(200, result.get("response_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.6 非法expression
        filters = [{"field_name": "wb", "expression": 999, "value": "zs"}]
        result = self.test_list(filters_override=filters)
        tr = TestResult("TC07.6 非法expression=999 - 应返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.7 不存在的field_name
        filters = [{"field_name": "nonexistent_field", "expression": 1, "value": "test"}]
        result = self.test_list(filters_override=filters)
        tr = TestResult("TC07.7 不存在的field_name - 应返回错误")
        tr.assert_true(result.get("response_code") != 200)
        tr.details = result.get("response_data")
        self.test_results.append(tr)
        self._print_test_result(tr)

        # 7.8 多条件组合查询
        filters = [
            {"field_name": "wb", "expression": 9, "value": "zs"},
            {"field_name": "_creator", "expression": 1, "value": "zhangshun"}
        ]
        result = self.test_list(filters_override=filters)
        tr = TestResult("TC07.8 多条件组合(AND)查询")
        tr.assert_equal(200, result.get("response_code"))
        self.test_results.append(tr)
        self._print_test_result(tr)

    def test_case_response_time(self):
        """TC08: 响应时间性能测试"""
        print("\n" + "=" * 80)
        print("[TC08] 响应时间性能测试")
        print("=" * 80)

        # View API响应时间
        view_times = []
        for _ in range(10):
            result = self.test_view()
            if result.get("success"):
                view_times.append(result.get("response_time", 0))

        if view_times:
            avg = sum(view_times) / len(view_times)
            max_t = max(view_times)
            p95 = sorted(view_times)[int(len(view_times) * 0.95) - 1]

            tr = TestResult("TC08.1 View API 平均响应时间 < 500ms")
            tr.assert_true(avg < 0.5, f"avg={avg * 1000:.1f}ms, max={max_t * 1000:.1f}ms, p95={p95 * 1000:.1f}ms")
            tr.details = {"avg_ms": f"{avg * 1000:.1f}", "max_ms": f"{max_t * 1000:.1f}", "p95_ms": f"{p95 * 1000:.1f}"}
            self.test_results.append(tr)
            self._print_test_result(tr)

        # List API响应时间
        list_times = []
        for _ in range(10):
            result = self.test_list()
            if result.get("success"):
                list_times.append(result.get("response_time", 0))

        if list_times:
            avg = sum(list_times) / len(list_times)
            max_t = max(list_times)
            p95 = sorted(list_times)[int(len(list_times) * 0.95) - 1]

            tr = TestResult("TC08.2 List API 平均响应时间 < 500ms")
            tr.assert_true(avg < 0.5, f"avg={avg * 1000:.1f}ms, max={max_t * 1000:.1f}ms, p95={p95 * 1000:.1f}ms")
            tr.details = {"avg_ms": f"{avg * 1000:.1f}", "max_ms": f"{max_t * 1000:.1f}", "p95_ms": f"{p95 * 1000:.1f}"}
            self.test_results.append(tr)
            self._print_test_result(tr)

    def test_case_qps_limit(self):
        """TC09: QPS限制测试"""
        print("\n" + "=" * 80)
        print("[TC09] QPS限制测试 (目标QPS=100)")
        print("=" * 80)

        num_requests = 50  # 避免消耗过多配额
        start_time = time.time()
        results = []

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(self.test_view, None, None, False)
                       for _ in range(num_requests)]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append({"success": False, "error": str(e)})

        total_time = time.time() - start_time
        actual_qps = num_requests / total_time if total_time > 0 else 0
        successful = sum(1 for r in results if r.get("response_code") == 200)

        tr = TestResult(f"TC09.1 QPS压测({num_requests}并发请求)")
        tr.assert_true(successful > num_requests * 0.8,  # 80%以上成功
                       f"QPS={actual_qps:.1f}, 成功{successful}/{num_requests}")
        tr.details = {
            "total_requests": num_requests,
            "successful": successful,
            "actual_qps": f"{actual_qps:.2f}",
            "total_time": f"{total_time:.2f}s"
        }
        self.test_results.append(tr)
        self._print_test_result(tr)

    def _print_test_result(self, tr: TestResult):
        """打印单个测试结果"""
        status = "✓ PASS" if tr.passed else "✗ FAIL"
        color_status = f"\033[92m{status}\033[0m" if tr.passed else f"\033[91m{status}\033[0m"
        print(f"  {color_status} | {tr.test_name}")
        if tr.message:
            print(f"         └─ {tr.message}")
        if not tr.passed:
            print(f"         └─ 预期: {tr.expected}")
            print(f"         └─ 实际: {tr.actual}")

    def generate_report(self):
        """生成最终测试报告"""
        print("\n" + "=" * 80)
        print("测试总结报告")
        print("=" * 80)

        total = len(self.test_results)
        passed = sum(1 for t in self.test_results if t.passed)
        failed = total - passed
        pass_rate = (passed / total * 100) if total > 0 else 0

        print(f"测试时间: {datetime.now().isoformat()}")
        print(f"总测试数: {total}")
        print(f"通过数: {passed} ✓")
        print(f"失败数: {failed} ✗")
        print(f"通过率: {pass_rate:.1f}%")
        print(f"\nAPI请求统计:")
        print(f"  /api/view: {self.request_count['/api/view']} 次")
        print(f"  /api/list: {self.request_count['/api/list']} 次")
        print(f"  总计: {sum(self.request_count.values())} 次")

        # 按模块统计
        modules = {}
        for tr in self.test_results:
            module = tr.test_name.split(" ")[0] if " " in tr.test_name else "OTHER"
            module_key = module.split(".")[0]  # TC01.1 -> TC01
            if module_key not in modules:
                modules[module_key] = {"total": 0, "passed": 0}
            modules[module_key]["total"] += 1
            if tr.passed:
                modules[module_key]["passed"] += 1

        print(f"\n📊 按测试模块统计:")
        for module, stats in sorted(modules.items()):
            rate = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
            status = "✓" if stats["passed"] == stats["total"] else "⚠"
            print(f"  {status} {module}: {stats['passed']}/{stats['total']} ({rate:.0f}%)")

        # 失败的测试列表
        if failed > 0:
            print(f"\n❌ 失败的测试用例详情:")
            for tr in self.test_results:
                if not tr.passed:
                    print(f"\n  • {tr.test_name}")
                    print(f"    预期: {tr.expected}")
                    print(f"    实际: {tr.actual}")
                    if tr.message:
                        print(f"    说明: {tr.message}")

        print("\n" + "=" * 80)

        # 保存JSON报告
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": f"{pass_rate:.1f}%"
            },
            "api_requests": self.request_count,
            "module_stats": modules,
            "test_cases": [tr.to_dict() for tr in self.test_results]
        }

        with open("test_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"✓ 详细JSON报告: test_report.json")

        # 生成HTML报告
        self._generate_html_report(report)
        print(f"✓ HTML报告: test_report.html\n")

        return report

    def _generate_html_report(self, report: Dict):
        """生成HTML测试报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>API测试报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .card {{ flex: 1; padding: 20px; border-radius: 8px; text-align: center; }}
        .card.total {{ background: #e3f2fd; }}
        .card.passed {{ background: #c8e6c9; }}
        .card.failed {{ background: #ffcdd2; }}
        .card.rate {{ background: #fff3e0; }}
        .card h2 {{ margin: 0; font-size: 36px; }}
        .card p {{ margin: 5px 0 0 0; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        tr:hover {{ background: #f9f9f9; }}
        .pass {{ color: #4CAF50; font-weight: bold; }}
        .fail {{ color: #f44336; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🧪 API测试报告</h1>
        <p>生成时间: {report['timestamp']}</p>

        <div class="summary">
            <div class="card total"><h2>{report['summary']['total']}</h2><p>总测试数</p></div>
            <div class="card passed"><h2>{report['summary']['passed']}</h2><p>通过</p></div>
            <div class="card failed"><h2>{report['summary']['failed']}</h2><p>失败</p></div>
            <div class="card rate"><h2>{report['summary']['pass_rate']}</h2><p>通过率</p></div>
        </div>

        <h2>📋 测试用例详情</h2>
        <table>
            <thead>
                <tr>
                    <th>测试用例</th>
                    <th>状态</th>
                    <th>预期</th>
                    <th>实际</th>
                    <th>说明</th>
                </tr>
            </thead>
            <tbody>
"""
        for tc in report['test_cases']:
            status_class = "pass" if tc['passed'] else "fail"
            status_text = "✓ PASS" if tc['passed'] else "✗ FAIL"
            html += f"""
                <tr>
                    <td>{tc['test_name']}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{tc['expected']}</td>
                    <td>{tc['actual']}</td>
                    <td>{tc['message']}</td>
                </tr>"""

        html += """
            </tbody>
        </table>
    </div>
</body>
</html>"""

        with open("test_report.html", "w", encoding="utf-8") as f:
            f.write(html)


def main():
    """主测试流程"""
    print("\n" + "=" * 80)
    print("🧪 API 服务限制 & 响应格式测试套件 v3.0")
    print("=" * 80)
    print("API限制: 最大请求数=100, 请求间隔=10s, QPS=100")
    print("=" * 80)

    tester = APITester()

    try:
        # 核心响应格式测试
        tester.test_case_view_response_format()
        tester.test_case_list_response_format()
        tester.test_case_data_consistency()

        # 功能测试
        tester.test_case_pagination()
        tester.test_case_auth_validation()
        tester.test_case_parameter_validation()
        tester.test_case_filter_expressions()

        # 性能 & 限制测试
        tester.test_case_response_time()
        tester.test_case_qps_limit()

    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")
    except Exception as e:
        logger.error(f"测试执行出错: {e}", exc_info=True)
    finally:
        tester.generate_report()


if __name__ == "__main__":
    main()