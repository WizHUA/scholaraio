from __future__ import annotations

import pandas as pd

from scholaraio.topics import get_outliers, get_topic_overview, get_topic_papers


class _FakeTopicModel:
    def __init__(self):
        self._topics = [0, 1, 0, -1]
        self._metas = [
            {
                "paper_id": "p1",
                "title": "Wave propagation in porous media",
                "authors": "Alice Zheng",
                "year": 2024,
                "journal": "JFM",
                "citation_count": {"openalex": 12},
            },
            {
                "paper_id": "p2",
                "title": "Shock response of cellular materials",
                "authors": "Bo Li",
                "year": 2023,
                "journal": "PoF",
                "citation_count": {"openalex": 8},
            },
            {
                "paper_id": "p3",
                "title": "Granular damping in porous waves",
                "authors": "Chen Wang",
                "year": 2022,
                "journal": "JFM",
                "citation_count": {"openalex": 20},
            },
            {
                "paper_id": "p4",
                "title": "Unclustered note",
                "authors": "Dana Xu",
                "year": 2021,
                "journal": "",
                "citation_count": {},
            },
        ]

    def get_topic_info(self):
        return pd.DataFrame(
            [
                {"Topic": 0, "Count": 2, "Name": "Topic 0"},
                {"Topic": 1, "Count": 1, "Name": "Topic 1"},
                {"Topic": -1, "Count": 1, "Name": "Outliers"},
            ]
        )

    def get_topic(self, topic_id: int):
        mapping = {
            0: [("granular", 0.9), ("porous", 0.8), ("waves", 0.7)],
            1: [("shock", 0.9), ("cellular", 0.8), ("impact", 0.7)],
        }
        return mapping.get(topic_id, [])


def test_get_topic_overview_sorts_topics_and_representative_papers_by_count_and_citations():
    model = _FakeTopicModel()

    overview = get_topic_overview(model)

    assert [item["topic_id"] for item in overview] == [0, 1]
    assert overview[0]["count"] == 2
    assert overview[0]["keywords"][:3] == ["granular", "porous", "waves"]
    assert [paper["paper_id"] for paper in overview[0]["representative_papers"]] == ["p3", "p1"]


def test_get_topic_papers_and_outliers_return_expected_rows():
    model = _FakeTopicModel()

    topic_zero = get_topic_papers(model, 0)
    outliers = get_outliers(model)

    assert [paper["paper_id"] for paper in topic_zero] == ["p3", "p1"]
    assert [paper["paper_id"] for paper in outliers] == ["p4"]
