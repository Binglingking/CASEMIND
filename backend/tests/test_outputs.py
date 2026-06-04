from fastapi.testclient import TestClient

from backend.agents.query_agent import QueryAgent
from backend.api.routes import router
from backend.core.llm import LLMConfig
from backend.core.project import project_manager
from backend.services import output_service


PROJECT = "outputs_proj"


def _seed_outputs():
    project_manager.create(PROJECT)
    tc = project_manager.out_testcase_dir(PROJECT) / "testcase_seed.md"
    xm = project_manager.out_xmind_dir(PROJECT) / "xmind_seed.md"
    req_pdf = project_manager.out_req_analysis_dir(PROJECT) / "req_analysis_seed.pdf"
    req_json = project_manager.out_req_analysis_dir(PROJECT) / "req_analysis_seed.json"
    tc.write_text("# cases\n", encoding="utf-8")
    xm.write_text("# map\n", encoding="utf-8")
    req_pdf.write_bytes(b"%PDF-1.4\nseed\n")
    req_json.write_text('{"summary":"sidecar"}', encoding="utf-8")
    return tc, xm, req_pdf, req_json


def test_output_service_supports_req_analysis(tmp_settings):
    _seed_outputs()

    items = output_service.list_outputs(PROJECT)
    names = {(it["kind"], it["name"]) for it in items}
    assert ("testcase", "testcase_seed.md") in names
    assert ("xmind", "xmind_seed.md") in names
    assert ("req_analysis", "req_analysis_seed.pdf") in names
    assert ("req_analysis", "req_analysis_seed.json") not in names

    meta = output_service.read_output_content(PROJECT, "req_analysis", "req_analysis_seed.pdf")
    assert meta["kind"] == "req_analysis"
    assert meta["content_type"] == "application/pdf"

    output_service.rename_output(PROJECT, "req_analysis", "req_analysis_seed.pdf", "renamed.pdf")
    assert (project_manager.out_req_analysis_dir(PROJECT) / "renamed.pdf").exists()

    output_service.delete_output(PROJECT, "req_analysis", "renamed.pdf")
    assert not (project_manager.out_req_analysis_dir(PROJECT) / "renamed.pdf").exists()


def test_output_service_rejects_invalid_kind(tmp_settings):
    project_manager.create(PROJECT)
    try:
        output_service.read_output_content(PROJECT, "bad", "x")
    except ValueError as exc:
        assert "kind must be" in str(exc)
    else:
        raise AssertionError("invalid kind should fail")


def test_outputs_download_route(tmp_settings):
    _seed_outputs()
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/outputs/download", params={
        "project": PROJECT, "kind": "xmind", "filename": "xmind_seed.md",
    })
    assert r.status_code == 200
    assert r.text.strip() == "# map"

    r = client.get("/api/outputs/download", params={
        "project": PROJECT, "kind": "req_analysis", "filename": "req_analysis_seed.pdf",
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")

    r = client.get("/api/outputs/download", params={
        "project": PROJECT, "kind": "req_analysis", "filename": "missing.pdf",
    })
    assert r.status_code == 404


def test_req_analysis_query_persists_pdf(tmp_settings, monkeypatch):
    project_manager.create(PROJECT)

    def fake_chat(*args, **kwargs):
        return '{"summary":"ok","statistics":{"total":0},"issues":[]}'

    monkeypatch.setattr("backend.agents.query_agent.chat", fake_chat)
    monkeypatch.setattr(
        "backend.services.req_analysis_service.generate_pdf_report",
        lambda project, data: b"%PDF-1.4\nreq\n",
    )

    result = QueryAgent(PROJECT).run(
        question="登录需求",
        mode="req_analysis",
        llm_cfg=LLMConfig("", "", ""),
    )

    assert result["mode"] == "req_analysis"
    assert result["pdf_filename"].endswith(".pdf")
    assert (project_manager.out_req_analysis_dir(PROJECT) / result["pdf_filename"]).exists()
    assert output_service.list_outputs(PROJECT, "req_analysis")[0]["name"] == result["pdf_filename"]
