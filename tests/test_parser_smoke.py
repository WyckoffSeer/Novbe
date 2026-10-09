import pytest

from novbe import llm
from novbe.data import demo_rules, load_problem
from novbe.parser import _Out, assemble, parse, resolve_person, split_sentences


@pytest.fixture(scope="module")
def problem():
    return load_problem()


@pytest.mark.parametrize("mention,expected", [
    ("Aysel", "s01"), ("Aysel'in", "s01"), ("Лейла", "s03"), ("Лейлы", "s03"),
    ("Elnura", "s02"), ("Rasad", "s06"), ("Рашад", "s06"), ("Gunel", "s07"),
    ("Гюнель", "s07"), ("Fərid", "s12"), ("Ferid", "s12"), ("Orxan", "s10"), ("Орхан", "s10"),
    ("hamı", None), ("Bob", None), ("all", "all"),
])
def test_resolve_person(problem, mention, expected):
    assert resolve_person(mention, problem) == expected


def test_split_sentences():
    assert split_sentences("A b c. D e f!\n\n- G h\n") == ["A b c.", "D e f!", "G h"]


def test_assemble_never_drops_a_sentence(problem):
    sentences = ["Aysel cümə günləri işləyə bilməz.", "Bob gecə işləməz.", "Nigar gecə növbələrini sevmir.", "Missing one."]
    out = _Out.model_validate({"items": [
        {"index": 1, "kind": "constraint", "constraints": [{"type": "unavailable", "person": "Aysel", "weekdays": [4]}]},
        {"index": 2, "kind": "constraint", "constraints": [{"type": "unavailable", "person": "Bob", "weekdays": None, "shift": "night"}]},
        {"index": 3, "kind": "ambiguous", "question": "Hard rule or preference?"},
    ]})
    res = assemble(sentences, out, problem)
    assert [c.person for c in res.constraints] == ["s01"]
    assert res.constraints[0].source_text == sentences[0]
    assert [a.source_text for a in res.ambiguous] == [sentences[1], sentences[2]]  # unknown name -> ambiguous
    assert [u.source_text for u in res.unsupported] == [sentences[3]]  # missing -> unsupported, not dropped
    assert len(res.constraints) + len(res.ambiguous) + len(res.unsupported) == len(sentences)


@pytest.mark.skipif(not llm.available(), reason="needs ANTHROPIC_API_KEY")
def test_demo_rules_parse_live(problem):
    res, _ = parse(demo_rules(), problem)
    types = sorted(c.type for c in res.constraints)
    assert types == sorted(["unavailable", "min_role", "max_consecutive_days", "unavailable", "unavailable", "min_rest_hours"])
    assert len(res.ambiguous) == 1 and "Nigar" in res.ambiguous[0].source_text
    by_person = {c.person: c for c in res.constraints if c.type == "unavailable"}
    assert by_person["s01"].weekdays == [4]
    assert by_person["s02"].weekdays == [2] and by_person["s02"].shift == "morning"
    assert by_person["s03"].weekdays == [5]
