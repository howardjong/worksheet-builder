"""Dosage derivations from profile facts (spec 2026-07-10)."""

from datetime import date

import pytest

from companion.dosage import (
    age_years,
    current_grade,
    derived_grade,
    grade_with_source,
    segment_minutes,
    session_minutes,
    severity,
)
from companion.schema import LearnerProfile

IAN_BD = date(2019, 9, 21)
JULY = date(2026, 7, 10)


class _FrozenDate(date):
    """date subclass whose today() is pinned, so arithmetic still works."""

    @classmethod
    def today(cls) -> "_FrozenDate":
        return cls(2026, 7, 10)


def _profile(**overrides) -> LearnerProfile:
    data = {"name": "Ian", "grade_level": "2"}
    data.update(overrides)
    return LearnerProfile.model_validate(data)


def test_age_years_ian_in_july_2026() -> None:
    assert age_years(IAN_BD, JULY) == pytest.approx(6.80, abs=0.02)


def test_derived_grade_rolls_july_first() -> None:
    assert derived_grade(IAN_BD, "CA-ON", JULY) == "2"  # summer -> incoming grade
    assert derived_grade(IAN_BD, "CA-ON", date(2026, 6, 30)) == "1"  # still last school year
    assert derived_grade(IAN_BD, "CA-ON", date(2027, 6, 30)) == "2"  # holds through June
    assert derived_grade(IAN_BD, "CA-ON", date(2027, 7, 1)) == "3"


def test_derived_grade_dec31_cutoff_and_clamps() -> None:
    # Dec-2019-born child is the same cohort as Ian (cutoff Dec 31).
    assert derived_grade(date(2019, 12, 30), "CA-ON", JULY) == "2"
    # Too young / too old clamp to product range.
    assert derived_grade(date(2022, 5, 1), "CA-ON", JULY) == "K"
    assert derived_grade(date(2014, 5, 1), "CA-ON", JULY) == "3"


def test_unsupported_jurisdiction_returns_none() -> None:
    assert derived_grade(IAN_BD, "US-NY", JULY) is None


def test_grade_source_and_stale_profile_fallbacks() -> None:
    derived = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", grade_level="1")
    assert grade_with_source(derived, JULY) == ("2", "derived")  # derived wins over stale '1'
    legacy = _profile(grade_level="1")
    assert grade_with_source(legacy, JULY) == ("1", "profile")
    unsupported = _profile(birthdate=IAN_BD, jurisdiction="US-NY", grade_level="1")
    assert grade_with_source(unsupported, JULY) == ("1", "profile")
    assert current_grade(derived, JULY) == "2"


def test_severity_default_and_explicit() -> None:
    assert severity(_profile()) == "moderate"
    assert severity(_profile(adhd_severity="severe")) == "severe"


def test_segment_minutes_worked_example_and_clamps() -> None:
    ian = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate")
    assert segment_minutes(ian, JULY) == 7  # 6.80 * 1.5 * 0.70 = 7.14 -> 7
    assert segment_minutes(_profile(), JULY) is None  # no birthdate -> table fallback
    mild_teenish = _profile(birthdate=date(2013, 1, 1), adhd_severity="mild")
    assert segment_minutes(mild_teenish, JULY) == 12  # 13.5*1.5*0.85=17.2 -> clamp 12
    severe_toddler = _profile(birthdate=date(2023, 1, 1), adhd_severity="severe")
    assert segment_minutes(severe_toddler, JULY) == 4  # 3.5*1.5*0.55=2.9 -> clamp 4


def test_session_minutes_norm_and_clamps() -> None:
    ian = _profile(birthdate=IAN_BD, jurisdiction="CA-ON")
    assert session_minutes(ian, JULY) == 20  # 10 * grade 2
    assert session_minutes(_profile(), JULY) is None  # no jurisdiction -> table
    k_kid = _profile(birthdate=date(2021, 3, 1), jurisdiction="CA-ON")
    assert session_minutes(k_kid, JULY) == 12  # K -> clamp floor 12
    g1 = _profile(jurisdiction="CA-ON", grade_level="1")  # no birthdate: profile grade
    assert session_minutes(g1, JULY) == 12  # 10 -> clamp 12


def test_profile_yaml_roundtrip_with_new_fields(tmp_path) -> None:
    from companion.schema import load_profile, save_profile

    p = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate")
    path = tmp_path / "p.yaml"
    save_profile(p, path)
    loaded = load_profile(path)
    assert loaded.birthdate == IAN_BD
    assert loaded.jurisdiction == "CA-ON"
    assert loaded.adhd_severity == "moderate"


def test_invalid_severity_rejected() -> None:
    with pytest.raises(ValueError):
        _profile(adhd_severity="extreme")


def test_birthdate_never_enters_planner_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_planner import _build_planner_prompt
    from adapt.rules import build_rules
    from skill.schema import LiteracySkillModel, SourceItem

    monkeypatch.setattr("companion.dosage.date", _FrozenDate)
    profile = _profile(
        birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate", grade_level="1"
    )
    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="sentence", content="The cat sat.", source_region_index=0)
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )
    prompt = _build_planner_prompt(skill, profile, build_rules(profile), "default", None)

    assert "2019" not in prompt
    assert "birthdate" not in prompt.lower()
    assert "Grade: 2" in prompt  # derived grade (July -> incoming grade 2), not stale '1'


def test_rules_use_current_grade(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.rules import build_rules

    monkeypatch.setattr("companion.dosage.date", _FrozenDate)
    stale = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", grade_level="1")
    plain_grade2 = _profile(grade_level="2")

    assert build_rules(stale) == build_rules(plain_grade2)


def test_design_spec_uses_current_grade(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.schema import ActivityChunk, AdaptedActivityModel, Example, ScaffoldConfig, Step
    from render.design_spec import compile_worksheet_design_spec
    from theme.schema import ThemeConfig

    monkeypatch.setattr("companion.dosage.date", _FrozenDate)
    stale = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", grade_level="1")
    adapted = AdaptedActivityModel(
        source_hash="source_hash",
        skill_model_hash="skill_hash",
        learner_profile_hash="profile_hash",
        grade_level="1",
        domain="phonics",
        specific_skill="vowel teams ai ay",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Read vowel team words",
                instructions=[Step(number=1, text="Read each word.")],
                worked_example=Example(instruction="Try this first:", content="rain has ai"),
                items=[],
                response_format="write",
                time_estimate="About 3 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="geometry_dash",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_title="Vowel Team Adventure",
        worksheet_number=1,
        worksheet_count=2,
    )
    theme = ThemeConfig(name="Geometry Dash Calm")

    spec = compile_worksheet_design_spec(adapted, theme, stale, render_mode="image_gen")

    assert spec.learner_grade_level == "2"
