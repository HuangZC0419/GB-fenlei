# -*- coding: utf-8 -*-
"""参照表校验、冲突检测、特征提取与分类模型。"""

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import (
    CATEGORIES,
    CLASS_WEIGHT_POWER,
    CV_FOLDS,
    DEFAULT_SYSTEM_MAP,
    IDF_MODE,
    KEYWORD_FEATURE_SCALE,
    KEYWORD_HITS_SCALE,
    KEYWORD_RULES,
    KEYWORD_SATURATION,
    MAX_MODEL_CONFIDENCE,
    MIN_DOCUMENT_FREQUENCY,
    MIN_TEMPERATURE,
    MODEL_EPOCHS,
    MODEL_L2,
    MODEL_LR,
    NAME_PATTERNS,
    RANDOM_SEED,
)
from excel_io import ExcelError, pick, variant_code_key
from text import base_code, normalize_code, normalize_name, tokenize

FeatureVector = Dict[str, float]


@dataclass
class ReferenceData:
    training_examples: List[Tuple[str, str]]
    by_code: Dict[str, Dict[str, Any]]
    by_name: Dict[str, Dict[str, Any]]
    by_base: Dict[str, Dict[str, Any]]
    system_map: Dict[str, str]
    mapping: Dict[str, Any]
    conflicts: List[Dict[str, Any]]
    categories: List[str]
    warnings: List[str] = field(default_factory=list)
    excluded_rows: List[int] = field(default_factory=list)
    row_count: int = 0


def _majority(counter: Counter) -> Tuple[Any, int]:
    return counter.most_common(1)[0]


def _label_text(profession: str, system: str) -> str:
    return "{} / {}".format(profession, system) if system else profession


def _resolve_group(group: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counter = Counter((item["profession"], item["system"]) for item in group)
    (profession, system), votes = _majority(counter)
    total = sum(counter.values())
    return {
        "profession": profession,
        "system": system,
        "votes": votes,
        "total": total,
        "ratio": float(votes) / total if total else 0.0,
    }


def _conflict_for_group(group: Sequence[Dict[str, Any]], conflict_type: str) -> Optional[Dict[str, Any]]:
    counter = Counter((item["profession"], item["system"]) for item in group)
    if len(counter) <= 1:
        return None
    (profession, _system), _votes = _majority(counter)
    labels = [
        "{} {}票".format(_label_text(item[0], item[1]), count)
        for item, count in counter.most_common()
    ]
    first = group[0]
    return {
        "type": conflict_type,
        "code": first.get("code", ""),
        "name": first.get("name", ""),
        "count": sum(counter.values()),
        "labels": labels,
        "chosen": profession,
    }


def build_reference(
    records: Sequence[Dict[str, Any]],
    mapping_rows: Sequence[Dict[str, Any]],
) -> ReferenceData:
    """从参照表构建映射、冲突报告、查找索引和训练样本。

    类别完全由上传的参照表决定，不再依赖写死的固定分类。相同标准号、
    相同标准名称但选用专业/系统不一致的记录视为脏数据，整组排除出训练集。
    """
    mapping_hint: Dict[str, str] = {}
    for row in mapping_rows:
        profession = pick(row, "profession")
        system = pick(row, "system")
        if profession and system:
            mapping_hint[profession] = system

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for row in records:
        code = pick(row, "code")
        name = pick(row, "name")
        profession = pick(row, "profession")
        if not name or not profession:
            continue
        system = (
            pick(row, "system")
            or mapping_hint.get(profession)
            or DEFAULT_SYSTEM_MAP.get(profession, "")
        )
        items.append({
            "code": code,
            "name": name,
            "profession": profession,
            "system": system,
            "row": row.get("_row", ""),
        })

    if not items:
        raise ExcelError("INVALID_FILE", "参照表没有可用的分类记录，请检查标准名称和选用专业名称")

    # 训练集只保留完全干净的数据：
    # 1) 同号 + 同名但分类不一致；
    # 2) 同名不同号且分类不一致；
    # 3) 同号不同名且分类不一致。
    labels_by_name: Dict[str, set] = defaultdict(set)
    labels_by_code: Dict[str, set] = defaultdict(set)
    for item in items:
        label = (item["profession"], item["system"])
        name_key = normalize_name(item["name"])
        code_key = variant_code_key(item["code"])
        if name_key:
            labels_by_name[name_key].add(label)
        if code_key:
            labels_by_code[code_key].add(label)

    groups_by_code_name: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        code_key = variant_code_key(item["code"])
        name_key = normalize_name(item["name"])
        if code_key and name_key:
            groups_by_code_name[(code_key, name_key)].append(item)

    excluded_rows: set = set()
    excluded_conflicts: List[Dict[str, Any]] = []

    def add_conflict(
        conflict_type: str,
        group: Sequence[Dict[str, Any]],
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        counter = Counter((item["profession"], item["system"]) for item in group)
        if len(counter) <= 1:
            return
        rows = [item["row"] for item in group if item.get("row") != ""]
        if not rows or set(rows).issubset(excluded_rows):
            return
        excluded_rows.update(rows)
        excluded_conflicts.append({
            "type": conflict_type,
            "code": code if code is not None else group[0]["code"],
            "name": name if name is not None else group[0]["name"],
            "count": len(group),
            "labels": [
                "{} {}票".format(_label_text(profession, system), count)
                for (profession, system), count in counter.most_common()
            ],
            "chosen": "",
            "rows": rows,
        })

    for group in groups_by_code_name.values():
        add_conflict("同号同名不同分类", group)

    for name_key, labels in labels_by_name.items():
        if len(labels) <= 1:
            continue
        group = [
            item for item in items
            if normalize_name(item["name"]) == name_key
        ]
        add_conflict(
            "同名不同分类",
            group,
            code="、".join(sorted({item["code"] for item in group if item["code"]})),
        )

    for code_key, labels in labels_by_code.items():
        if len(labels) <= 1:
            continue
        group = [
            item for item in items
            if variant_code_key(item["code"]) == code_key
        ]
        add_conflict(
            "同号不同分类",
            group,
            name="、".join(sorted({item["name"] for item in group if item["name"]})),
        )

    if excluded_conflicts:
        warnings.append(
            "参照表中同号同名、同名不同号或同号不同名且分类不一致："
            "{} 组、{} 行，已整组排除出训练集".format(
                len(excluded_conflicts), len(excluded_rows)
            )
        )

    items = [item for item in items if item.get("row", "") not in excluded_rows]
    if not items:
        raise ExcelError(
            "INVALID_FILE", "参照表的记录全部存在分类冲突，没有可用于训练的干净数据"
        )

    categories = sorted({item["profession"] for item in items})
    pair_counts: Counter = Counter()
    profession_systems: Dict[str, Counter] = defaultdict(Counter)
    system_professions: Dict[str, Counter] = defaultdict(Counter)
    for item in items:
        pair = (item["profession"], item["system"])
        pair_counts[pair] += 1
        profession_systems[item["profession"]][item["system"]] += 1
        system_professions[item["system"]][item["profession"]] += 1

    profession_to_system = {
        profession: _majority(counter)[0]
        for profession, counter in profession_systems.items()
    }
    system_to_profession = {
        system: _majority(counter)[0]
        for system, counter in system_professions.items()
    }

    issues: List[Dict[str, Any]] = []
    for profession, counter in sorted(profession_systems.items()):
        if len(counter) > 1:
            issues.append({
                "type": "专业对应多个系统",
                "profession": profession,
                "values": ["{}（{}票）".format(name, count) for name, count in counter.most_common()],
            })
    for system, counter in sorted(system_professions.items()):
        if len(counter) > 1:
            issues.append({
                "type": "系统对应多个专业",
                "system": system,
                "values": ["{}（{}票）".format(name, count) for name, count in counter.most_common()],
            })
    for profession, system in sorted(mapping_hint.items()):
        chosen = profession_to_system.get(profession)
        if chosen and chosen != system:
            issues.append({
                "type": "映射表与总表不一致",
                "profession": profession,
                "values": ["映射表：{}；总表多数：{}".format(system, chosen)],
            })

    inverse_ok = all(
        system_to_profession.get(system) == profession
        for profession, system in profession_to_system.items()
    )
    is_one_to_one = not issues and inverse_ok and len(profession_to_system) == len(system_to_profession)

    # 冲突检测：按标准号、按标准名称分别分组。
    by_code_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_name_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_base_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        code_key = normalize_code(item["code"])
        name_key = normalize_name(item["name"])
        if code_key:
            by_code_groups[code_key].append(item)
            by_base_groups[base_code(code_key)].append(item)
        if name_key:
            by_name_groups[name_key].append(item)

    conflicts: List[Dict[str, Any]] = list(excluded_conflicts)
    for group in by_code_groups.values():
        conflict = _conflict_for_group(group, "标准号")
        if conflict:
            conflicts.append(conflict)
    for group in by_name_groups.values():
        conflict = _conflict_for_group(group, "标准名称")
        if conflict:
            conflicts.append(conflict)

    by_code = {
        key: _resolve_group(group)
        for key, group in by_code_groups.items()
    }
    by_base = {
        key: _resolve_group(group)
        for key, group in by_base_groups.items()
        if key
    }

    # 名称必须唯一对应一个专业，才允许用于名称匹配和训练。
    by_name: Dict[str, Dict[str, Any]] = {}
    ambiguous_names: List[str] = []
    for key, group in by_name_groups.items():
        labels = Counter((item["profession"], item["system"]) for item in group)
        if len(labels) == 1:
            by_name[key] = _resolve_group(group)
        else:
            ambiguous_names.append(group[0]["name"])
    if ambiguous_names:
        preview = "、".join(ambiguous_names[:5])
        suffix = " 等 {} 个".format(len(ambiguous_names)) if len(ambiguous_names) > 5 else ""
        warnings.append("以下名称对应多个专业，未参与训练和名称匹配：{}{}".format(preview, suffix))

    training_by_name: Dict[str, Tuple[str, str]] = {}
    for item in items:
        key = normalize_name(item["name"])
        if key not in by_name:
            continue
        training_by_name.setdefault(key, (item["name"], item["profession"]))
    training_examples = list(training_by_name.values())
    if not training_examples:
        warnings.append("参照表没有可用于训练的唯一名称记录")

    system_map = dict(DEFAULT_SYSTEM_MAP)
    system_map.update(profession_to_system)

    mapping = {
        "is_one_to_one": is_one_to_one,
        "profession_to_system": profession_to_system,
        "system_to_profession": system_to_profession,
        "issues": issues,
        "categories": categories,
    }

    return ReferenceData(
        training_examples=training_examples,
        by_code=by_code,
        by_name=by_name,
        by_base=by_base,
        system_map=system_map,
        mapping=mapping,
        conflicts=conflicts,
        categories=categories,
        warnings=warnings,
        excluded_rows=sorted(excluded_rows),
        row_count=len(records),
    )


class FeatureExtractor:
    """字符 n-gram TF-IDF + 关键词 + 名称结构特征。"""

    def __init__(
        self,
        min_document_frequency: int = MIN_DOCUMENT_FREQUENCY,
        keyword_scale: float = KEYWORD_FEATURE_SCALE,
        keyword_hits_scale: float = KEYWORD_HITS_SCALE,
        idf_mode: str = IDF_MODE,
    ) -> None:
        self.min_document_frequency = max(1, min_document_frequency)
        self.keyword_scale = max(0.0, keyword_scale)
        self.keyword_hits_scale = max(0.0, keyword_hits_scale)
        self.idf_mode = idf_mode if idf_mode in ("smooth", "sqrt", "none") else "smooth"
        self._document_frequency: Counter = Counter()
        self._document_count = 0

    def fit(self, names: Sequence[str]) -> "FeatureExtractor":
        self._document_frequency = Counter()
        self._document_count = 0
        for name in names:
            for token in set(tokenize(name)):
                self._document_frequency[token] += 1
            self._document_count += 1
        if len(names) < 20:
            self.min_document_frequency = 1
        return self

    def _idf(self, token: str) -> float:
        if self.idf_mode == "none":
            return 1.0
        document_frequency = self._document_frequency.get(token, 0)
        base = math.log((self._document_count + 1.0) / (document_frequency + 1.0))
        if self.idf_mode == "sqrt":
            return math.sqrt(base + 1.0)
        return base + 1.0

    def transform(self, name: str) -> FeatureVector:
        vector: FeatureVector = {}
        counts = Counter(tokenize(name))
        for token, count in counts.items():
            if self._document_frequency.get(token, 0) < self.min_document_frequency:
                continue
            vector["ng:" + token] = (1.0 + math.log(count)) * self._idf(token)

        for category, rules in KEYWORD_RULES.items():
            hits = [(keyword, weight) for keyword, weight in rules if keyword in name]
            weight_sum = sum(weight for _keyword, weight in hits)
            max_weight = max([weight for _keyword, weight in hits], default=0)
            vector["kw:" + category] = (
                min(1.0, float(weight_sum) / KEYWORD_SATURATION) * self.keyword_scale
            )
            vector["kwmax:" + category] = min(1.0, float(max_weight) / 30.0) * self.keyword_scale
            if self.keyword_hits_scale > 0.0:
                vector["kwhits:" + category] = (
                    min(1.0, float(len(hits)) / 3.0)
                    * self.keyword_scale
                    * self.keyword_hits_scale
                )

        for pattern in NAME_PATTERNS:
            if pattern in name:
                vector["pat:" + pattern] = 1.0

        return vector

    def keyword_hits(self, name: str) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        for category, rules in KEYWORD_RULES.items():
            for keyword, weight in rules:
                if keyword in name:
                    hits.append({
                        "category": category,
                        "keyword": keyword,
                        "weight": weight,
                    })
        hits.sort(key=lambda item: (item["weight"], len(item["keyword"])), reverse=True)
        return hits[:8]


def _class_weights(
    labels: Sequence[int],
    power: float = CLASS_WEIGHT_POWER,
    num_classes: int = len(CATEGORIES),
) -> List[float]:
    """按类别频率的逆幂次加权；power=0 时各类权重均为 1。"""
    counts = Counter(labels)
    total = len(labels)
    if total == 0 or power == 0.0:
        return [1.0] * num_classes
    return [
        (float(total) / (num_classes * counts[label_index])) ** power
        if counts.get(label_index) else 1.0
        for label_index in range(num_classes)
    ]


class SoftmaxRegression:
    """纯 Python 多项逻辑回归，稀疏权重，Adam 全批量训练。"""

    def __init__(
        self,
        num_classes: int,
        l2: float = MODEL_L2,
        lr: float = MODEL_LR,
        epochs: int = MODEL_EPOCHS,
        class_weights: Optional[Sequence[float]] = None,
    ) -> None:
        self.num_classes = num_classes
        self.l2 = l2
        self.lr = lr
        self.epochs = epochs
        self.class_weights = (
            [float(weight) for weight in class_weights]
            if class_weights is not None else [1.0] * num_classes
        )
        self.weights: List[Dict[str, float]] = [dict() for _ in range(num_classes)]
        self.bias: List[float] = [0.0] * num_classes

    def logits(self, vector: FeatureVector) -> List[float]:
        scores = list(self.bias)
        for feature, value in vector.items():
            for class_index in range(self.num_classes):
                weight = self.weights[class_index].get(feature)
                if weight is not None:
                    scores[class_index] += weight * value
        return scores

    def probabilities(self, vector: FeatureVector) -> List[float]:
        return _softmax(self.logits(vector))

    def fit(self, vectors: Sequence[FeatureVector], labels: Sequence[int]) -> "SoftmaxRegression":
        if not vectors:
            return self
        self.weights = [dict() for _ in range(self.num_classes)]
        self.bias = [0.0] * self.num_classes
        m_weight: List[Dict[str, float]] = [defaultdict(float) for _ in range(self.num_classes)]
        v_weight: List[Dict[str, float]] = [defaultdict(float) for _ in range(self.num_classes)]
        m_bias = [0.0] * self.num_classes
        v_bias = [0.0] * self.num_classes
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        scale = 1.0 / len(vectors)

        for epoch in range(1, self.epochs + 1):
            weight_grad: List[Dict[str, float]] = [defaultdict(float) for _ in range(self.num_classes)]
            bias_grad = [0.0] * self.num_classes
            for vector, label in zip(vectors, labels):
                probs = self.probabilities(vector)
                sample_weight = self.class_weights[label]
                for class_index in range(self.num_classes):
                    error = (
                        (probs[class_index] - (1.0 if class_index == label else 0.0))
                        * scale
                        * sample_weight
                    )
                    if error == 0.0:
                        continue
                    bias_grad[class_index] += error
                    bucket = weight_grad[class_index]
                    for feature, value in vector.items():
                        bucket[feature] += error * value
            for class_index in range(self.num_classes):
                bucket = weight_grad[class_index]
                for feature, weight in self.weights[class_index].items():
                    bucket[feature] += self.l2 * weight

            correction1 = 1.0 - beta1 ** epoch
            correction2 = 1.0 - beta2 ** epoch
            for class_index in range(self.num_classes):
                for feature, grad in weight_grad[class_index].items():
                    m_weight[class_index][feature] = beta1 * m_weight[class_index][feature] + (1 - beta1) * grad
                    v_weight[class_index][feature] = beta2 * v_weight[class_index][feature] + (1 - beta2) * grad * grad
                    m_hat = m_weight[class_index][feature] / correction1
                    v_hat = v_weight[class_index][feature] / correction2
                    current = self.weights[class_index].get(feature, 0.0)
                    self.weights[class_index][feature] = current - self.lr * m_hat / (math.sqrt(v_hat) + eps)

                m_bias[class_index] = beta1 * m_bias[class_index] + (1 - beta1) * bias_grad[class_index]
                v_bias[class_index] = beta2 * v_bias[class_index] + (1 - beta2) * bias_grad[class_index] ** 2
                m_hat_bias = m_bias[class_index] / correction1
                v_hat_bias = v_bias[class_index] / correction2
                self.bias[class_index] -= self.lr * m_hat_bias / (math.sqrt(v_hat_bias) + eps)

        return self


def _softmax(scores: Sequence[float]) -> List[float]:
    if not scores:
        return []
    maximum = max(scores)
    exps = [math.exp(score - maximum) for score in scores]
    total = sum(exps)
    if total <= 0:
        return [1.0 / len(scores)] * len(scores)
    return [value / total for value in exps]


def apply_temperature(logits: Sequence[Sequence[float]], temperature: float) -> List[List[float]]:
    if temperature <= 0:
        raise ValueError("temperature 必须大于 0")
    return [_softmax([score / temperature for score in row]) for row in logits]


def cap_probabilities(
    probabilities: Sequence[float], maximum: float = MAX_MODEL_CONFIDENCE
) -> List[float]:
    """把最高概率压到上限，同时保持概率和为 1。"""
    if not probabilities:
        return []
    top = max(probabilities)
    floor = 1.0 / len(probabilities)
    if top <= maximum or top <= floor:
        return list(probabilities)
    alpha = (maximum - floor) / (top - floor)
    return [alpha * value + (1.0 - alpha) * floor for value in probabilities]


def fit_temperature(logits: Sequence[Sequence[float]], labels: Sequence[int]) -> float:
    if not logits:
        return 1.0
    best_temperature = 1.0
    best_loss = float("inf")
    # 温度可能小于 1（模型偏保守），搜索区间从 0.1 开始避免卡在下界。
    for step in range(1, 61):
        temperature = 0.1 * step
        probabilities = apply_temperature(logits, temperature)
        loss = 0.0
        for row, label in zip(probabilities, labels):
            loss -= math.log(max(row[label], 1e-12))
        loss /= len(probabilities)
        if loss < best_loss:
            best_loss = loss
            best_temperature = temperature
    return best_temperature


def stratified_kfold(labels: Sequence[int], k: int, seed: int) -> List[Tuple[List[int], List[int]]]:
    if k < 2 or len(set(labels)) < 2:
        return []
    generator = random.Random(seed)
    by_label: Dict[int, List[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        by_label[label].append(index)
    for indices in by_label.values():
        generator.shuffle(indices)

    buckets: List[List[int]] = [[] for _ in range(k)]
    position = 0
    for label in sorted(by_label):
        for index in by_label[label]:
            buckets[position % k].append(index)
            position += 1

    all_indices = set(range(len(labels)))
    folds: List[Tuple[List[int], List[int]]] = []
    for test_indices in buckets:
        if not test_indices:
            continue
        folds.append((sorted(all_indices - set(test_indices)), sorted(test_indices)))
    return folds


def evaluate_predictions(
    labels: Sequence[int],
    probabilities: Sequence[Sequence[float]],
    categories: Sequence[str],
) -> Dict[str, Any]:
    predictions = [max(range(len(row)), key=lambda index: row[index]) for row in probabilities]
    total = len(labels)
    correct = sum(1 for truth, prediction in zip(labels, predictions) if truth == prediction)
    per_class: Dict[str, Dict[str, float]] = {}
    f1_scores: List[float] = []
    for class_index, name in enumerate(categories):
        true_positive = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth == class_index and prediction == class_index
        )
        false_positive = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth != class_index and prediction == class_index
        )
        false_negative = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth == class_index and prediction != class_index
        )
        support = sum(1 for truth in labels if truth == class_index)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        f1_scores.append(f1)

    return {
        "accuracy": float(correct) / total if total else 0.0,
        "macro_f1": sum(f1_scores) / len(f1_scores) if f1_scores else 0.0,
        "per_class": per_class,
        "sample_count": total,
    }


class ClassificationPipeline:
    """训练一次、预测多次。交叉验证与最终模型使用同一套参数。"""

    def __init__(self, reference: ReferenceData) -> None:
        self.reference = reference
        self.categories = list(reference.categories)
        if not reference.training_examples:
            raise ExcelError("INVALID_FILE", "参照表没有可用于训练的唯一名称记录")
        names = [name for name, _profession in reference.training_examples]
        labels = [self.categories.index(profession) for _name, profession in reference.training_examples]
        self.extractor = FeatureExtractor().fit(names)
        vectors = [self.extractor.transform(name) for name in names]
        self.model = SoftmaxRegression(
            num_classes=len(self.categories),
            class_weights=_class_weights(labels, num_classes=len(self.categories)),
        ).fit(vectors, labels)
        self._temperature, self._evaluation = self._cross_validate()
        self._evaluation["training_samples"] = len(reference.training_examples)

    def _cross_validate(self) -> Tuple[float, Dict[str, Any]]:
        examples = self.reference.training_examples
        labels = [self.categories.index(profession) for _name, profession in examples]
        if len(examples) < 4 or len(set(labels)) < 2:
            return 1.0, self._empty_evaluation("样本不足，未做交叉验证")

        counts = Counter(labels)
        folds_count = min(CV_FOLDS, min(counts.values()))
        if folds_count < 2:
            return 1.0, self._empty_evaluation("每个类别至少需要 2 条样本才能交叉验证")

        folds = stratified_kfold(labels, folds_count, RANDOM_SEED)
        logits: List[Optional[List[float]]] = [None] * len(examples)
        for train_indices, test_indices in folds:
            train_names = [examples[index][0] for index in train_indices]
            train_labels = [labels[index] for index in train_indices]
            extractor = FeatureExtractor().fit(train_names)
            vectors = [extractor.transform(name) for name in train_names]
            model = SoftmaxRegression(
                num_classes=len(self.categories),
                class_weights=_class_weights(
                    train_labels, num_classes=len(self.categories)
                ),
            ).fit(vectors, train_labels)
            for index in test_indices:
                name = examples[index][0]
                logits[index] = model.logits(extractor.transform(name))

        filled = [
            row if row is not None else [0.0] * len(self.categories)
            for row in logits
        ]
        temperature = max(fit_temperature(filled, labels), MIN_TEMPERATURE)
        probabilities = [
            cap_probabilities(row) for row in apply_temperature(filled, temperature)
        ]
        evaluation = evaluate_predictions(labels, probabilities, self.categories)
        evaluation["note"] = (
            "{} 折交叉验证，每折重新拟合特征和模型。关键词特征来自人工整理的领域词表，"
            "与参照表同源，指标偏乐观；样本量较小，结果仅作参考。".format(folds_count)
        )
        return temperature, evaluation

    @staticmethod
    def _empty_evaluation(note: str) -> Dict[str, Any]:
        return {
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "per_class": {},
            "sample_count": 0,
            "note": note,
        }

    def evaluation(self) -> Dict[str, Any]:
        return self._evaluation

    def _model_probabilities(self, name: str) -> List[float]:
        vector = self.extractor.transform(name)
        logits = [self.model.logits(vector)]
        calibrated = apply_temperature(logits, self._temperature)[0]
        return cap_probabilities(calibrated)

    def _top3(self, probabilities: Sequence[float]) -> List[Dict[str, Any]]:
        ranked = sorted(
            range(len(probabilities)),
            key=lambda index: probabilities[index],
            reverse=True,
        )
        return [
            {
                "profession": self.categories[index],
                "system": self.reference.system_map.get(self.categories[index], ""),
                "probability": round(float(probabilities[index]), 4),
            }
            for index in ranked[:3]
        ]

    def _reference_result(
        self,
        label: Dict[str, Any],
        method: str,
        confidence: float,
        probabilities: Sequence[float],
    ) -> Dict[str, Any]:
        return {
            "profession": label["profession"],
            "system": label["system"],
            "confidence": round(confidence, 4),
            "method": method,
            "source": "reference",
            "top3": self._top3(probabilities),
            "evidence": [
                "参照表命中：{}（一致率 {:.0%}）".format(method, label["ratio"])
            ],
            "detail": "参照表 {} 条同组记录，多数票 {}/{}。".format(
                label["total"], label["votes"], label["total"]
            ),
        }

    def predict(self, name: str, code: str = "") -> Dict[str, Any]:
        """对单条标准给出专业、系统、置信度和 Top 3。"""
        clean_name = str(name or "").strip()
        probabilities = self._model_probabilities(clean_name)

        code_key = normalize_code(code)
        if code_key and code_key in self.reference.by_code:
            label = self.reference.by_code[code_key]
            confidence = 0.99 if label["ratio"] >= 1.0 else 0.85 + 0.1 * label["ratio"]
            return self._reference_result(label, "参照表·标准号", confidence, probabilities)

        name_key = normalize_name(clean_name)
        if name_key and name_key in self.reference.by_name:
            label = self.reference.by_name[name_key]
            return self._reference_result(label, "参照表·名称", 0.98, probabilities)

        code_base = base_code(code_key) if code_key else ""
        if code_base and code_base in self.reference.by_base:
            label = self.reference.by_base[code_base]
            confidence = 0.88 + 0.05 * label["ratio"]
            return self._reference_result(label, "参照表·标准号主体", confidence, probabilities)

        ranked = sorted(range(len(probabilities)), key=lambda index: probabilities[index], reverse=True)
        top_index = ranked[0]
        profession = self.categories[top_index]
        confidence = max(0.0, min(1.0, float(probabilities[top_index])))
        hits = self.extractor.keyword_hits(clean_name)
        evidence = [
            "{}：{}（{} 分）".format(hit["category"], hit["keyword"], hit["weight"])
            for hit in hits[:6]
        ]
        if not evidence:
            evidence = ["无领域关键词命中"]

        return {
            "profession": profession,
            "system": self.reference.system_map.get(profession, ""),
            "confidence": round(confidence, 4),
            "method": "模型",
            "source": "model",
            "top3": self._top3(probabilities),
            "evidence": evidence,
            "detail": "字符 n-gram + 关键词特征，温度校准后的模型概率。",
        }


def classify_pending_groups(
    pipeline: ClassificationPipeline,
    items: Sequence[Dict[str, Any]],
    threshold: float,
    dedup_reports: Sequence[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """只对无歧义的组调用模型；有歧义的组留空，交给人工分类。"""
    rows: List[Dict[str, Any]] = []
    low_rows: List[Dict[str, Any]] = []
    profession_counts: Counter = Counter()
    system_counts: Counter = Counter()
    low_count = 0

    for item in items:
        status = item.get("status", "auto")
        result: Dict[str, Any] = {}
        if status == "auto":
            result = pipeline.predict(item.get("name", ""), item.get("code", ""))
            profession = result["profession"]
            system = result["system"]
            confidence = float(result["confidence"])
            low = confidence < threshold
            if low:
                low_count += 1
            profession_counts[profession] += 1
            system_counts[system] += 1
        else:
            profession = ""
            system = ""
            confidence = 0.0
            low = False

        row = {
            "index": item["index"],
            "code": item.get("code", ""),
            "name": item.get("name", ""),
            "system": system,
            "profession": profession,
            "confidence": round(confidence, 4),
            "method": result.get("method", "人工"),
            "source": result.get("source", "manual"),
            "top3": result.get("top3", []),
            "evidence": result.get("evidence", []),
            "detail": result.get("detail", ""),
            "low_confidence": low,
            "duplicate_count": item.get("count", 1),
            "source_rows": list(item.get("source_rows", [])),
            "units": list(item.get("units", [])),
            "status": status,
            "reason": item.get("reason", ""),
            "needs_confirmation": bool(item.get("needs_confirmation")),
        }
        rows.append(row)
        if low:
            low_rows.append(row)

    auto_rows = [row for row in rows if row["status"] == "auto"]
    manual_rows = [row for row in rows if row["status"] == "manual"]
    multi_unit_count = sum(1 for row in rows if row["needs_confirmation"])
    summary_meta = dict(meta or {})
    summary = {
        "raw_rows": summary_meta.get(
            "raw_rows", sum(int(item.get("count", 1)) for item in items)
        ),
        "unique_rows": len(rows),
        "group_count": len(rows),
        "auto_count": len(auto_rows),
        "manual_count": len(manual_rows),
        "multi_unit_count": multi_unit_count,
        "low_confidence_count": low_count,
        "threshold": threshold,
        "dedup_basis": summary_meta.get("dedup_basis", ""),
    }

    return {
        "rows": rows,
        "auto_rows": auto_rows,
        "manual_rows": manual_rows,
        "low_rows": low_rows,
        "categories": [
            {
                "profession": profession,
                "system": pipeline.reference.system_map.get(profession, ""),
            }
            for profession in pipeline.categories
        ],
        "summary": summary,
        "stats": {
            "professions": dict(profession_counts),
            "systems": dict(system_counts),
            "total": len(auto_rows),
        },
        "conflicts": pipeline.reference.conflicts,
        "mapping": pipeline.reference.mapping,
        "warnings": pipeline.reference.warnings,
        "dedup_reports": list(dedup_reports),
        "evaluation": pipeline.evaluation(),
    }


def classify_pending(
    pipeline: ClassificationPipeline,
    items: Sequence[Dict[str, Any]],
    threshold: float,
    dedup_reports: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """批量分类去重后的标准，并生成统计与低置信度清单。"""
    rows: List[Dict[str, Any]] = []
    low_rows: List[Dict[str, Any]] = []
    method_counts: Counter = Counter()
    confidence_bins: Counter = Counter()
    profession_counts: Counter = Counter()
    system_counts: Counter = Counter()

    for index, item in enumerate(items, start=1):
        result = pipeline.predict(item["name"], item["code"])
        row = {
            "index": index,
            "code": item["code"],
            "name": item["name"],
            "system": result["system"],
            "profession": result["profession"],
            "confidence": result["confidence"],
            "method": result["method"],
            "source": result["source"],
            "top3": result["top3"],
            "evidence": result["evidence"],
            "detail": result["detail"],
            "low_confidence": result["confidence"] < threshold,
            "duplicate_count": item.get("count", 1),
            "source_rows": item.get("source_rows", []),
        }
        rows.append(row)
        method_counts[result["method"]] += 1
        profession_counts[result["profession"]] += 1
        system_counts[result["system"]] += 1

        if result["confidence"] >= 0.80:
            confidence_bins["高（≥0.80）"] += 1
        elif result["confidence"] >= 0.60:
            confidence_bins["中（0.60–0.79）"] += 1
        else:
            confidence_bins["低（<0.60）"] += 1

        if row["low_confidence"]:
            low_rows.append(row)

    raw_rows = sum(int(item.get("count", 1)) for item in items)
    reference_rows = sum(1 for row in rows if row["source"] == "reference")
    model_rows = len(rows) - reference_rows
    new_rows = [row for row in rows if row["source"] != "reference"]

    return {
        "rows": rows,
        "new_rows": new_rows,
        "low_rows": low_rows,
        "categories": [
            {
                "profession": profession,
                "system": pipeline.reference.system_map.get(profession, ""),
            }
            for profession in pipeline.categories
        ],
        "summary": {
            "raw_rows": raw_rows,
            "unique_rows": len(rows),
            "reference_rows": reference_rows,
            "model_rows": model_rows,
            "low_confidence_count": len(low_rows),
            "threshold": threshold,
            "method_counts": dict(method_counts),
            "confidence_bins": dict(confidence_bins),
        },
        "stats": {
            "professions": dict(profession_counts),
            "systems": dict(system_counts),
            "total": len(rows),
        },
        "conflicts": pipeline.reference.conflicts,
        "mapping": pipeline.reference.mapping,
        "warnings": pipeline.reference.warnings,
        "dedup_reports": list(dedup_reports),
        "evaluation": pipeline.evaluation(),
    }
