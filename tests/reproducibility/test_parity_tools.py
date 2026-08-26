from __future__ import annotations

import pytest

from tools.parity.collect_corpus import batch_ranges


def test_decision_corpus_collection_is_bounded_by_batch_size() -> None:
    ranges = list(batch_ranges(20_003, 1_000))

    assert ranges[0] == (0, 1_000)
    assert ranges[-1] == (20_000, 3)
    assert sum(count for _, count in ranges) == 20_003
    assert max(count for _, count in ranges) == 1_000


@pytest.mark.parametrize("runs,batch_size", [(0, 1_000), (1_000, 0)])
def test_decision_corpus_collection_rejects_non_positive_ranges(
    runs: int, batch_size: int
) -> None:
    with pytest.raises(ValueError, match="positive"):
        list(batch_ranges(runs, batch_size))
