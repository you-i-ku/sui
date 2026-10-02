"""既存の名前の計算を、共通の値の照会の型につなぐ。格子は変更しない。"""

from dataclasses import dataclass, field

from .values import ValueSpace, InformationBounds


@dataclass(frozen=True, slots=True)
class NameQuery:
    action: str
    capture_ns: int

    def __post_init__(self):
        if type(self.action) is not str or type(self.capture_ns) is not int or self.capture_ns < 0:
            raise ValueError("name query: expected action and nonnegative integer capture_ns")


@dataclass(frozen=True, slots=True)
class NameBelief:
    model: object
    reading: object
    value_space: ValueSpace = field(default=ValueSpace("name", "1"), init=False)
    condition_keys: tuple = field(default=("action", "state"), init=False)

    def _history(self):
        if self.model.Q is not None:
            return tuple((ns, action, outcome) for ns, _, _, _, action, outcome in self.reading.sequence)
        # 静的なS1cは回数が十分統計量。時刻の読めない名前も回数に含める。
        return tuple((0, action, outcome) for action in self.model.actions
                     for outcome, count in zip(self.model.outcomes, self.reading.n[action])
                     for _ in range(int(count)))

    def _query(self, query):
        if not isinstance(query, NameQuery) or query.action not in self.model.actions:
            raise ValueError("names: expected NameQuery for a model action")
        return query

    def predictive(self, query):
        """返す値はモデルのoutcomes順の対数確率。"""
        from scipy.special import logsumexp
        from .inference import _s4d_log_belief, _s4d_likelihood, ledger, _log_A, _s4d_log_product
        from .lattice import learn, _column
        query = self._query(query)
        if self.model.Q is None:
            logs = _s4d_log_belief(self.model.D, [_s4d_likelihood(self.model.a[action],
                self.reading.n[action], learnable=action in self.model.learnable)
                for action in self.model.actions])
            counts = (ledger(self.model.a[query.action], self.reading.n[query.action])
                      if query.action in self.model.learnable else self.model.a[query.action])
            return logsumexp(_s4d_log_product(_log_A(counts), logs[None, :]), axis=1)
        posterior = learn(self.model, self.reading.sequence, until_ns=query.capture_ns)
        import numpy as np
        terms = []
        for (state, counts), weight in posterior.log_w.items():
            column = (_column(self.model, counts, query.action, state)
                      if query.action in self.model.learnable else self.model.a[query.action][:, state])
            terms.append(_s4d_log_product(weight, _log_A(column[:, None])[:, 0]))
        return logsumexp(np.array(terms), axis=0)

    def information(self, target, evidence, given) -> InformationBounds:
        """givenは(仕事,行動,測ったns|None)の列。名前と所要を分けられる枝で呼ぶ。"""
        if target != "state_and_parameters":
            raise ValueError("names: expected state_and_parameters target")
        query = self._query(evidence)
        from .lattice import hand_table, one_step_components
        table = hand_table(self.model, self._history(), tuple(given), query.action,
                           capture_ns=query.capture_ns)
        _, information = one_step_components(self.model, table, query.action,
                                              [0.] * len(self.model.outcomes))
        return InformationBounds(information, information)
