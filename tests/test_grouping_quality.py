"""Code's headline grouping, scored on a hand-labelled day (pipeline/evaluate_grouping.py)."""
import evaluate_grouping as ev


def test_grouping_stays_precise_on_the_labelled_day():
    arts, labels = ev.load()
    result, _ = ev.run(arts, labels)
    # Measured when the thresholds were tuned: precision 0.977, recall 0.58. A change that mixes
    # unrelated events (precision) or splits much more (recall) fails here.
    assert result["precision"] >= 0.95, result
    assert result["recall"] >= 0.5, result
