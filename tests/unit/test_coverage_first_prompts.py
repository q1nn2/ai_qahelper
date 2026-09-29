from __future__ import annotations

from ai_qahelper.models import LlmConfig, RequirementItem, UnifiedRequirementModel
from ai_qahelper.testdocs import generate_checklist, generate_test_cases


class CapturingLlm:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, schema, root_list_key: str | None = None):  # noqa: ANN001
        self.prompts.append(system + "\n" + user)
        return schema(**{root_list_key: []})


def test_test_case_prompt_is_coverage_first_without_fixed_count() -> None:
    llm = CapturingLlm()
    model = UnifiedRequirementModel(
        requirements=[RequirementItem(source="req.md", content="Login")],
        target_url="https://example.com",
    )

    generate_test_cases(llm, model, max_cases=30, llm_cfg=LlmConfig())

    prompt = "\n".join(llm.prompts)
    assert "Сгенерируй ровно" not in prompt
    assert "не меньше и не больше" not in prompt
    assert "Количество: 30" not in prompt
    assert "сколько необходимо для полного покрытия" in prompt


def test_checklist_prompt_is_coverage_first_without_fixed_count() -> None:
    llm = CapturingLlm()
    model = UnifiedRequirementModel(
        requirements=[RequirementItem(source="req.md", content="Login")],
        target_url="https://example.com",
    )

    generate_checklist(llm, model, max_items=30, llm_cfg=LlmConfig())

    prompt = "\n".join(llm.prompts)
    assert "Сгенерируй ровно" not in prompt
    assert "не меньше и не больше" not in prompt
    assert "сколько необходимо для полного покрытия" in prompt
