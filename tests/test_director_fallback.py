from backend.director_script import DirectorScriptGenerator


def test_fallback_script_remains_usable_for_pipeline():
    result = DirectorScriptGenerator()._fallback_script("trendy", "JSON parse failed")
    assert result["success"] is False
    assert result["script"]["scenes"]
    assert result["script"]["scenes"][0]["voiceover_text"]
