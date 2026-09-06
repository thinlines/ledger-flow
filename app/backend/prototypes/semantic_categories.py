"""Pure ranking logic for the semantic-category prototype.

Question: can embedding similarity to previously categorized transactions make
useful imported-transaction suggestions, including when statement text shares
no useful tokens with the historical merchant? This deliberately sits outside
production services until the experiment answers that question.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from sklearn.linear_model import LogisticRegression


@dataclass(frozen=True)
class EmbeddedExample:
    description: str
    category: str
    embedding: list[float]


@dataclass(frozen=True)
class Neighbor:
    description: str
    category: str
    similarity: float


@dataclass(frozen=True)
class CategoryScore:
    category: str
    score: float
    neighbor_count: int


@dataclass(frozen=True)
class Suggestion:
    category: str | None
    margin: float
    category_scores: list[CategoryScore]
    neighbors: list[Neighbor]


@dataclass(frozen=True)
class LogisticCategoryScore:
    category: str
    probability: float


@dataclass(frozen=True)
class LogisticSuggestion:
    category: str
    margin: float
    category_scores: list[LogisticCategoryScore]


@dataclass
class LogisticCategoryModel:
    classifier: LogisticRegression


def fit_logistic_category_model(
    examples: list[EmbeddedExample],
) -> LogisticCategoryModel:
    """Fit a small category classifier over frozen transaction embeddings."""
    classifier = LogisticRegression(
        class_weight="balanced",
        max_iter=1_000,
        random_state=0,
    )
    classifier.fit(
        [example.embedding for example in examples],
        [example.category for example in examples],
    )
    return LogisticCategoryModel(classifier)


def predict_logistic_category(
    query_embedding: list[float],
    model: LogisticCategoryModel,
) -> LogisticSuggestion:
    """Return ranked class probabilities from a fitted logistic model."""
    probabilities = model.classifier.predict_proba([query_embedding])[0]
    ranked = sorted(
        (
            LogisticCategoryScore(category, round(float(probability), 4))
            for category, probability in zip(
                model.classifier.classes_, probabilities, strict=True
            )
        ),
        key=lambda item: item.probability,
        reverse=True,
    )
    runner_up = ranked[1].probability if len(ranked) > 1 else 0.0
    return LogisticSuggestion(
        ranked[0].category,
        round(ranked[0].probability - runner_up, 4),
        ranked,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def suggest_category(
    query_embedding: list[float],
    examples: list[EmbeddedExample],
    *,
    neighbor_limit: int = 5,
    minimum_similarity: float = 0.35,
) -> Suggestion:
    """Rank categories by the squared similarity of their nearest examples.

    Squaring gives close neighbors more authority without pretending the result
    is a calibrated probability. The margin is the winning score minus runner-up.
    """
    ranked = sorted(
        (
            Neighbor(example.description, example.category, cosine_similarity(query_embedding, example.embedding))
            for example in examples
        ),
        key=lambda item: item.similarity,
        reverse=True,
    )
    neighbors = [item for item in ranked if item.similarity >= minimum_similarity][
        :neighbor_limit
    ]
    totals: dict[str, tuple[float, int]] = {}
    for neighbor in neighbors:
        score, count = totals.get(neighbor.category, (0.0, 0))
        totals[neighbor.category] = (score + neighbor.similarity**2, count + 1)
    category_scores = [
        CategoryScore(category, round(score, 4), count)
        for category, (score, count) in totals.items()
    ]
    category_scores.sort(key=lambda item: item.score, reverse=True)
    if not category_scores:
        return Suggestion(None, 0.0, [], neighbors)
    runner_up = category_scores[1].score if len(category_scores) > 1 else 0.0
    return Suggestion(
        category_scores[0].category,
        round(category_scores[0].score - runner_up, 4),
        category_scores,
        neighbors,
    )
