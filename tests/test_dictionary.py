"""Tests for the user dictionary."""


import pytest

from wispr_dragon.correction.dictionary import UserDictionary


@pytest.fixture
def tmp_dict(tmp_path):
    path = tmp_path / "test_dict.json"
    return UserDictionary(path=path)


def test_add_correction(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    assert tmp_dict.get_correction("john ball win") == "John Baldwin"


def test_correction_frequency(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_correction("john ball win", "John Baldwin")
    high = tmp_dict.get_high_confidence_corrections(threshold=3)
    assert "john ball win" in high
    assert high["john ball win"] == "John Baldwin"


def test_remove_correction(tmp_dict):
    tmp_dict.add_correction("test", "Test")
    assert tmp_dict.remove_correction("test")
    assert tmp_dict.get_correction("test") is None


def test_custom_words(tmp_dict):
    tmp_dict.add_custom_word("ROCm")
    tmp_dict.add_custom_word("Wispr-Dragon")
    assert "ROCm" in tmp_dict.custom_words
    assert "Wispr-Dragon" in tmp_dict.custom_words


def test_hotwords(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_custom_word("ROCm")
    hotwords = tmp_dict.build_hotwords()
    assert "John Baldwin" in hotwords
    assert "ROCm" in hotwords


def test_initial_prompt(tmp_dict):
    tmp_dict.add_custom_word("Jonathan")
    tmp_dict.add_custom_word("Baldwin")
    prompt = tmp_dict.build_initial_prompt()
    assert "Jonathan" in prompt
    assert "Baldwin" in prompt


def test_persistence(tmp_path):
    path = tmp_path / "persist.json"
    d1 = UserDictionary(path=path)
    d1.add_correction("wrong", "Right")
    d1.add_custom_word("TestWord")

    d2 = UserDictionary(path=path)
    assert d2.get_correction("wrong") == "Right"
    assert "TestWord" in d2.custom_words


def test_phrase_replacement(tmp_dict):
    tmp_dict.add_phrase_replacement("per say", "per se")
    assert tmp_dict.phrase_replacements["per say"] == "per se"


def test_add_correction_count_bumps_frequency_once(tmp_dict):
    tmp_dict.add_correction("teh", "the", count=3)
    assert tmp_dict.corrections["teh"]["frequency"] == 3


def test_corrupt_dictionary_is_backed_up_not_fatal(tmp_path):
    path = tmp_path / "d.json"
    path.write_text("{ not json")
    d = UserDictionary(path=path)
    assert d.corrections == {}
    assert list(tmp_path.glob("d.json.corrupt*")), "bad file should be kept aside"


def test_save_is_atomic_and_round_trips(tmp_path):
    path = tmp_path / "d.json"
    d = UserDictionary(path=path)
    d.add_correction("teh", "the")
    assert UserDictionary(path=path).get_correction("teh") == "the"
    assert not list(tmp_path.glob("*.tmp")), "temp file must be renamed into place"


def test_initial_prompt_prefers_newest_words(tmp_path):
    d = UserDictionary(path=tmp_path / "d.json")
    for i in range(60):
        d.add_custom_word(f"Word{i}")
    prompt = d.build_initial_prompt()
    assert "Word59" in prompt


@pytest.mark.skipif(not hasattr(__import__("os"), "geteuid") or __import__("os").geteuid() == 0,
                    reason="needs a non-root POSIX user for permission errors")
def test_unreadable_dictionary_is_an_error_not_corruption(tmp_path):
    path = tmp_path / "d.json"
    UserDictionary(path=path).add_correction("teh", "the")
    path.chmod(0)
    try:
        with pytest.raises(PermissionError):
            UserDictionary(path=path)
        assert not list(tmp_path.glob("d.json.corrupt*"))
    finally:
        path.chmod(0o600)
