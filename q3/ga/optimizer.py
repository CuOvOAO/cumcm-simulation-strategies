"""Small, simulator-agnostic GA operating only through policy evaluation."""

from __future__ import annotations

import ast
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..fitness import Fitness
from ..logging_utils import write_json
from ..policy_params import PolicyParams
from .operators import crossover, mutate, random_params


@dataclass
class GenerationRecord:
    generation: int
    best_fitness: tuple
    median_fitness: tuple
    worst_fitness: tuple
    best_params: dict
    population_size: int
    unique_params: int


@dataclass
class GAResult:
    best_params: PolicyParams
    best_fitness: Fitness
    history: list[GenerationRecord]


class GAOptimizer:
    def __init__(
        self,
        evaluator: Callable[[PolicyParams], Any],
        population_size: int = 8,
        elite_count: int = 1,
        tournament_size: int = 3,
        mutation_probability: float = 0.2,
        mutation_scale: float = 0.1,
        seed: int = 0,
        log_dir: str | Path | None = None,
    ) -> None:
        if population_size < 2 or not 1 <= elite_count < population_size:
            raise ValueError("invalid population/elite size")
        if not 2 <= tournament_size <= population_size:
            raise ValueError("invalid tournament size")
        self.evaluator = evaluator
        self.population_size = population_size
        self.elite_count = elite_count
        self.tournament_size = tournament_size
        self.mutation_probability = mutation_probability
        self.mutation_scale = mutation_scale
        self.rng = random.Random(seed)
        self.seed = seed
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.population = [random_params(self.rng) for _ in range(population_size)]
        self.history: list[GenerationRecord] = []
        self.generation = 0

    @staticmethod
    def _fitness(result: Any) -> Fitness:
        value = result.fitness if hasattr(result, "fitness") else result
        if not isinstance(value, Fitness):
            raise TypeError("evaluator must return Fitness or an object with .fitness")
        return value

    def _evaluate(self) -> list[tuple[Fitness, PolicyParams]]:
        rows = [(self._fitness(self.evaluator(p)), p) for p in self.population]
        return sorted(rows, key=lambda item: item[0])

    def _tournament(self, ranked: list[tuple[Fitness, PolicyParams]]) -> PolicyParams:
        sample = self.rng.sample(ranked, self.tournament_size)
        return min(sample, key=lambda item: item[0])[1]

    def step(self) -> tuple[Fitness, PolicyParams]:
        ranked = self._evaluate()
        fitnesses = [pair[0] for pair in ranked]
        median = fitnesses[len(fitnesses) // 2]
        best_fitness, best_params = ranked[0]
        self.history.append(GenerationRecord(
            self.generation,
            best_fitness.to_tuple(),
            median.to_tuple(),
            fitnesses[-1].to_tuple(),
            best_params.to_dict(),
            len(ranked),
            len({tuple(sorted(p.to_dict().items())) for _, p in ranked}),
        ))
        if self.log_dir is not None:
            write_json(self.log_dir / f"generation_{self.generation:04d}.json", self.history[-1])
        next_population = [p for _, p in ranked[:self.elite_count]]
        while len(next_population) < self.population_size:
            a = self._tournament(ranked)
            b = self._tournament(ranked)
            child = mutate(crossover(a, b, self.rng), self.rng,
                           self.mutation_probability, self.mutation_scale)
            next_population.append(child)
        self.population = next_population
        self.generation += 1
        return best_fitness, best_params

    def run(self, generations: int) -> GAResult:
        if generations < 1:
            raise ValueError("generations must be positive")
        best: tuple[Fitness, PolicyParams] | None = None
        for _ in range(generations):
            current = self.step()
            if best is None or current[0] < best[0]:
                best = current
        assert best is not None
        return GAResult(best[1], best[0], list(self.history))

    def save_checkpoint(self, path: str | Path) -> Path:
        return write_json(path, {
            "config": {
                "population_size": self.population_size,
                "elite_count": self.elite_count,
                "tournament_size": self.tournament_size,
                "mutation_probability": self.mutation_probability,
                "mutation_scale": self.mutation_scale,
                "seed": self.seed,
            },
            "generation": self.generation,
            "population": [p.to_dict() for p in self.population],
            "history": self.history,
            "random_state_repr": repr(self.rng.getstate()),
        })

    @classmethod
    def load_checkpoint(cls, path: str | Path, evaluator: Callable[[PolicyParams], Any]) -> "GAOptimizer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        optimizer = cls(evaluator=evaluator, **payload["config"])
        optimizer.generation = int(payload["generation"])
        optimizer.population = [PolicyParams.repair(p) for p in payload["population"]]
        optimizer.history = [GenerationRecord(
            generation=row["generation"],
            best_fitness=tuple(row["best_fitness"]),
            median_fitness=tuple(row["median_fitness"]),
            worst_fitness=tuple(row["worst_fitness"]),
            best_params=row["best_params"],
            population_size=row["population_size"],
            unique_params=row["unique_params"],
        ) for row in payload["history"]]
        optimizer.rng.setstate(ast.literal_eval(payload["random_state_repr"]))
        return optimizer
