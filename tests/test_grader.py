from app.catalog import get_question, load_catalog
from app.grader import grade_answer


def test_normalisation_francaise_ignore_accents_et_typographie():
    from app.grader import normalize_text

    assert normalize_text("Les villosités de l’intestin grêle !") == "les villosites de l intestin grele"


def test_reponse_complete_digestion():
    question = get_question("c4-digestion-absorption")
    assert question is not None
    result = grade_answer(question, "Les nutriments passent dans le sang au niveau des villosités de l'intestin grêle.")
    assert result["complete"] is True
    assert result["level"] == 4
    assert result["coverage"] == 1.0


def test_reponse_partielle_identifie_le_manque():
    question = get_question("c4-digestion-absorption")
    assert question is not None
    result = grade_answer(question, "Les nutriments passent dans l'estomac.")
    labels = {item["label"] for item in result["missing_criteria"]}
    assert "Les villosités sont nommées" in labels
    assert result["complete"] is False


def test_misconception_photosynthese_prioritaire():
    question = get_question("c4-nutrition-plante-echanges")
    assert question is not None
    result = grade_answer(
        question,
        "La photosynthèse libère du CO2 et consomme du dioxygène comme la respiration.",
    )
    assert result["contradictory"] is True
    assert result["misconceptions"][0]["id"] == "photosynthese-respiration"
    assert result["level"] == 0


def test_phrase_négative_et_contradiction_ordonnée_ne_provoquent_pas_de_faux_positif():
    from app.catalog import get_question
    from app.grader import grade_answer

    question = get_question("c4-vent-direction")
    assert question is not None
    result = grade_answer(question, "Le vent ne vient pas du nord, mais il vient des hautes pressions vers les basses.")
    assert result["misconceptions"] == []


def test_phrase_negativée_ne_compte_pas():
    question = get_question("c4-vent-direction")
    assert question is not None
    result = grade_answer(question, "Le vent ne souffle pas des hautes pressions vers les basses pressions.")
    assert result["matched_criteria"] == []


def test_longue_reponse_demande_relecture():
    question = get_question("c4-vent-direction")
    assert question is not None
    result = grade_answer(question, "Je ne sais pas. C’est peut-être le nord. MonCopains dise autre chose. Le professeur a expliqué.")
    assert result["statistics"]["too_long"] is True
    assert len(result["remediation"]["steps"]) >= 3


def test_banque_wooflash_couvre_39_ebooks():
    questions = [question for question in load_catalog() if question.get("origin") == "wooflashquizz"]
    assert len(questions) == 78
    quiz_ids = {question["source"]["locator"].split()[1].rstrip(",") for question in questions}
    assert len(quiz_ids) == 39
    assert {question["level"] for question in questions} == {"Cycle 3", "Cycle 4"}


def test_questions_historiques_ont_le_bon_cycle():
    expected = {
        "c4-digestion-absorption": "5e",
        "c4-digestion-enzymes": "5e",
        "c4-vent-direction": "4e",
    }
    for question_id, school_level in expected.items():
        question = get_question(question_id)
        assert question is not None
        assert question["level"] == "Cycle 4"
        assert question["school_level"] == school_level


def test_banque_cycle3_et_cycle4():
    questions = load_catalog()
    assert len(questions) == 87
    assert {question["level"] for question in questions} == {"Cycle 3", "Cycle 4"}
    assert {question["school_level"] for question in questions} == {"3e", "4e", "5e", "6e"}
    assert len({question["id"] for question in questions}) == len(questions)
    for question in questions:
        assert question["source"]["file"]
        assert question["remediation"]["retry_prompt"]
